"""已发生的入场不随后来规则改变。"""

import unittest
from datetime import date, timedelta

import helpers
from accreditation import (
    Material,
    MaterialRule,
    NotEligibleError,
    PassageStatus,
    Role,
    gate_scan,
    ingest_receipts,
    issue_credential,
    passage_conclusion,
    publish_rule,
    refresh_event_cases,
    submit_roster,
    trace_entry,
)
from helpers import ATHLETE, EVENT_ID, KEY, NOW, STAFF, TEAM_ID, TODAY


class EntryImmutabilityTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE, STAFF], NOW)
        helpers.approve_all(self.store, ATHLETE.person_id)
        helpers.approve_all(self.store, STAFF.person_id)
        credential = issue_credential(self.store, STAFF.person_id, EVENT_ID, NOW, KEY)
        receipt = gate_scan(credential, KEY, "gate-A1", NOW + timedelta(minutes=5),
                            receipt_id="rcpt-staff")
        self.entry = ingest_receipts(self.store, [receipt], KEY).entries[0]

    def test_entry_survives_stricter_rule(self):
        # 赛区发布更严规则:随队人员也需反兴奋剂声明
        publish_rule(
            self.store,
            MaterialRule(
                "rule-ad-staff", "HongKong", Material.ANTI_DOPING, "反兴奋剂中心",
                frozenset({Role.STAFF}), False, date(2026, 6, 1), None, 1,
            ),
        )
        refresh_event_cases(self.store, EVENT_ID)
        # 新规则下该人员当前不再具备通行资格,也不能再签凭证
        self.assertIs(
            passage_conclusion(self.store, STAFF.person_id, EVENT_ID, TODAY),
            PassageStatus.DENY,
        )
        with self.assertRaises(NotEligibleError):
            issue_credential(self.store, STAFF.person_id, EVENT_ID, NOW, KEY)
        # 但已发生的入场记录保持原结论与规则快照
        stored = self.store.entries[self.entry.entry_id]
        self.assertIs(stored.conclusion, PassageStatus.PASS)
        self.assertEqual(
            stored.rule_snapshot,
            {"identity": "rule-identity", "insurance": "rule-insurance"},
        )
        trace = trace_entry(self.store, self.entry.entry_id)
        self.assertIs(trace.entry.conclusion, PassageStatus.PASS)
        self.assertEqual(trace.roster.version, 1)

    def test_entry_survives_roster_substitution(self):
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW,
                      basis="随队人员行程调整", decided_by="team-manager")
        self.assertIs(
            passage_conclusion(self.store, STAFF.person_id, EVENT_ID, TODAY),
            PassageStatus.DENY,
        )
        stored = self.store.entries[self.entry.entry_id]
        self.assertIs(stored.conclusion, PassageStatus.PASS)
        self.assertEqual(stored.roster_version, 1)


if __name__ == "__main__":
    unittest.main()
