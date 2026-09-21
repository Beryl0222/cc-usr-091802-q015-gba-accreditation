"""赛前看板:按紧迫程度排列的缺件和到期项。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .cases import get_event
from .decisions import item_status, item_valid_until
from .models import ItemStatus
from .store import Store


@dataclass(frozen=True)
class BoardEntry:
    team_id: str
    person_id: str
    material: object
    kind: str  # missing=缺件 / expiring=到期项
    days_remaining: int  # 距影响参赛的天数,越小越紧迫,负数表示已过期
    detail: str


def pre_event_board(store: Store, event_id: str, on: date, team_id: str | None = None) -> list:
    """汇总在册人员的缺件与赛前到期项,按紧迫程度升序排列。"""
    event = get_event(store, event_id)
    entries = []
    for (ev, tid), version in sorted(store.current_roster.items()):
        if ev != event_id or (team_id is not None and tid != team_id):
            continue
        roster = store.rosters[(ev, tid, version)]
        for person_id in roster.member_ids:
            case = store.cases[store.case_by_person[(event_id, person_id)]]
            for item in case.items:
                status = item_status(store, item, on)
                if status in (ItemStatus.PENDING, ItemStatus.REJECTED):
                    entries.append(
                        BoardEntry(
                            team_id=tid,
                            person_id=person_id,
                            material=item.material,
                            kind="missing",
                            days_remaining=(event.competition_date - on).days,
                            detail="材料缺失或未通过核验",
                        )
                    )
                    continue
                valid_until = item_valid_until(store, item)
                if valid_until is not None and valid_until < event.competition_date:
                    entries.append(
                        BoardEntry(
                            team_id=tid,
                            person_id=person_id,
                            material=item.material,
                            kind="expiring",
                            days_remaining=(valid_until - on).days,
                            detail="材料将在赛前到期或已过期",
                        )
                    )
    entries.sort(
        key=lambda e: (
            e.days_remaining,
            0 if e.kind == "expiring" else 1,
            e.team_id,
            e.person_id,
            e.material.value,
        )
    )
    return entries
