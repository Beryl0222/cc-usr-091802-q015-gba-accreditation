"""内存存储:汇聚资格通行服务的全部状态。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    Case,
    Credential,
    Decision,
    EntryRecord,
    Event,
    GateReceipt,
    MaterialRule,
    PassageStatus,
    Person,
    RegionClearance,
    ReviewTask,
    Roster,
    VerificationItem,
)


@dataclass
class Store:
    rules: dict = field(default_factory=dict)  # rule_id -> MaterialRule
    persons: dict = field(default_factory=dict)  # person_id -> Person
    events: dict = field(default_factory=dict)  # event_id -> Event
    rosters: dict = field(default_factory=dict)  # (event_id, team_id, version) -> Roster
    current_roster: dict = field(default_factory=dict)  # (event_id, team_id) -> version
    cases: dict = field(default_factory=dict)  # case_id -> Case
    case_by_person: dict = field(default_factory=dict)  # (event_id, person_id) -> case_id
    items: dict = field(default_factory=dict)  # item_id -> VerificationItem
    decisions: dict = field(default_factory=dict)  # decision_id -> Decision(按记录顺序)
    clearances: list = field(default_factory=list)  # RegionClearance 时序列表
    suspensions: set = field(default_factory=set)  # (person_id, event_id) 冲突暂停
    conflict_overrides: dict = field(default_factory=dict)  # (person_id, event_id) -> PassageStatus
    review_tasks: dict = field(default_factory=dict)  # task_id -> ReviewTask
    credentials: dict = field(default_factory=dict)  # credential_id -> Credential
    receipts: dict = field(default_factory=dict)  # receipt_id -> GateReceipt(幂等键)
    entries: dict = field(default_factory=dict)  # entry_id -> EntryRecord
