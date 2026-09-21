"""赛前看板:按紧迫程度排列缺件与到期项。"""

import unittest
from datetime import date, timedelta

import helpers
from accreditation import Material, pre_event_board, review_item, submit_roster
from helpers import ATHLETE, COACH, EVENT_ID, NOW, STAFF, STAFF2, TEAM_ID, TODAY


class PreEventBoardTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID,
                      [ATHLETE, COACH, STAFF, STAFF2], NOW)
        # 教练材料齐全且长期有效,不应出现在看板上
        helpers.approve_all(self.store, COACH.person_id)
        # 运动员缺证件
        for item in helpers.case_of(self.store, ATHLETE.person_id).items:
            if item.material is not Material.IDENTITY:
                review_item(self.store, item.item_id, True, "核验通过", "rev-1", NOW)
        # 随队甲保险将在赛前到期
        for item in helpers.case_of(self.store, STAFF.person_id).items:
            until = date(2026, 9, 26) if item.material is Material.INSURANCE else None
            review_item(self.store, item.item_id, True, "核验通过", "rev-1", NOW,
                        valid_until=until)
        # 随队乙保险已经过期
        for item in helpers.case_of(self.store, STAFF2.person_id).items:
            until = TODAY - timedelta(days=2) if item.material is Material.INSURANCE else None
            review_item(self.store, item.item_id, True, "核验通过", "rev-1", NOW,
                        valid_until=until)

    def test_board_sorted_by_urgency(self):
        board = pre_event_board(self.store, EVENT_ID, TODAY)
        seen = [(e.person_id, e.material, e.kind, e.days_remaining) for e in board]
        self.assertEqual(
            seen,
            [
                (STAFF2.person_id, Material.INSURANCE, "expiring", -2),
                (STAFF.person_id, Material.INSURANCE, "expiring", 6),
                (ATHLETE.person_id, Material.IDENTITY, "missing", 11),
            ],
        )
        self.assertNotIn(COACH.person_id, [e.person_id for e in board])

    def test_board_can_filter_by_team(self):
        board = pre_event_board(self.store, EVENT_ID, TODAY, team_id="no-such-team")
        self.assertEqual(board, [])


if __name__ == "__main__":
    unittest.main()
