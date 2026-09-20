"""演示场景装配：构造一场粤港澳跨城赛事所需的机构、账号与初始名单。

仅用于本地体验与测试，全部为虚构资料；令牌写在这里是为了 README 可复现，
生产环境应由各机构分别下发。
"""

from __future__ import annotations

from datetime import timedelta

from accreditation import (
    AccreditationStore,
    ANTI_DOPING,
    GUARDIAN_CONSENT,
    ID_DOCUMENT,
    INSURANCE,
    format_ts,
    utc_now,
)

EVENT_ID = "evt-baycup-2026"
ZONE = "Guangdong"
DELEGATION_HK = "del-hk"
DELEGATION_GD = "del-gd"

AGENCY_ID_GD = "ag-gd-entry"
AGENCY_ID_HK_ID = "ag-hk-immigration"
AGENCY_ID_INSURER = "ag-insurer"
AGENCY_ID_ANTIDOPING = "ag-anti-doping"
AGENCY_ID_GUARDIAN = "ag-guardian"

TOKENS = {
    "organizer": "tok-organizer",
    "reviewer_gd": "tok-reviewer-gd",
    "reviewer_hk": "tok-reviewer-hk",
    "insurer": "tok-reviewer-insurer",
    "anti_doping": "tok-reviewer-ad",
    "guardian": "tok-reviewer-guardian",
    "appeal": "tok-appeal",
    "medical": "tok-medical",
    "resolver": "tok-resolver",
    "pass": "tok-pass",
    "manager_hk": "tok-manager-hk",
    "gate": "tok-gate",
    "venue": "tok-venue",
}


def build_demo_store(clock=None) -> AccreditationStore:
    store = AccreditationStore(secret="demo-shared-secret", clock=clock or utc_now)

    # 机构：证件可由两地分别查验（这正是“两地结论冲突”的来源），
    # 保险、反兴奋剂、监护同意各自由专门机构负责。
    store.register_agency(AGENCY_ID_GD, "粤方入出境核验", "Guangdong", {ID_DOCUMENT})
    store.register_agency(AGENCY_ID_HK_ID, "港方证件查验", "Hong Kong", {ID_DOCUMENT})
    store.register_agency(AGENCY_ID_INSURER, "赛事保险承保联盟", "Guangdong", {INSURANCE})
    store.register_agency(AGENCY_ID_ANTIDOPING, "反兴奋剂机构", "Hong Kong", {ANTI_DOPING})
    store.register_agency(AGENCY_ID_GUARDIAN, "未成年人监护审核", "Macao", {GUARDIAN_CONSENT})

    store.register_delegation(DELEGATION_GD, "广州代表队", "Guangdong")
    store.register_delegation(DELEGATION_HK, "香港代表队", "Hong Kong")

    def add(pid, roles, token, agency_id=None, delegation_id=None):
        store.add_principal(pid, roles.split(","), agency_id, delegation_id, token)

    add("p-organizer", "organizer", TOKENS["organizer"])
    add("p-reviewer-gd", "reviewer", TOKENS["reviewer_gd"], AGENCY_ID_GD)
    add("p-reviewer-hk", "reviewer", TOKENS["reviewer_hk"], AGENCY_ID_HK_ID)
    add("p-reviewer-insurer", "reviewer", TOKENS["insurer"], AGENCY_ID_INSURER)
    add("p-reviewer-ad", "reviewer", TOKENS["anti_doping"], AGENCY_ID_ANTIDOPING)
    add("p-reviewer-guardian", "reviewer", TOKENS["guardian"], AGENCY_ID_GUARDIAN)
    add("p-appeal", "appeal_officer", TOKENS["appeal"])
    add("p-medical", "medical_officer", TOKENS["medical"])
    add("p-resolver", "conflict_resolver", TOKENS["resolver"])
    add("p-pass", "pass_officer", TOKENS["pass"])
    add("p-manager-hk", "delegation_manager", TOKENS["manager_hk"], None, DELEGATION_HK)
    add("p-gate", "gate_operator", TOKENS["gate"])
    add("p-venue", "venue_staff", TOKENS["venue"])

    now = store._now()  # noqa: SLF001 - 演示装配与时钟同源
    store.create_event(
        EVENT_ID, "湾区杯城市邀请赛", ZONE,
        format_ts(now.replace(microsecond=0)),
        format_ts(now.replace(microsecond=0) + timedelta(days=2)),
        ["venue-arena-a", "venue-training-b"],
    )

    store.register_device("dev-gate-1", "venue-arena-a", ZONE, "demo-device-secret")
    return store


def publish_initial_rules(store: AccreditationStore, effective_from: str) -> str:
    rs = store.publish_rule_set(
        ZONE,
        requirements=[
            {"code": ID_DOCUMENT, "roles": ["athlete", "coach", "staff"]},
            {"code": INSURANCE, "roles": ["athlete", "coach", "staff"]},
            {"code": ANTI_DOPING, "roles": ["athlete", "coach"]},
            {"code": GUARDIAN_CONSENT, "roles": ["athlete"]},  # minor_only 默认
        ],
        effective_from=effective_from,
        actor="p-organizer",
    )
    return rs.rule_set_id
