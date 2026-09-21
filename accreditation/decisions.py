"""核验决定:审核、续证、资格申诉与临时医疗豁免。"""

from __future__ import annotations

from datetime import date, datetime

from .common import new_id, require_basis
from .errors import UnknownEntityError
from .models import Decision, DecisionKind, Document, ItemStatus, Material, VerificationItem
from .store import Store


def get_item(store: Store, item_id: str) -> VerificationItem:
    item = store.items.get(item_id)
    if item is None:
        raise UnknownEntityError(f"未知待核项目:{item_id}")
    return item


def submit_document(
    store: Store,
    item_id: str,
    material: Material,
    content_ref: str,
    submitted_by: str,
    now: datetime,
) -> Document:
    """代表队提交材料原件;原件的读取受角色限制,见 views.item_documents。"""
    item = get_item(store, item_id)
    document = Document(
        document_id=new_id(),
        material=material,
        content_ref=content_ref,
        submitted_by=submitted_by,
        uploaded_at=now,
    )
    item.documents.append(document)
    return document


def _record(
    store: Store,
    kind: DecisionKind,
    outcome: str,
    basis: str,
    decided_by: str,
    now: datetime,
    item: VerificationItem,
    valid_until: date | None = None,
) -> Decision:
    case = store.cases[item.case_id]
    decision = Decision(
        decision_id=new_id(),
        kind=kind,
        outcome=outcome,
        basis=require_basis(basis),
        decided_by=decided_by,
        decided_at=now,
        event_id=case.event_id,
        team_id=case.team_id,
        case_id=case.case_id,
        item_id=item.item_id,
        person_id=case.person_id,
        valid_until=valid_until,
    )
    store.decisions[decision.decision_id] = decision
    return decision


def review_item(
    store: Store,
    item_id: str,
    approved: bool,
    basis: str,
    decided_by: str,
    now: datetime,
    valid_until: date | None = None,
) -> Decision:
    """审核岗对材料作出核验决定,通过时可登记材料自身有效期。"""
    item = get_item(store, item_id)
    if approved:
        item.valid_until = valid_until
    return _record(
        store,
        DecisionKind.REVIEW,
        "approved" if approved else "rejected",
        basis,
        decided_by,
        now,
        item,
        valid_until=valid_until,
    )


def renew_item(
    store: Store,
    item_id: str,
    valid_until: date,
    basis: str,
    decided_by: str,
    now: datetime,
) -> Decision:
    """续证:以带依据的新决定延长材料有效期。"""
    item = get_item(store, item_id)
    item.valid_until = valid_until
    return _record(
        store,
        DecisionKind.RENEWAL,
        "approved",
        basis,
        decided_by,
        now,
        item,
        valid_until=valid_until,
    )


def appeal_item(
    store: Store,
    item_id: str,
    approved: bool,
    basis: str,
    decided_by: str,
    now: datetime,
) -> Decision:
    """资格申诉:带依据地维持或推翻此前结论。"""
    item = get_item(store, item_id)
    return _record(
        store,
        DecisionKind.APPEAL,
        "approved" if approved else "rejected",
        basis,
        decided_by,
        now,
        item,
    )


def grant_medical_exemption(
    store: Store,
    item_id: str,
    valid_until: date,
    basis: str,
    decided_by: str,
    now: datetime,
) -> Decision:
    """临时医疗豁免:在有效期内豁免该项材料,逾期自动回到待核。"""
    item = get_item(store, item_id)
    return _record(
        store,
        DecisionKind.MEDICAL_EXEMPTION,
        "waived",
        basis,
        decided_by,
        now,
        item,
        valid_until=valid_until,
    )


def latest_decision(store: Store, item_id: str):
    """同一项目上后记录的决定覆盖先记录的。"""
    found = None
    for decision in store.decisions.values():
        if decision.item_id == item_id:
            found = decision
    return found


def item_status(store: Store, item: VerificationItem, on: date) -> ItemStatus:
    decision = latest_decision(store, item.item_id)
    if decision is None:
        return ItemStatus.PENDING
    if decision.kind is DecisionKind.MEDICAL_EXEMPTION and decision.outcome == "waived":
        if decision.valid_until is not None and decision.valid_until >= on:
            return ItemStatus.WAIVED
        return ItemStatus.PENDING  # 豁免期已过,回到待核
    if decision.outcome == "approved":
        return ItemStatus.APPROVED
    return ItemStatus.REJECTED


def item_valid_until(store: Store, item: VerificationItem):
    """项目当前的实际有效期:豁免看豁免决定,其余看材料本身。"""
    decision = latest_decision(store, item.item_id)
    if decision is not None and decision.kind is DecisionKind.MEDICAL_EXEMPTION:
        return decision.valid_until
    return item.valid_until


def is_satisfied(store: Store, item: VerificationItem, on: date) -> bool:
    status = item_status(store, item, on)
    if status is ItemStatus.WAIVED:
        return True
    if status is ItemStatus.APPROVED:
        return item.valid_until is None or item.valid_until >= on
    return False
