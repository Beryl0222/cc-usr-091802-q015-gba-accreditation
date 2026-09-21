"""赛后从入场记录查回名单版本、核验机构、例外决定与设备回执。"""

import unittest
from datetime import date, timedelta

import helpers
from accreditation import (
    DecisionKind,
    Material,
    appeal_item,
    gate_scan,
    grant_medical_exemption,
    ingest_receipts,
    issue_credential,
    review_item,
    submit_roster,
    trace_entry,
)
from helpers import ATHLETE, EVENT_ID, KEY, NOW, TEAM_ID


class EntryTraceTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        identity = helpers.item_of(self.store, ATHLETE.person_id, Material.IDENTITY)
        insurance = helpers.item_of(self.store, ATHLETE.person_id, Material.INSURANCE)
        anti_doping = helpers.item_of(self.store, ATHLETE.person_id, Material.ANTI_DOPING)
        review_item(self.store, identity.item_id, True, "证件有效", "rev-1", NOW)
        # 保险先被驳回,申诉后成立
        review_item(self.store, insurance.item_id, False, "保单信息与名单不符", "rev-1", NOW)
        appeal_item(self.store, insurance.item_id, True,
                    "申诉补充批单后成立", "rev-2", NOW)
        # 反兴奋剂声明获临时医疗豁免
        grant_medical_exemption(self.store, anti_doping.item_id, date(2026, 10, 5),
                                "临时医疗豁免,附队医证明", "medical-officer", NOW)
        credential = issue_credential(self.store, ATHLETE.person_id, EVENT_ID, NOW, KEY)
        receipt = gate_scan(credential, KEY, "gate-A1", NOW + timedelta(minutes=5),
                            receipt_id="rcpt-trace")
        self.entry = ingest_receipts(self.store, [receipt], KEY).entries[0]

    def test_trace_recovers_full_context(self):
        trace = trace_entry(self.store, self.entry.entry_id)
        # 名单版本
        self.assertEqual(trace.roster.version, 1)
        self.assertIn(ATHLETE.person_id, trace.roster.member_ids)
        # 各材料的核验机构
        self.assertEqual(
            trace.agencies,
            {
                "identity": "证件查验中心",
                "insurance": "保险核验平台",
                "anti_doping": "反兴奋剂中心",
            },
        )
        # 例外决定:申诉与临时医疗豁免,均带依据
        kinds = [d.kind for d in trace.exception_decisions]
        self.assertEqual(
            kinds, [DecisionKind.APPEAL, DecisionKind.MEDICAL_EXEMPTION]
        )
        self.assertTrue(all(d.basis for d in trace.exception_decisions))
        # 设备回执
        self.assertEqual(trace.receipt.receipt_id, "rcpt-trace")
        self.assertEqual(trace.receipt.device_id, "gate-A1")
        self.assertEqual(trace.receipt.decision, "admitted")


if __name__ == "__main__":
    unittest.main()
