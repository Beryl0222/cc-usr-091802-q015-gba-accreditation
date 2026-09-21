"""按角色裁剪视图:原件仅授权审核岗可见,场馆接驳只见结论。"""

import unittest

import helpers
from accreditation import (
    Actor,
    ActorRole,
    Material,
    PermissionDeniedError,
    item_documents,
    passage_view,
    submit_document,
    submit_roster,
)
from helpers import ATHLETE, EVENT_ID, NOW, TEAM_ID, TODAY


class AccessViewTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        self.identity = helpers.item_of(self.store, ATHLETE.person_id, Material.IDENTITY)
        submit_document(self.store, self.identity.item_id, Material.IDENTITY,
                        "vault://docs/id-001", TEAM_ID, NOW)

    def test_reviewer_can_read_originals(self):
        reviewer = Actor("rev-1", ActorRole.REVIEWER)
        documents = item_documents(self.store, self.identity.item_id, reviewer)
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].content_ref, "vault://docs/id-001")

    def test_other_roles_cannot_read_originals(self):
        for role in (ActorRole.VENUE, ActorRole.SHUTTLE, ActorRole.ORGANIZER, ActorRole.TEAM):
            with self.assertRaises(PermissionDeniedError):
                item_documents(self.store, self.identity.item_id, Actor("x", role))

    def test_passage_view_carries_conclusion_only(self):
        view = passage_view(self.store, ATHLETE.person_id, EVENT_ID, TODAY)
        self.assertEqual(
            set(view),
            {"person_id", "name", "event_id", "status", "as_of"},
        )
        self.assertEqual(view["status"], "deny")  # 材料未核,结论为不可通行
        self.assertEqual(view["name"], ATHLETE.name)


if __name__ == "__main__":
    unittest.main()
