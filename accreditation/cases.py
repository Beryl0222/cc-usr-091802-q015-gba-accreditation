"""名单提交、换人与待核项目生成。"""

from __future__ import annotations

from datetime import datetime

from .common import new_id, require_basis
from .errors import UnknownEntityError
from .models import Case, Decision, DecisionKind, Event, Person, Roster, VerificationItem
from .rules import applicable_rules
from .store import Store


def get_event(store: Store, event_id: str) -> Event:
    event = store.events.get(event_id)
    if event is None:
        raise UnknownEntityError(f"未知赛事:{event_id}")
    return event


def submit_roster(
    store: Store,
    event_id: str,
    team_id: str,
    members,
    now: datetime,
    basis: str = "",
    decided_by: str = "",
) -> Roster:
    """代表队提交名单,产生新的名单版本并为成员生成待核项目。

    名单反复换人时版本递增;人员变动会形成带依据的换人决定。
    """
    event = get_event(store, event_id)
    key = (event_id, team_id)
    version = store.current_roster.get(key, 0) + 1
    members = tuple(members)
    for person in members:
        store.persons[person.person_id] = person
    roster = Roster(
        roster_id=f"{event_id}:{team_id}:v{version}",
        event_id=event_id,
        team_id=team_id,
        version=version,
        member_ids=tuple(p.person_id for p in members),
        submitted_at=now,
        basis=basis,
    )
    store.rosters[(event_id, team_id, version)] = roster
    store.current_roster[key] = version
    for person in members:
        ensure_case(store, event, team_id, person)
    if version > 1:
        previous = store.rosters[(event_id, team_id, version - 1)]
        removed = [pid for pid in previous.member_ids if pid not in roster.member_ids]
        added = [pid for pid in roster.member_ids if pid not in previous.member_ids]
        if removed or added:
            _record_substitution(
                store, event_id, team_id, removed, added, basis, decided_by, now
            )
    return roster


def _record_substitution(store, event_id, team_id, removed, added, basis, decided_by, now):
    detail = f"换下:{','.join(removed) or '无'};换上:{','.join(added) or '无'}"
    decision = Decision(
        decision_id=new_id(),
        kind=DecisionKind.SUBSTITUTION,
        outcome="roster_updated",
        basis=f"{require_basis(basis)}({detail})",
        decided_by=decided_by,
        decided_at=now,
        event_id=event_id,
        team_id=team_id,
    )
    store.decisions[decision.decision_id] = decision


def ensure_case(store: Store, event: Event, team_id: str, person: Person) -> Case:
    """为人员建立资格个案,并按身份与职责补齐待核项目(幂等)。"""
    key = (event.event_id, person.person_id)
    case_id = store.case_by_person.get(key)
    case = store.cases.get(case_id) if case_id else None
    if case is None:
        case = Case(
            case_id=new_id(),
            event_id=event.event_id,
            team_id=team_id,
            person_id=person.person_id,
        )
        store.cases[case.case_id] = case
        store.case_by_person[key] = case.case_id
    case.team_id = team_id
    existing = {item.material for item in case.items}
    for rule in applicable_rules(store, event, person):
        if rule.material in existing:
            continue
        item = VerificationItem(
            item_id=new_id(),
            case_id=case.case_id,
            material=rule.material,
            agency=rule.agency,
            rule_id=rule.rule_id,
        )
        case.items.append(item)
        store.items[item.item_id] = item
    return case


def refresh_event_cases(store: Store, event_id: str) -> None:
    """规则发布后,重算该赛事所有在册人员的待核项目。"""
    event = get_event(store, event_id)
    for (ev, team_id), version in list(store.current_roster.items()):
        if ev != event_id:
            continue
        roster = store.rosters[(ev, team_id, version)]
        for person_id in roster.member_ids:
            ensure_case(store, event, team_id, store.persons[person_id])


def current_roster_of(store: Store, event_id: str, person_id: str):
    """返回人员当前所在的名单版本,不在任何在册名单上则返回 None。"""
    for (ev, team_id), version in store.current_roster.items():
        if ev != event_id:
            continue
        roster = store.rosters[(ev, team_id, version)]
        if person_id in roster.member_ids:
            return roster
    return None
