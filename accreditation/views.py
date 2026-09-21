"""按角色裁剪的读取视图。

原件仅向授权审核岗开放;场馆和接驳人员只收到足以判断通行的结论。
"""

from __future__ import annotations

from datetime import date

from .clearance import passage_conclusion
from .errors import PermissionDeniedError, UnknownEntityError
from .models import Actor, ActorRole
from .store import Store

PASSAGE_VIEW_KEYS = ("person_id", "name", "event_id", "status", "as_of")


def passage_view(store: Store, person_id: str, event_id: str, on: date) -> dict:
    """足以判断通行的结论,不含材料明细与原件。"""
    person = store.persons.get(person_id)
    if person is None:
        raise UnknownEntityError(f"未知人员:{person_id}")
    status = passage_conclusion(store, person_id, event_id, on)
    return {
        "person_id": person_id,
        "name": person.name,
        "event_id": event_id,
        "status": status.value,
        "as_of": on.isoformat(),
    }


def item_documents(store: Store, item_id: str, actor: Actor) -> list:
    """材料原件仅向授权审核岗开放。"""
    if actor.role is not ActorRole.REVIEWER:
        raise PermissionDeniedError("材料原件仅向授权审核岗开放")
    item = store.items.get(item_id)
    if item is None:
        raise UnknownEntityError(f"未知待核项目:{item_id}")
    return list(item.documents)
