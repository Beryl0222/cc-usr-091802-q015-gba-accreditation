"""断网闸机的短期签名凭证与通行回执。

凭证由平台用 HMAC 签名,闸机离线即可验签与核对有效期;
恢复联网后设备回执上传,重复上传仍只算一次通行。
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from .cases import current_roster_of
from .clearance import passage_conclusion
from .common import new_id
from .errors import NotEligibleError
from .models import Credential, EntryRecord, GateReceipt, PassageStatus
from .store import Store

DEFAULT_OFFLINE_TTL_MINUTES = 30  # 与 fixtures/sample.json 的 offline_ttl_minutes 对齐


def _sign(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _payload_of(credential: Credential) -> str:
    return "|".join(
        [
            credential.credential_id,
            credential.person_id,
            credential.event_id,
            credential.team_id,
            str(credential.roster_version),
            credential.issued_at.isoformat(),
            credential.expires_at.isoformat(),
        ]
    )


def issue_credential(
    store: Store,
    person_id: str,
    event_id: str,
    now: datetime,
    key: bytes,
    ttl_minutes: int = DEFAULT_OFFLINE_TTL_MINUTES,
) -> Credential:
    """为当前可通行人员签发短期签名凭证。"""
    status = passage_conclusion(store, person_id, event_id, now.date())
    if status is not PassageStatus.PASS:
        raise NotEligibleError(f"当前结论为 {status.value},不能签发凭证")
    roster = current_roster_of(store, event_id, person_id)
    expires_at = now + timedelta(minutes=ttl_minutes)
    credential = Credential(
        credential_id=new_id(),
        person_id=person_id,
        event_id=event_id,
        team_id=roster.team_id,
        roster_version=roster.version,
        issued_at=now,
        expires_at=expires_at,
        signature="",
    )
    credential = replace(credential, signature=_sign(key, _payload_of(credential)))
    store.credentials[credential.credential_id] = credential
    return credential


def verify_credential(credential: Credential, key: bytes, now: datetime) -> bool:
    """闸机离线校验:签名一致且在有效期内。"""
    expected = _sign(key, _payload_of(credential))
    return hmac.compare_digest(expected, credential.signature) and now <= credential.expires_at


def gate_scan(
    credential: Credential,
    key: bytes,
    device_id: str,
    now: datetime,
    receipt_id: str | None = None,
) -> GateReceipt:
    """闸机离线扫码,落成本地回执。"""
    admitted = verify_credential(credential, key, now)
    return GateReceipt(
        receipt_id=receipt_id or new_id(),
        credential_id=credential.credential_id,
        person_id=credential.person_id,
        event_id=credential.event_id,
        device_id=device_id,
        passed_at=now,
        decision="admitted" if admitted else "denied",
    )


@dataclass
class IngestResult:
    entries: list = field(default_factory=list)
    duplicates: int = 0
    rejected: int = 0


def ingest_receipts(store: Store, receipts, key: bytes | None = None) -> IngestResult:
    """恢复联网后接收回执;同一回执重复上传只算一次通行。"""
    result = IngestResult()
    for receipt in receipts:
        if receipt.receipt_id in store.receipts:
            result.duplicates += 1
            continue
        store.receipts[receipt.receipt_id] = receipt
        entry = _entry_from_receipt(store, receipt, key)
        if entry is None:
            result.rejected += 1
            continue
        store.entries[entry.entry_id] = entry
        result.entries.append(entry)
    return result


def _entry_from_receipt(store: Store, receipt: GateReceipt, key: bytes | None):
    if receipt.decision != "admitted":
        return None
    credential = store.credentials.get(receipt.credential_id)
    if credential is None:
        return None
    if receipt.passed_at > credential.expires_at:
        return None
    if key is not None:
        expected = _sign(key, _payload_of(credential))
        if not hmac.compare_digest(expected, credential.signature):
            return None
    case_id = store.case_by_person.get((receipt.event_id, receipt.person_id))
    if case_id is None:
        return None
    case = store.cases[case_id]
    return EntryRecord(
        entry_id=new_id(),
        receipt_id=receipt.receipt_id,
        person_id=receipt.person_id,
        event_id=receipt.event_id,
        team_id=credential.team_id,
        roster_version=credential.roster_version,
        case_id=case.case_id,
        conclusion=PassageStatus.PASS,
        rule_snapshot={item.material.value: item.rule_id for item in case.items},
        entered_at=receipt.passed_at,
        device_id=receipt.device_id,
    )
