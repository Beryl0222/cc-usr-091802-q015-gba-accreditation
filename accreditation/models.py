"""领域模型:名单、材料规则、待核项目、决定与通行记录。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime


class Role(enum.Enum):
    """代表队成员职责。"""

    ATHLETE = "athlete"
    COACH = "coach"
    STAFF = "staff"


class Material(enum.Enum):
    """参赛材料类别,分别由不同机构查验。"""

    IDENTITY = "identity"  # 证件
    INSURANCE = "insurance"  # 保险
    ANTI_DOPING = "anti_doping"  # 反兴奋剂声明
    GUARDIAN_CONSENT = "guardian_consent"  # 未成年监护同意


class ItemStatus(enum.Enum):
    """待核项目在某日期下的核验状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WAIVED = "waived"


class DecisionKind(enum.Enum):
    """带依据的决定类别。"""

    REVIEW = "review"  # 审核岗核验
    SUBSTITUTION = "substitution"  # 换人
    RENEWAL = "renewal"  # 续证
    APPEAL = "appeal"  # 资格申诉
    MEDICAL_EXEMPTION = "medical_exemption"  # 临时医疗豁免
    CONFLICT_RESOLUTION = "conflict_resolution"  # 两地冲突复核


class PassageStatus(enum.Enum):
    """通行结论,是场馆与接驳人员唯一可见的判断。"""

    PASS = "pass"
    DENY = "deny"
    SUSPENDED = "suspended"  # 两地结论冲突,暂停待复核


class ActorRole(enum.Enum):
    """系统使用者角色。"""

    REVIEWER = "reviewer"  # 授权审核岗
    ORGANIZER = "organizer"  # 办赛人员
    VENUE = "venue"  # 场馆人员
    SHUTTLE = "shuttle"  # 接驳人员
    TEAM = "team"  # 代表队工作人员


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: ActorRole


@dataclass(frozen=True)
class MaterialRule:
    """赛区发布的带生效期的材料规则。"""

    rule_id: str
    region: str
    material: Material
    agency: str  # 核验机构
    roles: frozenset
    minors_only: bool
    effective_from: date
    effective_to: date | None  # None 表示长期有效
    version: int

    def effective_on(self, day: date) -> bool:
        return self.effective_from <= day and (
            self.effective_to is None or day <= self.effective_to
        )


@dataclass(frozen=True)
class Person:
    person_id: str
    name: str
    role: Role
    birth_date: date
    home_region: str

    def is_minor_on(self, day: date) -> bool:
        age = day.year - self.birth_date.year - (
            (day.month, day.day) < (self.birth_date.month, self.birth_date.day)
        )
        return age < 18


@dataclass(frozen=True)
class Event:
    event_id: str
    name: str
    host_region: str
    competition_date: date
    reviewer: str  # 两地冲突时的指定复核人员


@dataclass
class Roster:
    """名单的一个不可变版本;换人产生新版本。"""

    roster_id: str
    event_id: str
    team_id: str
    version: int
    member_ids: tuple
    submitted_at: datetime
    basis: str = ""


@dataclass
class Document:
    """材料原件,仅授权审核岗可见。"""

    document_id: str
    material: Material
    content_ref: str
    submitted_by: str
    uploaded_at: datetime


@dataclass
class VerificationItem:
    """按身份与职责产生的待核项目。"""

    item_id: str
    case_id: str
    material: Material
    agency: str
    rule_id: str
    valid_until: date | None = None  # 材料自身有效期,如保险到期日
    documents: list = field(default_factory=list)


@dataclass
class Case:
    """个人在某赛事下的资格个案,跨名单版本延续。"""

    case_id: str
    event_id: str
    team_id: str
    person_id: str
    items: list = field(default_factory=list)


@dataclass
class Decision:
    """带依据的决定:审核、换人、续证、申诉、医疗豁免、冲突复核。"""

    decision_id: str
    kind: DecisionKind
    outcome: str
    basis: str
    decided_by: str
    decided_at: datetime
    event_id: str
    team_id: str | None = None
    case_id: str | None = None
    item_id: str | None = None
    person_id: str | None = None
    valid_until: date | None = None


@dataclass
class RegionClearance:
    """一个地区对个人给出的参赛结论。"""

    person_id: str
    event_id: str
    region: str
    outcome: PassageStatus
    basis: str
    recorded_at: datetime


@dataclass
class ReviewTask:
    """两地结论冲突时派给指定人员的复核单。"""

    task_id: str
    person_id: str
    event_id: str
    reason: str
    assignee: str
    created_at: datetime
    status: str = "open"
    resolution_decision_id: str | None = None


@dataclass(frozen=True)
class Credential:
    """断网闸机可离线识别的短期签名凭证。"""

    credential_id: str
    person_id: str
    event_id: str
    team_id: str
    roster_version: int
    issued_at: datetime
    expires_at: datetime
    signature: str


@dataclass(frozen=True)
class GateReceipt:
    """闸机设备回执,恢复联网后上传。"""

    receipt_id: str
    credential_id: str
    person_id: str
    event_id: str
    device_id: str
    passed_at: datetime
    decision: str  # admitted / denied


@dataclass
class EntryRecord:
    """已发生的入场记录,不随后来规则改变。"""

    entry_id: str
    receipt_id: str
    person_id: str
    event_id: str
    team_id: str
    roster_version: int
    case_id: str
    conclusion: PassageStatus
    rule_snapshot: dict  # 入场时各材料适用的规则版本
    entered_at: datetime
    device_id: str
