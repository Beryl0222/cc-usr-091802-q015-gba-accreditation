"""断网闸机的短期签名凭证与幂等回执。"""

import unittest
from dataclasses import replace
from datetime import timedelta

import helpers
from accreditation import (
    GateReceipt,
    NotEligibleError,
    PassageStatus,
    gate_scan,
    ingest_receipts,
    issue_credential,
    submit_roster,
    verify_credential,
)
from helpers import ATHLETE, EVENT_ID, KEY, NOW, TEAM_ID


class CredentialTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)

    def test_issue_requires_pass(self):
        with self.assertRaises(NotEligibleError):
            issue_credential(self.store, ATHLETE.person_id, EVENT_ID, NOW, KEY)

    def test_verify_signature_and_expiry(self):
        helpers.approve_all(self.store, ATHLETE.person_id)
        credential = issue_credential(self.store, ATHLETE.person_id, EVENT_ID, NOW, KEY)
        self.assertTrue(verify_credential(credential, KEY, NOW + timedelta(minutes=10)))
        # 短期有效:30 分钟后失效
        self.assertFalse(verify_credential(credential, KEY, NOW + timedelta(minutes=31)))
        # 篡改有效期或签名均不能通过
        tampered = replace(credential, expires_at=NOW + timedelta(hours=2))
        self.assertFalse(verify_credential(tampered, KEY, NOW + timedelta(minutes=10)))
        forged = replace(credential, signature="0" * 64)
        self.assertFalse(verify_credential(forged, KEY, NOW + timedelta(minutes=10)))
        # 错误的密钥不能通过
        self.assertFalse(verify_credential(credential, b"other-key", NOW))


class GateIngestTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        helpers.approve_all(self.store, ATHLETE.person_id)
        self.credential = issue_credential(self.store, ATHLETE.person_id, EVENT_ID, NOW, KEY)

    def scan(self, at, receipt_id):
        return gate_scan(self.credential, KEY, "gate-A1", at, receipt_id=receipt_id)

    def test_admitted_scan_becomes_entry(self):
        receipt = self.scan(NOW + timedelta(minutes=5), "rcpt-1")
        self.assertEqual(receipt.decision, "admitted")
        result = ingest_receipts(self.store, [receipt], KEY)
        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.person_id, ATHLETE.person_id)
        self.assertEqual(entry.roster_version, 1)
        self.assertEqual(entry.device_id, "gate-A1")
        self.assertIs(entry.conclusion, PassageStatus.PASS)
        self.assertEqual(entry.rule_snapshot["identity"], "rule-identity")

    def test_duplicate_upload_counts_once(self):
        receipt = self.scan(NOW + timedelta(minutes=5), "rcpt-1")
        first = ingest_receipts(self.store, [receipt], KEY)
        second = ingest_receipts(self.store, [receipt], KEY)
        self.assertEqual(len(first.entries), 1)
        self.assertEqual(second.duplicates, 1)
        self.assertEqual(len(second.entries), 0)
        self.assertEqual(len(self.store.entries), 1)
        # 同一批内重复也只算一次
        store2 = helpers.make_store()
        submit_roster(store2, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        helpers.approve_all(store2, ATHLETE.person_id)
        credential = issue_credential(store2, ATHLETE.person_id, EVENT_ID, NOW, KEY)
        receipt2 = gate_scan(credential, KEY, "gate-A1", NOW, receipt_id="rcpt-x")
        result = ingest_receipts(store2, [receipt2, receipt2], KEY)
        self.assertEqual((len(result.entries), result.duplicates), (1, 1))
        self.assertEqual(len(store2.entries), 1)

    def test_expired_credential_denied_at_gate(self):
        receipt = self.scan(NOW + timedelta(minutes=31), "rcpt-late")
        self.assertEqual(receipt.decision, "denied")
        result = ingest_receipts(self.store, [receipt], KEY)
        self.assertEqual(len(result.entries), 0)
        self.assertEqual(result.rejected, 1)
        self.assertIn("rcpt-late", self.store.receipts)  # 回执留存供审计

    def test_unknown_credential_rejected(self):
        receipt = GateReceipt(
            receipt_id="rcpt-ghost",
            credential_id="no-such-credential",
            person_id=ATHLETE.person_id,
            event_id=EVENT_ID,
            device_id="gate-A1",
            passed_at=NOW,
            decision="admitted",
        )
        result = ingest_receipts(self.store, [receipt], KEY)
        self.assertEqual(len(result.entries), 0)
        self.assertEqual(result.rejected, 1)


if __name__ == "__main__":
    unittest.main()
