"""材料规则生效期与按身份职责生成待核项目。"""

import unittest
from datetime import date

import helpers
from accreditation import (
    Material,
    MaterialRule,
    PassageStatus,
    Role,
    applicable_rules,
    passage_conclusion,
    publish_rule,
    submit_roster,
)
from helpers import (
    ATHLETE,
    COACH,
    EVENT_ID,
    MINOR,
    NOW,
    STAFF,
    TEAM_ID,
    TODAY,
)


class RuleApplicationTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()

    def test_pending_items_follow_identity_and_role(self):
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE, MINOR, COACH, STAFF], NOW)
        self.assertEqual(
            helpers.materials_of(self.store, ATHLETE.person_id),
            {Material.IDENTITY, Material.INSURANCE, Material.ANTI_DOPING},
        )
        # 未成年运动员额外需要监护同意
        self.assertEqual(
            helpers.materials_of(self.store, MINOR.person_id),
            {
                Material.IDENTITY,
                Material.INSURANCE,
                Material.ANTI_DOPING,
                Material.GUARDIAN_CONSENT,
            },
        )
        # 教练与随队人员无需反兴奋剂声明
        for person in (COACH, STAFF):
            self.assertEqual(
                helpers.materials_of(self.store, person.person_id),
                {Material.IDENTITY, Material.INSURANCE},
            )

    def test_rule_outside_effective_window_not_applied(self):
        future = MaterialRule(
            "rule-ad-coach-future", "HongKong", Material.ANTI_DOPING, "反兴奋剂中心",
            frozenset({Role.COACH}), False, date(2026, 11, 1), None, 1,
        )
        expired = MaterialRule(
            "rule-ad-coach-expired", "HongKong", Material.ANTI_DOPING, "反兴奋剂中心",
            frozenset({Role.COACH}), False, date(2025, 1, 1), date(2025, 12, 31), 1,
        )
        publish_rule(self.store, future)
        publish_rule(self.store, expired)
        event = self.store.events[EVENT_ID]
        materials = {r.material for r in applicable_rules(self.store, event, COACH)}
        self.assertNotIn(Material.ANTI_DOPING, materials)

    def test_latest_rule_version_wins(self):
        publish_rule(
            self.store,
            MaterialRule(
                "rule-identity-v2", "HongKong", Material.IDENTITY, "证件查验中心",
                frozenset({Role.ATHLETE, Role.COACH, Role.STAFF}), False,
                date(2026, 6, 1), None, 2,
            ),
        )
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        item = helpers.item_of(self.store, ATHLETE.person_id, Material.IDENTITY)
        self.assertEqual(item.rule_id, "rule-identity-v2")


class RosterSubstitutionTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()

    def test_substitution_forms_decision_with_basis(self):
        from accreditation import DecisionKind

        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE, COACH], NOW)
        helpers.approve_all(self.store, ATHLETE.person_id)
        helpers.approve_all(self.store, COACH.person_id)
        roster_v2 = submit_roster(
            self.store, EVENT_ID, TEAM_ID, [COACH, MINOR], NOW,
            basis="运动员伤病换人,附医疗证明", decided_by="team-manager",
        )
        self.assertEqual(roster_v2.version, 2)
        substitutions = [
            d for d in self.store.decisions.values()
            if d.kind is DecisionKind.SUBSTITUTION
        ]
        self.assertEqual(len(substitutions), 1)
        self.assertIn("医疗证明", substitutions[0].basis)
        self.assertIn(ATHLETE.person_id, substitutions[0].basis)
        self.assertIn(MINOR.person_id, substitutions[0].basis)
        # 被换下者失去通行资格,留队成员的核验结论不受影响
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, TODAY),
            PassageStatus.DENY,
        )
        self.assertIs(
            passage_conclusion(self.store, COACH.person_id, EVENT_ID, TODAY),
            PassageStatus.PASS,
        )
        # 换上者按身份职责产生新的待核项目
        self.assertIn(Material.GUARDIAN_CONSENT, helpers.materials_of(self.store, MINOR.person_id))

    def test_substitution_requires_basis(self):
        from accreditation import DomainError

        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        with self.assertRaises(DomainError):
            submit_roster(self.store, EVENT_ID, TEAM_ID, [MINOR], NOW)


if __name__ == "__main__":
    unittest.main()
