"""两地结论冲突:只暂停相关个人,交指定人员复核。"""

import unittest

import helpers
from accreditation import (
    DecisionKind,
    PassageStatus,
    passage_conclusion,
    passage_view,
    record_clearance,
    resolve_conflict,
    submit_roster,
)
from helpers import ATHLETE, COACH, EVENT_ID, NOW, TEAM_ID, TODAY


class ConflictTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE, COACH], NOW)
        helpers.approve_all(self.store, ATHLETE.person_id)
        helpers.approve_all(self.store, COACH.person_id)

    def trigger_conflict(self):
        record_clearance(self.store, ATHLETE.person_id, EVENT_ID,
                         "Guangdong", PassageStatus.PASS, "主场预检通过", NOW)
        return record_clearance(self.store, ATHLETE.person_id, EVENT_ID,
                                "HongKong", PassageStatus.DENY, "口岸抽检存疑", NOW)

    def test_agreeing_regions_do_not_suspend(self):
        record_clearance(self.store, ATHLETE.person_id, EVENT_ID,
                         "Guangdong", PassageStatus.PASS, "主场预检通过", NOW)
        task = record_clearance(self.store, ATHLETE.person_id, EVENT_ID,
                                "HongKong", PassageStatus.PASS, "口岸复核通过", NOW)
        self.assertIsNone(task)
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, TODAY),
            PassageStatus.PASS,
        )

    def test_conflict_suspends_individual_only(self):
        task = self.trigger_conflict()
        self.assertIsNotNone(task)
        self.assertEqual(task.assignee, helpers.REVIEWER)  # 指定复核人员
        self.assertEqual(task.status, "open")
        # 当事人暂停,场馆视图同步反映
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, TODAY),
            PassageStatus.SUSPENDED,
        )
        self.assertEqual(
            passage_view(self.store, ATHLETE.person_id, EVENT_ID, TODAY)["status"],
            "suspended",
        )
        # 不扩大到全队
        self.assertIs(
            passage_conclusion(self.store, COACH.person_id, EVENT_ID, TODAY),
            PassageStatus.PASS,
        )
        self.assertEqual(len(self.store.review_tasks), 1)

    def test_resolution_pass_restores_passage(self):
        task = self.trigger_conflict()
        decision = resolve_conflict(self.store, task.task_id, PassageStatus.PASS,
                                    "复核确认材料真实有效", helpers.REVIEWER, NOW)
        self.assertIs(decision.kind, DecisionKind.CONFLICT_RESOLUTION)
        self.assertEqual(task.status, "resolved")
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, TODAY),
            PassageStatus.PASS,
        )

    def test_resolution_deny_blocks_despite_approved_items(self):
        task = self.trigger_conflict()
        resolve_conflict(self.store, task.task_id, PassageStatus.DENY,
                         "复核确认证件系伪造", helpers.REVIEWER, NOW)
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, TODAY),
            PassageStatus.DENY,
        )


if __name__ == "__main__":
    unittest.main()
