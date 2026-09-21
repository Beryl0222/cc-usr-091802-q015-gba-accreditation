"""赛后追溯:从一条入场记录查回名单版本、核验机构、例外决定与设备回执。"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import UnknownEntityError
from .models import DecisionKind
from .store import Store

EXCEPTION_KINDS = (
    DecisionKind.RENEWAL,
    DecisionKind.APPEAL,
    DecisionKind.MEDICAL_EXEMPTION,
    DecisionKind.CONFLICT_RESOLUTION,
)


@dataclass(frozen=True)
class EntryTrace:
    entry: object
    roster: object
    agencies: dict  # 材料 -> 核验机构
    exception_decisions: tuple  # 影响该个案的例外决定,按记录顺序
    receipt: object  # 闸机设备回执


def trace_entry(store: Store, entry_id: str) -> EntryTrace:
    entry = store.entries.get(entry_id)
    if entry is None:
        raise UnknownEntityError(f"未知入场记录:{entry_id}")
    roster = store.rosters[(entry.event_id, entry.team_id, entry.roster_version)]
    case = store.cases[entry.case_id]
    agencies = {item.material.value: item.agency for item in case.items}
    exceptions = tuple(
        decision
        for decision in store.decisions.values()
        if decision.kind in EXCEPTION_KINDS
        and (
            decision.case_id == case.case_id
            or (
                decision.kind is DecisionKind.CONFLICT_RESOLUTION
                and decision.person_id == entry.person_id
                and decision.event_id == entry.event_id
            )
        )
    )
    receipt = store.receipts[entry.receipt_id]
    return EntryTrace(
        entry=entry,
        roster=roster,
        agencies=agencies,
        exception_decisions=exceptions,
        receipt=receipt,
    )
