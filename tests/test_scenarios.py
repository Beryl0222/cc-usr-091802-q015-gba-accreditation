"""端到端领域场景测试：覆盖跨城参赛的全部关键约定。"""

import unittest
from datetime import timedelta

from accreditation import (
    ANTI_DOPING,
    GUARDIAN_CONSENT,
    ID_DOCUMENT,
    INSURANCE,
    OfflineGate,
    RECEIPT_GRACE,
    decode_pass_token,
    format_ts,
    is_minor,
    parse_ts,
)
from demo import (
    AGENCY_ID_ANTIDOPING,
    AGENCY_ID_GD,
    AGENCY_ID_GUARDIAN,
    AGENCY_ID_HK_ID,
    AGENCY_ID_INSURER,
    DELEGATION_HK,
    EVENT_ID,
    build_demo_store,
    publish_initial_rules,
)

T0 = "2026-09-18T08:00:00Z"
T1 = "2026-09-19T08:00:00Z"  # 比赛日
T2 = "2026-09-21T08:00:00Z"  # 赛后


class Clock:
    """可拨动的时钟。"""

    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)
        return self.t


def make_world():
    clock = Clock(parse_ts(T0))
    store = build_demo_store(clock=clock.now)
    publish_initial_rules(store, T0)
    return store, clock


def p(store, pid):
    return next(x for x in store.principals.values() if x.principal_id == pid)


def submit_member(store, clock, member, *, expired=(), rejected=(), skip=()):
    """上传一个队员的材料并由各机构核验。"""
    mid = member["member_id"]
    soon = format_ts(clock.t + timedelta(days=30))
    expired_at = format_ts(clock.t - timedelta(days=1))
    specs = [
        (ID_DOCUMENT, AGENCY_ID_GD, "p-reviewer-gd"),
        (INSURANCE, AGENCY_ID_INSURER, "p-reviewer-insurer"),
        (ANTI_DOPING, AGENCY_ID_ANTIDOPING, "p-reviewer-ad"),
    ]
    if is_minor(member["date_of_birth"], clock.t):
        specs.append((GUARDIAN_CONSENT, AGENCY_ID_GUARDIAN, "p-reviewer-guardian"))
    for code, agency, reviewer in specs:
        if member["role"] == "staff" and code == ANTI_DOPING:
            continue
        if code in skip:
            continue
        if code in rejected:
            store.upload_document(mid, code, f"dig-{mid}-{code}", "p-manager-hk")
            store.verify_document(p(store, reviewer), mid, code, False)
            continue
        exp = expired_at if code in expired else (soon if code == ID_DOCUMENT else None)
        store.upload_document(mid, code, f"dig-{mid}-{code}",
                              "p-manager-hk", expires_at=exp)
        store.verify_document(p(store, reviewer), mid, code, True)


ATHLETE_MINOR = {"member_id": "m-chan", "name": "陳小文", "role": "athlete",
                 "date_of_birth": "2009-05-01"}
ATHLETE_ADULT = {"member_id": "m-wong", "name": "黃大文", "role": "athlete",
                 "date_of_birth": "2000-01-01"}
COACH = {"member_id": "m-coach", "name": "李教練", "role": "coach",
         "date_of_birth": "1985-03-03"}
STAFF = {"member_id": "m-staff", "name": "職員強", "role": "staff",
         "date_of_birth": "1990-07-07"}


def roster_hk(store, *members, note="", clock=None):
    return store.submit_roster(
        DELEGATION_HK, list(members), "p-manager-hk", note=note,
        effective_from=format_ts(clock.t) if clock else None)


class RuleAndRosterTests(unittest.TestCase):
    def test_requirements_follow_identity_and_role(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_MINOR, ATHLETE_ADULT, COACH, STAFF, clock=clock)
        codes = {}
        for m in (ATHLETE_MINOR, ATHLETE_ADULT, COACH, STAFF):
            res = store.evaluate(m["member_id"], EVENT_ID, clock.t)
            codes[m["member_id"]] = {i["code"] for i in res["items"]}
        self.assertIn(GUARDIAN_CONSENT, codes["m-chan"])
        self.assertNotIn(GUARDIAN_CONSENT, codes["m-wong"])
        self.assertNotIn(GUARDIAN_CONSENT, codes["m-coach"])
        self.assertNotIn(ANTI_DOPING, codes["m-staff"])
        res = store.evaluate("m-chan", EVENT_ID, clock.t)
        self.assertTrue(all(i["status"] == "missing" for i in res["items"]))
        self.assertEqual(res["status"], "pending")

    def test_rule_versions_have_effective_windows_and_dont_retroact(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, clock=clock)
        submit_member(store, clock, ATHLETE_ADULT)
        clock.advance(days=1)
        pas = store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID)
        # 赛后发布更严格的新规，不影响已产生的凭证（其载荷冻结签发时的版本）。
        clock.t = parse_ts(T2)
        store.publish_rule_set(
            "Guangdong",
            requirements=[
                {"code": ID_DOCUMENT}, {"code": INSURANCE},
                {"code": ANTI_DOPING, "roles": ["athlete", "coach"]},
            ],
            effective_from=T2, actor="p-organizer",
        )
        payload, trusted = decode_pass_token(pas.token, "demo-shared-secret")
        self.assertTrue(trusted)
        self.assertEqual(payload["rule_set_id"], pas.rule_set_id)
        self.assertEqual(store.active_rule_set("Guangdong", clock.t).version, 2)

    def test_new_rule_version_closes_previous_open_window(self):
        store, clock = make_world()
        store.publish_rule_set(
            "Guangdong", requirements=[{"code": ID_DOCUMENT}],
            effective_from=T2, actor="p-organizer")
        v1 = store.active_rule_set("Guangdong", parse_ts(T1))
        v2 = store.active_rule_set("Guangdong", parse_ts(T2))
        self.assertEqual(v1.version, 1)
        self.assertEqual(v2.version, 2)
        self.assertIsNotNone(v1.effective_until)


class VerificationAndVisibilityTests(unittest.TestCase):
    def test_original_documents_only_for_authorized_agency_reviewer(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, clock=clock)
        store.upload_document("m-wong", ID_DOCUMENT, "secret-digest",
                              "p-manager-hk",
                              expires_at=format_ts(clock.t + timedelta(days=9)))
        body = store.document_body(p(store, "p-reviewer-gd"), "m-wong", ID_DOCUMENT)
        self.assertEqual(body["body_digest"], "secret-digest")
        with self.assertRaises(Exception):
            store.document_body(p(store, "p-reviewer-insurer"), "m-wong", ID_DOCUMENT)
        with self.assertRaises(Exception):
            store.document_body(p(store, "p-venue"), "m-wong", ID_DOCUMENT)
        with self.assertRaises(Exception):
            store.document_body(p(store, "p-organizer"), "m-wong", ID_DOCUMENT)

    def test_venue_validation_exposes_only_conclusion(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, clock=clock)
        submit_member(store, clock, ATHLETE_ADULT)
        pas = store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID)
        verdict = store.validate_pass(pas.token, clock.t)
        self.assertEqual(verdict["verdict"], "GREEN")
        self.assertNotIn("date_of_birth", verdict)
        self.assertNotIn("body_digest", verdict)
        self.assertEqual(verdict["name"], "黃大文")

    def test_expired_document_blocks_then_refresh_restores(self):
        """事故场景：开赛前暴露证件过期；续证后恢复，且决定留痕 supersedes。"""
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, clock=clock)
        submit_member(store, clock, ATHLETE_ADULT, expired={ID_DOCUMENT})
        res = store.evaluate("m-wong", EVENT_ID, clock.t)
        self.assertEqual(
            next(i for i in res["items"] if i["code"] == ID_DOCUMENT)["status"],
            "expired")
        self.assertEqual(res["status"], "pending")
        with self.assertRaises(Exception):
            store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID)
        store.upload_document("m-wong", ID_DOCUMENT, "dig-new", "p-manager-hk",
                              expires_at=format_ts(clock.t + timedelta(days=30)))
        _, decision = store.verify_document(
            p(store, "p-reviewer-gd"), "m-wong", ID_DOCUMENT, True)
        self.assertTrue(decision.supersedes)
        self.assertEqual(store.evaluate("m-wong", EVENT_ID, clock.t)["status"],
                         "eligible")


class ConflictTests(unittest.TestCase):
    def _conflicted(self, clock=None):
        store, c = make_world()
        roster_hk(store, ATHLETE_ADULT, COACH, clock=clock or c, note="两名港队成员")
        submit_member(store, clock or c, ATHLETE_ADULT)
        submit_member(store, clock or c, COACH)
        pas = store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID)
        # 港方对同一证件给出相反结论。
        store.verify_document(p(store, "p-reviewer-hk"), "m-wong",
                              ID_DOCUMENT, False, note="港方签注存疑")
        return store, clock or c, pas

    def test_conflict_suspends_only_the_individual(self):
        store, clock, pas = self._conflicted()
        wong = store.evaluate("m-wong", EVENT_ID, clock.t)
        coach = store.evaluate("m-coach", EVENT_ID, clock.t)
        self.assertEqual(wong["status"], "suspended")
        self.assertIsNotNone(wong["hold_decision_id"])
        # 同队教练不受牵连。
        self.assertEqual(coach["status"], "eligible")
        # 冲突个人已发凭证被作废，在线校验即时拒绝。
        self.assertTrue(store.passes[pas.pass_id].revoked)
        self.assertEqual(store.validate_pass(pas.token, clock.t)["verdict"], "DENY")

    def test_only_designated_resolver_can_lift_hold(self):
        store, clock, _ = self._conflicted()
        with self.assertRaises(Exception):
            store.resolve_conflict(p(store, "p-organizer"), "m-wong",
                                   "uphold_approved", "越权")
        d = store.resolve_conflict(
            p(store, "p-resolver"), "m-wong", "uphold_approved",
            "复核确认粤方签注有效，港方为误判")
        res = store.evaluate("m-wong", EVENT_ID, clock.t)
        self.assertEqual(res["status"], "eligible")
        id_item = next(i for i in res["items"] if i["code"] == ID_DOCUMENT)
        self.assertEqual(id_item.get("resolution_id"), d.decision_id)
        self.assertIsNone(store._active_suspension("m-wong"))

    def test_resolution_uphold_rejected_keeps_ineligible(self):
        store, clock, _ = self._conflicted()
        store.resolve_conflict(p(store, "p-resolver"), "m-wong",
                               "uphold_rejected", "复核维持不予通行")
        self.assertEqual(store.evaluate("m-wong", EVENT_ID, clock.t)["status"],
                         "ineligible")


class ExceptionDecisionTests(unittest.TestCase):
    def test_appeal_granted_is_a_basis_backed_decision(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, clock=clock)
        submit_member(store, clock, ATHLETE_ADULT, rejected={INSURANCE})
        self.assertEqual(store.evaluate("m-wong", EVENT_ID, clock.t)["status"],
                         "ineligible")
        until = format_ts(clock.t + timedelta(days=1))
        store.decide_appeal(p(store, "p-appeal"), "m-wong", INSURANCE, True,
                            "保险处于理赔切换期，承保联盟已出具覆盖承诺函",
                            valid_until=until, evidence_digest="ev-letter-1")
        res = store.evaluate("m-wong", EVENT_ID, clock.t)
        item = next(i for i in res["items"] if i["code"] == INSURANCE)
        self.assertEqual(item["status"], "appeal_upheld")
        self.assertEqual(res["status"], "eligible")

    def test_medical_exemption_then_expires(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_MINOR, clock=clock)
        # 治疗用药豁免（TUE）：该项不走常规反兴奋剂声明，由医疗官临时批准。
        submit_member(store, clock, ATHLETE_MINOR, skip={ANTI_DOPING})
        before = store.evaluate("m-chan", EVENT_ID, clock.t)
        self.assertEqual(
            next(i for i in before["items"] if i["code"] == ANTI_DOPING)["status"],
            "missing")
        store.grant_medical_exemption(
            p(store, "p-medical"), "m-chan", ANTI_DOPING,
            format_ts(clock.t + timedelta(hours=12)),
            "急救用药临时豁免，附治疗用药豁免证明", "ev-tue-1")
        res = store.evaluate("m-chan", EVENT_ID, clock.t)
        self.assertEqual(
            next(i for i in res["items"] if i["code"] == ANTI_DOPING)["status"],
            "exempted")
        self.assertEqual(res["status"], "eligible")
        clock.advance(hours=13)
        after = store.evaluate("m-chan", EVENT_ID, clock.t)
        self.assertNotEqual(after["status"], "eligible")


class DashboardTests(unittest.TestCase):
    def test_dashboard_orders_by_urgency(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_MINOR, ATHLETE_ADULT, COACH, STAFF, clock=clock)
        # 成年运动员：证件过期（最紧迫之一）；未成年：缺多件。
        submit_member(store, clock, ATHLETE_ADULT, expired={ID_DOCUMENT})
        submit_member(store, clock, COACH)
        dash = store.urgency_dashboard(EVENT_ID, clock.t)
        states = [row["state"] for row in dash["items"]]
        self.assertIn("expired", states)
        self.assertIn("missing", states)
        # conflict/rejected/expired 排在 missing 之前；同状态按截止时间。
        weights = {"conflict": 0, "expired": 1, "rejected": 2, "missing": 3,
                   "in_review": 4, "expiring_during_event": 5}
        ordered = [weights[s] for s in states]
        self.assertEqual(ordered, sorted(ordered))
        wong_rows = [r for r in dash["items"] if r["member_id"] == "m-wong"]
        self.assertEqual(wong_rows[0]["state"], "expired")
        self.assertLess(wong_rows[0]["hours_to_deadline"], 0)


class RosterSubstitutionTests(unittest.TestCase):
    def test_substitution_keeps_personnel_history_and_drops_off_roster(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, COACH, clock=clock, note="第一版")
        submit_member(store, clock, ATHLETE_ADULT)
        # 换人：成年运动员下、未成年运动员上。
        roster_hk(store, ATHLETE_MINOR, COACH, clock=clock, note="受伤换人")
        self.assertEqual(
            store.evaluate("m-wong", EVENT_ID, clock.t)["status"], "off_roster")
        versions = store.rosters[DELEGATION_HK]
        self.assertEqual([v.sequence for v in versions], [1, 2])
        # 被换下者不能再发证。
        with self.assertRaises(Exception):
            store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID)


class OfflineGateTests(unittest.TestCase):
    def _green_world(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, clock=clock)
        submit_member(store, clock, ATHLETE_ADULT)
        pas = store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID,
                               ttl=timedelta(days=3))
        device = store.devices["dev-gate-1"]
        gate = OfflineGate(device, "demo-shared-secret")
        return store, clock, pas, gate

    def test_offline_scan_validates_signature_and_queues_receipt(self):
        store, clock, pas, gate = self._green_world()
        result = gate.scan(pas.token, clock.t)
        self.assertEqual(result["verdict"], "GREEN")
        # 断网期间不联系服务器；恢复后上传一次。
        up = store.upload_receipt(gate.queued_uploads()[0], clock.t)
        self.assertFalse(up["deduplicated"])
        entries = store.all_entries()
        self.assertEqual(len(entries), 1)

    def test_repeated_uploads_count_as_one_entry(self):
        store, clock, pas, gate = self._green_world()
        gate.scan(pas.token, clock.t)
        envelope = gate.queued_uploads()[0]
        first = store.upload_receipt(envelope, clock.t)
        second = store.upload_receipt(envelope, clock.t)
        third = store.upload_receipt(envelope, clock.t)
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"])
        self.assertTrue(third["deduplicated"])
        self.assertEqual(len(store.all_entries()), 1)
        entry = store.all_entries()[0]
        self.assertEqual(entry.duplicate_uploads, 2)

    def test_tampered_and_expired_tokens_denied_offline(self):
        store, clock, pas, gate = self._green_world()
        bad = gate.scan(pas.token + "x", clock.t)
        self.assertEqual(bad["verdict"], "DENY")
        short = store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID,
                                 ttl=timedelta(minutes=20))
        clock.advance(minutes=21)
        expired = gate.scan(short.token, clock.t)
        self.assertEqual(expired["verdict"], "DENY")
        # DENY 回执不能进入入场账。
        for env in gate.queued_uploads():
            with self.assertRaises(Exception):
                store.upload_receipt(env, clock.t)
        self.assertEqual(store.all_entries(), [])

    def test_late_receipt_beyond_grace_rejected(self):
        store, clock, pas, gate = self._green_world()
        gate.scan(pas.token, clock.t)
        env = gate.queued_uploads()[0]
        clock.advance(seconds=RECEIPT_GRACE.total_seconds() + 1)
        with self.assertRaises(Exception):
            store.upload_receipt(env, clock.t)


class EntryTraceTests(unittest.TestCase):
    def test_entry_trace_reconstructs_full_chain(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_MINOR, clock=clock)
        submit_member(store, clock, ATHLETE_MINOR)
        # 对反兴奋剂走申诉通过，使入场记录带上例外决定。
        store.decide_appeal(
            p(store, "p-appeal"), "m-chan", ANTI_DOPING, True,
            "声明签署版本争议，以最新培训确认为准",
            valid_until=format_ts(clock.t + timedelta(days=1)))
        pas = store.issue_pass(p(store, "p-pass"), "m-chan", EVENT_ID)
        device = store.devices["dev-gate-1"]
        gate = OfflineGate(device, "demo-shared-secret")
        gate.scan(pas.token, clock.t)
        up = store.upload_receipt(gate.queued_uploads()[0], clock.t)
        trace = store.entry_trace(up["entry_id"])
        self.assertEqual(trace["rule_set"]["version"], 1)
        self.assertEqual(trace["roster_version"]["sequence"], 1)
        self.assertIn("m-chan", trace["roster_version"]["member_ids"])
        agencies = set(trace["agencies"])
        self.assertIn(AGENCY_ID_GD, agencies)
        self.assertIn(AGENCY_ID_INSURER, agencies)
        self.assertIn(AGENCY_ID_GUARDIAN, agencies)
        self.assertEqual(len(trace["exception_decisions"]), 1)
        self.assertEqual(trace["device_receipt"]["device_id"], "dev-gate-1")
        self.assertTrue(trace["device_receipt"]["sig"])

    def test_entry_is_immutable_against_later_rule_and_roster_changes(self):
        store, clock = make_world()
        roster_hk(store, ATHLETE_ADULT, clock=clock)
        submit_member(store, clock, ATHLETE_ADULT)
        pas = store.issue_pass(p(store, "p-pass"), "m-wong", EVENT_ID,
                               ttl=timedelta(days=3))
        gate = OfflineGate(store.devices["dev-gate-1"], "demo-shared-secret")
        scan_at = parse_ts(T1)
        gate.scan(pas.token, scan_at)
        up = store.upload_receipt(gate.queued_uploads()[0], scan_at)
        # 赛后：换人且发布新规；既有入场记录的快照不变。
        clock.t = parse_ts(T2)
        roster_hk(store, COACH, clock=clock, note="赛后名单调整")
        store.publish_rule_set(
            "Guangdong", requirements=[{"code": ID_DOCUMENT}],
            effective_from=T2, actor="p-organizer")
        trace = store.entry_trace(up["entry_id"])
        self.assertEqual(trace["roster_version"]["sequence"], 1)
        self.assertIn("m-wong", trace["roster_version"]["member_ids"])
        self.assertEqual(trace["rule_set"]["version"], 1)


if __name__ == "__main__":
    unittest.main()
