"""测试共用的领域搭建工具。"""

from datetime import date, datetime

from accreditation import (
    Event,
    Material,
    MaterialRule,
    Person,
    Role,
    Store,
    publish_rule,
    review_item,
)

KEY = b"gate-signing-key"
COMPETITION = date(2026, 10, 1)
NOW = datetime(2026, 9, 20, 9, 0, 0)
TODAY = NOW.date()

EVENT_ID = "evt-gba"
TEAM_ID = "team-gd"
REVIEWER = "rev-zhou"

ATHLETE = Person("p-athlete", "陈运动员", Role.ATHLETE, date(2000, 1, 1), "Guangdong")
MINOR = Person("p-minor", "李少年", Role.ATHLETE, date(2010, 5, 1), "Guangdong")
COACH = Person("p-coach", "王教练", Role.COACH, date(1980, 3, 1), "Guangdong")
STAFF = Person("p-staff", "赵随队", Role.STAFF, date(1990, 7, 1), "Guangdong")
STAFF2 = Person("p-staff2", "钱随队", Role.STAFF, date(1992, 8, 1), "Guangdong")


def make_event() -> Event:
    return Event(
        event_id=EVENT_ID,
        name="湾区城市对抗赛",
        host_region="HongKong",
        competition_date=COMPETITION,
        reviewer=REVIEWER,
    )


def make_rules() -> list:
    roles_all = frozenset({Role.ATHLETE, Role.COACH, Role.STAFF})
    return [
        MaterialRule(
            "rule-identity", "HongKong", Material.IDENTITY, "证件查验中心",
            roles_all, False, date(2026, 1, 1), None, 1,
        ),
        MaterialRule(
            "rule-insurance", "HongKong", Material.INSURANCE, "保险核验平台",
            roles_all, False, date(2026, 1, 1), None, 1,
        ),
        MaterialRule(
            "rule-anti-doping", "HongKong", Material.ANTI_DOPING, "反兴奋剂中心",
            frozenset({Role.ATHLETE}), False, date(2026, 1, 1), None, 1,
        ),
        MaterialRule(
            "rule-guardian", "HongKong", Material.GUARDIAN_CONSENT, "未成年保护核验处",
            roles_all, True, date(2026, 1, 1), None, 1,
        ),
    ]


def make_store() -> Store:
    store = Store()
    store.events[EVENT_ID] = make_event()
    for rule in make_rules():
        publish_rule(store, rule)
    return store


def case_of(store, person_id):
    return store.cases[store.case_by_person[(EVENT_ID, person_id)]]


def item_of(store, person_id, material):
    for item in case_of(store, person_id).items:
        if item.material is material:
            return item
    raise AssertionError(f"{person_id} 缺少待核项目 {material}")


def materials_of(store, person_id):
    return {item.material for item in case_of(store, person_id).items}


def approve_all(store, person_id, valid_until=None, now=NOW):
    for item in case_of(store, person_id).items:
        review_item(store, item.item_id, True, "原件核验通过", REVIEWER, now,
                    valid_until=valid_until)
