"""审核、续证、资格申诉与临时医疗豁免决定。"""

import unittest
from datetime import date

import helpers
from accreditation import (
    DecisionKind,
    DomainError,
    Material,
    PassageStatus,
    appeal_item,
    grant_medical_exemption,
    passage_conclusion,
    renew_item,
    review_item,
    submit_roster,
)
from helpers import ATHLETE, EVENT_ID, NOW, TEAM_ID, TODAY


class ReviewDecisionTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)

    def conclusion(self, on=TODAY):
        return passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, on)

    def test_all_approved_passes(self):
        helpers.approve_all(self.store, ATHLETE.person_id)
        self.assertIs(self.conclusion(), PassageStatus.PASS)

    def test_missing_item_denies(self):
        for item in helpers.case_of(self.store, ATHLETE.person_id).items:
            if item.material is not Material.INSURANCE:
                review_item(self.store, item.item_id, True, "核验通过", "rev-1", NOW)
        self.assertIs(self.conclusion(), PassageStatus.DENY)

    def test_expired_material_denies(self):
        helpers.approve_all(self.store, ATHLETE.person_id)
        insurance = helpers.item_of(self.store, ATHLETE.person_id, Material.INSURANCE)
        review_item(self.store, insurance.item_id, True, "保单有效至 9 月 25 日",
                    "rev-1", NOW, valid_until=date(2026, 9, 25))
        self.assertIs(self.conclusion(date(2026, 9, 24)), PassageStatus.PASS)
        self.assertIs(self.conclusion(date(2026, 9, 26)), PassageStatus.DENY)

    def test_decision_requires_basis(self):
        insurance = helpers.item_of(self.store, ATHLETE.person_id, Material.INSURANCE)
        with self.assertRaises(DomainError):
            review_item(self.store, insurance.item_id, True, "  ", "rev-1", NOW)


class RenewalTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        helpers.approve_all(self.store, ATHLETE.person_id)
        self.insurance = helpers.item_of(self.store, ATHLETE.person_id, Material.INSURANCE)
        review_item(self.store, self.insurance.item_id, True, "首保至 9 月 25 日",
                    "rev-1", NOW, valid_until=date(2026, 9, 25))

    def test_renewal_extends_validity_with_basis(self):
        later = date(2026, 9, 26)
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, later),
            PassageStatus.DENY,
        )
        decision = renew_item(self.store, self.insurance.item_id, date(2026, 12, 31),
                              "续保凭证#A123", "rev-1", NOW)
        self.assertIs(decision.kind, DecisionKind.RENEWAL)
        self.assertIn("A123", decision.basis)
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, later),
            PassageStatus.PASS,
        )


class AppealTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        helpers.approve_all(self.store, ATHLETE.person_id)
        self.identity = helpers.item_of(self.store, ATHLETE.person_id, Material.IDENTITY)
        review_item(self.store, self.identity.item_id, False, "证件照片不清晰", "rev-1", NOW)

    def test_appeal_overturns_rejection(self):
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, TODAY),
            PassageStatus.DENY,
        )
        appeal_item(self.store, self.identity.item_id, True,
                    "申诉补充高清扫描件后成立", "rev-2", NOW)
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, TODAY),
            PassageStatus.PASS,
        )
        kinds = [
            d.kind for d in self.store.decisions.values()
            if d.item_id == self.identity.item_id
        ]
        self.assertEqual(kinds[-2:], [DecisionKind.REVIEW, DecisionKind.APPEAL])


class MedicalExemptionTest(unittest.TestCase):
    def setUp(self):
        self.store = helpers.make_store()
        submit_roster(self.store, EVENT_ID, TEAM_ID, [ATHLETE], NOW)
        helpers.approve_all(self.store, ATHLETE.person_id)
        self.anti_doping = helpers.item_of(
            self.store, ATHLETE.person_id, Material.ANTI_DOPING
        )

    def test_exemption_waives_only_within_validity(self):
        grant_medical_exemption(self.store, self.anti_doping.item_id,
                                date(2026, 9, 30), "临时医疗豁免,附队医证明",
                                "medical-officer", NOW)
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, date(2026, 9, 29)),
            PassageStatus.PASS,
        )
        # 豁免到期后自动回到待核,比赛日不再放行
        self.assertIs(
            passage_conclusion(self.store, ATHLETE.person_id, EVENT_ID, date(2026, 10, 1)),
            PassageStatus.DENY,
        )


if __name__ == "__main__":
    unittest.main()
