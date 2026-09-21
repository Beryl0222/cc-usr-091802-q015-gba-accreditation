"""湾区参赛资格通行领域核心。

覆盖:带生效期的材料规则、名单版本与换人、按身份职责生成待核项目、
带依据的审核/续证/申诉/医疗豁免决定、两地冲突只暂停个人、
断网闸机短期签名凭证与幂等回执、赛前紧迫看板、赛后入场追溯,
以及按角色裁剪的视图(原件仅授权审核岗可见)。
"""

from .audit import EntryTrace, trace_entry
from .board import BoardEntry, pre_event_board
from .cases import (
    current_roster_of,
    ensure_case,
    refresh_event_cases,
    submit_roster,
)
from .clearance import passage_conclusion, record_clearance, resolve_conflict
from .decisions import (
    appeal_item,
    grant_medical_exemption,
    is_satisfied,
    item_status,
    item_valid_until,
    latest_decision,
    renew_item,
    review_item,
    submit_document,
)
from .errors import (
    DomainError,
    NotEligibleError,
    PermissionDeniedError,
    UnknownEntityError,
)
from .models import (
    Actor,
    ActorRole,
    Case,
    Credential,
    Decision,
    DecisionKind,
    Document,
    EntryRecord,
    Event,
    GateReceipt,
    ItemStatus,
    Material,
    MaterialRule,
    PassageStatus,
    Person,
    RegionClearance,
    ReviewTask,
    Role,
    Roster,
    VerificationItem,
)
from .offline import (
    DEFAULT_OFFLINE_TTL_MINUTES,
    IngestResult,
    gate_scan,
    ingest_receipts,
    issue_credential,
    verify_credential,
)
from .rules import applicable_rules, publish_rule
from .store import Store
from .views import item_documents, passage_view

__all__ = [
    "Actor",
    "ActorRole",
    "BoardEntry",
    "Case",
    "Credential",
    "Decision",
    "DecisionKind",
    "DEFAULT_OFFLINE_TTL_MINUTES",
    "Document",
    "DomainError",
    "EntryRecord",
    "EntryTrace",
    "Event",
    "GateReceipt",
    "IngestResult",
    "ItemStatus",
    "Material",
    "MaterialRule",
    "NotEligibleError",
    "PassageStatus",
    "PermissionDeniedError",
    "Person",
    "RegionClearance",
    "ReviewTask",
    "Role",
    "Roster",
    "Store",
    "UnknownEntityError",
    "VerificationItem",
    "appeal_item",
    "applicable_rules",
    "current_roster_of",
    "ensure_case",
    "gate_scan",
    "grant_medical_exemption",
    "ingest_receipts",
    "is_satisfied",
    "issue_credential",
    "item_documents",
    "item_status",
    "item_valid_until",
    "latest_decision",
    "passage_conclusion",
    "passage_view",
    "pre_event_board",
    "publish_rule",
    "record_clearance",
    "refresh_event_cases",
    "renew_item",
    "resolve_conflict",
    "review_item",
    "submit_document",
    "submit_roster",
    "trace_entry",
    "verify_credential",
]
