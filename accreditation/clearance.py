"""通行结论与两地冲突复核。"""

from __future__ import annotations

from datetime import date, datetime

from .cases import current_roster_of, get_event
from .common import new_id, require_basis
from .decisions import is_satisfied
from .errors import UnknownEntityError
from .models import (
    Decision,
    DecisionKind,
    PassageStatus,
    RegionClearance,
    ReviewTask,
)
from .store import Store


def passage_conclusion(store: Store, person_id: str, event_id: str, on: date) -> PassageStatus:
    """汇聚当前名单、核验决定与冲突状态后的通行结论。"""
    key = (person_id, event_id)
    if store.conflict_overrides.get(key) is PassageStatus.DENY:
        return PassageStatus.DENY
    if key in store.suspensions:
        return PassageStatus.SUSPENDED
    if current_roster_of(store, event_id, person_id) is None:
        return PassageStatus.DENY  # 已被换下或从未报名
    case_id = store.case_by_person.get((event_id, person_id))
    if case_id is None:
        return PassageStatus.DENY
    case = store.cases[case_id]
    if all(is_satisfied(store, item, on) for item in case.items):
        return PassageStatus.PASS
    return PassageStatus.DENY


def record_clearance(
    store: Store,
    person_id: str,
    event_id: str,
    region: str,
    outcome: PassageStatus,
    basis: str,
    now: datetime,
):
    """记录一个地区对个人的结论。

    两地结论冲突时,只暂停相关个人并派单给赛事指定复核人员,
    不扩大到全队。返回新建的复核单,无冲突时返回 None。
    """
    get_event(store, event_id)
    store.clearances.append(
        RegionClearance(
            person_id=person_id,
            event_id=event_id,
            region=region,
            outcome=outcome,
            basis=require_basis(basis),
            recorded_at=now,
        )
    )
    latest: dict = {}
    for clearance in store.clearances:
        if clearance.person_id == person_id and clearance.event_id == event_id:
            latest[clearance.region] = clearance.outcome
    outcomes = set(latest.values())
    if PassageStatus.PASS in outcomes and PassageStatus.DENY in outcomes:
        key = (person_id, event_id)
        if key not in store.suspensions:
            store.suspensions.add(key)
            event = get_event(store, event_id)
            task = ReviewTask(
                task_id=new_id(),
                person_id=person_id,
                event_id=event_id,
                reason="两地结论冲突",
                assignee=event.reviewer,
                created_at=now,
            )
            store.review_tasks[task.task_id] = task
            return task
    return None


def resolve_conflict(
    store: Store,
    task_id: str,
    outcome: PassageStatus,
    basis: str,
    decided_by: str,
    now: datetime,
) -> Decision:
    """指定人员复核冲突,形成带依据的新决定并解除暂停。"""
    task = store.review_tasks.get(task_id)
    if task is None:
        raise UnknownEntityError(f"未知复核单:{task_id}")
    decision = Decision(
        decision_id=new_id(),
        kind=DecisionKind.CONFLICT_RESOLUTION,
        outcome=outcome.value,
        basis=require_basis(basis),
        decided_by=decided_by,
        decided_at=now,
        event_id=task.event_id,
        person_id=task.person_id,
    )
    store.decisions[decision.decision_id] = decision
    task.status = "resolved"
    task.resolution_decision_id = decision.decision_id
    key = (task.person_id, task.event_id)
    store.suspensions.discard(key)
    if outcome is PassageStatus.DENY:
        store.conflict_overrides[key] = PassageStatus.DENY
    else:
        store.conflict_overrides.pop(key, None)
    return decision
