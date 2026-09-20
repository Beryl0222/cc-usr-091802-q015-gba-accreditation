"""参赛资格与通行领域核心。

设计要点（对应联合办赛的规则约定）：

* 规则带生效期：任何时点的资格评估只使用该时点生效的规则版本，已发生的入场
  保存当时的规则版本快照，不因后来规则改变而重写。
* 名单是不可变版本流：换人产生新版本，队员以稳定 member_id 跨版本保留材料。
* 证件、保险、反兴奋剂声明、未成年监护同意由不同机构分别核验；评估只依赖
  各机构的结论，原件（材料摘 要）仅授权审核岗可取。
* 换人、续证、申诉、临时医疗豁免、两地冲突暂停/复核全部进入带依据的决定台账。
* 两地结论冲突只暂停相关个人，不牵连全队；由指定复核人作出权威结论后解除。
* 通行凭证为短期 HMAC 签名凭证，闸机可离线验签；设备回执幂等，重复上传
  只计一次通行。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# ---- 稳定的领域常量 -------------------------------------------------------

REGIONS = ("Guangdong", "Hong Kong", "Macao")
ROLES = ("athlete", "coach", "staff")

ID_DOCUMENT = "id_document"
INSURANCE = "insurance"
ANTI_DOPING = "anti_doping_declaration"
GUARDIAN_CONSENT = "guardian_consent"

REQ_TITLES = {
    ID_DOCUMENT: "身份证件",
    INSURANCE: "比赛保险",
    ANTI_DOPING: "反兴奋剂声明",
    GUARDIAN_CONSENT: "未成年监护同意",
}

# 凭证默认有效期：断网闸机的离线判定窗口（分钟）。
DEFAULT_PASS_TTL = timedelta(minutes=30)

# 闸机回执延迟上传的宽限：超过扫描时刻过久的回执不再接受。
RECEIPT_GRACE = timedelta(minutes=30)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | datetime) -> datetime:
    """解析 ISO8601 时间，返回带时区的 datetime。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def is_minor(date_of_birth: str, at: datetime) -> bool:
    dob = parse_day(date_of_birth)
    ref = at.astimezone(timezone.utc).date()
    age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    return age < 18


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unb64u(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign(payload: bytes, secret: str) -> str:
    return b64u(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest())


# ---- 基础数据结构 ---------------------------------------------------------


@dataclass(frozen=True)
class Requirement:
    """规则中的一项材料要求。"""

    code: str
    title: str
    roles: frozenset
    minor_only: bool = False

    def applies_to(self, role: str, minor: bool) -> bool:
        return role in self.roles and (not self.minor_only or minor)


@dataclass(frozen=True)
class RuleSet:
    """赛区发布的带生效期材料规则版本。"""

    rule_set_id: str
    zone: str
    version: int
    requirements: tuple[Requirement, ...]
    published_at: datetime
    effective_from: datetime
    effective_until: datetime | None
    actor: str

    def active_at(self, at: datetime) -> bool:
        if at < self.effective_from:
            return False
        return self.effective_until is None or at < self.effective_until

    def public(self) -> dict:
        return {
            "rule_set_id": self.rule_set_id,
            "zone": self.zone,
            "version": self.version,
            "effective_from": format_ts(self.effective_from),
            "effective_until": format_ts(self.effective_until) if self.effective_until else None,
            "requirements": [
                {
                    "code": r.code,
                    "title": r.title,
                    "roles": sorted(r.roles),
                    "minor_only": r.minor_only,
                }
                for r in self.requirements
            ],
        }


@dataclass
class Delegation:
    delegation_id: str
    name: str
    home_region: str


@dataclass
class Member:
    member_id: str
    name: str
    role: str
    date_of_birth: str
    delegation_id: str
    home_region: str


@dataclass(frozen=True)
class RosterVersion:
    """不可变名单版本；换人即追加新版本。"""

    roster_id: str
    delegation_id: str
    sequence: int
    member_ids: tuple[str, ...]
    effective_from: datetime
    created_at: datetime
    actor: str
    note: str

    def public(self) -> dict:
        return {
            "roster_id": self.roster_id,
            "delegation_id": self.delegation_id,
            "sequence": self.sequence,
            "member_ids": list(self.member_ids),
            "effective_from": format_ts(self.effective_from),
            "note": self.note,
        }


@dataclass(frozen=True)
class Submission:
    """队员材料（“原件”），正文只以摘 要形式留痕，正文访问受岗级限制。"""

    submission_id: str
    member_id: str
    req_code: str
    body_digest: str
    issued_at: datetime
    expires_at: datetime | None
    uploaded_at: datetime
    actor: str


@dataclass(frozen=True)
class Verification:
    """核验机构对单项材料给出的结论。"""

    verification_id: str
    member_id: str
    req_code: str
    agency_id: str
    region: str
    approved: bool
    reviewer: str
    at: datetime
    valid_until: datetime | None
    submission_id: str
    note: str

    def valid_approval(self, at: datetime) -> bool:
        return self.approved and (self.valid_until is None or self.valid_until > at)


@dataclass(frozen=True)
class Decision:
    """带依据的决定台账条目。"""

    decision_id: str
    kind: str  # roster_change | verification | appeal | exemption | suspension | resolution
    subject_type: str  # delegation | member
    subject_id: str
    at: datetime
    actor: str
    reason: str
    basis: tuple[dict, ...]
    effect: dict
    supersedes: tuple[str, ...] = ()
    closed_by: str | None = None

    def public(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "kind": self.kind,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "at": format_ts(self.at),
            "actor": self.actor,
            "reason": self.reason,
            "basis": list(self.basis),
            "effect": self.effect,
            "supersedes": list(self.supersedes),
            "closed_by": self.closed_by,
        }


@dataclass(frozen=True)
class Event:
    event_id: str
    title: str
    host_zone: str
    starts_at: datetime
    ends_at: datetime
    venues: tuple[str, ...]


@dataclass(frozen=True)
class Agency:
    agency_id: str
    name: str
    region: str
    req_codes: frozenset


@dataclass(frozen=True)
class Principal:
    principal_id: str
    roles: frozenset
    agency_id: str | None = None
    delegation_id: str | None = None
    token: str | None = None


@dataclass(frozen=True)
class GateDevice:
    device_id: str
    venue: str
    zone: str
    secret: str


@dataclass(frozen=True)
class Pass:
    pass_id: str
    member_id: str
    event_id: str
    zones: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    rule_set_id: str
    roster_id: str
    token: str
    revoked: bool = False
    revoke_reason: str | None = None


@dataclass(frozen=True)
class Entry:
    """一条入场记录；全部以快照形式保存，事后规则/名单变化不改动它。"""

    entry_id: str
    receipt_id: str
    device_id: str
    venue: str
    pass_id: str
    member_id: str
    delegation_id: str
    event_id: str
    scan_at: datetime
    recorded_at: datetime
    rule_set_id: str
    roster_id: str
    verdict: str
    checks: tuple[dict, ...]
    exception_decisions: tuple[str, ...]
    receipt_sig: str
    duplicate_uploads: int = 0


class DomainError(Exception):
    """所有可预期的业务拒绝，HTTP 层映射为 4xx。"""


# ---- 凭证编解码 -----------------------------------------------------------


def encode_pass_token(payload: dict, secret: str) -> str:
    body = b64u(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return f"{body}.{sign(body.encode('ascii'), secret)}"


def decode_pass_token(token: str, secret: str) -> tuple[dict, bool]:
    """返回 (载荷, 签名是否可信)。离线闸机也只依赖这两个事实。"""
    try:
        body, sig = token.split(".", 1)
        payload = json.loads(unb64u(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, False
    trusted = hmac.compare_digest(sign(body.encode("ascii"), secret), sig)
    return payload, trusted


# ---- 离线闸机：断网时本地验签并排队签名回执 -------------------------------


class OfflineGate:
    """模拟场馆闸机：持设备密钥离线判定，回执先入本地队列。"""

    def __init__(self, device: GateDevice, secret: str):
        self.device = device
        self._secret = secret
        self._queue: list[dict] = []
        self._scanned = 0

    def scan(self, token: str, at: datetime) -> dict:
        payload, trusted = decode_pass_token(token, self._secret)
        verdict = "DENY"
        reason = "invalid_signature"
        if trusted:
            expires = parse_ts(payload["exp"])
            if at > expires:
                reason = "pass_expired"
            elif self.device.venue not in payload.get("venues", []):
                reason = "venue_not_allowed"
            elif payload.get("verdict") != "GREEN":
                reason = "verdict_not_green"
            else:
                verdict, reason = "GREEN", "ok"
        self._scanned += 1
        receipt_id = f"rcpt-{self.device.device_id}-{self._scanned}"
        receipt = {
            "receipt_id": receipt_id,
            "device_id": self.device.device_id,
            "token": token,
            "venue": self.device.venue,
            "scan_at": format_ts(at),
            "gate_verdict": verdict,
            "reason": reason,
        }
        envelope = self._seal(receipt)
        # 无论放行与否都留痕；离线期间排队，恢复后逐条重传，可安全重复。
        self._queue.append(envelope)
        return {"receipt_id": receipt_id, "verdict": verdict, "reason": reason}

    def _seal(self, receipt: dict) -> dict:
        inner = b64u(json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        return {"receipt": inner, "sig": sign(inner.encode("ascii"), self.device.secret)}

    def queued_uploads(self) -> list[dict]:
        return list(self._queue)

    def replay(self, index: int) -> dict:
        """断网恢复后重传（同一信封，服务端必须去重）。"""
        return self._queue[index]


# ---- 领域存储与规则编排 ---------------------------------------------------


class AccreditationStore:
    def __init__(self, secret: str = "demo-shared-secret", clock=utc_now):
        self._secret = secret
        self._clock = clock
        self.rule_sets: list[RuleSet] = []
        self.agencies: dict[str, Agency] = {}
        self.principals: dict[str, Principal] = {}
        self.tokens: dict[str, str] = {}
        self.events: dict[str, Event] = {}
        self.delegations: dict[str,Delegation] = {}
        self.members: dict[str, Member] = {}
        self.rosters: dict[str, list[RosterVersion]] = {}
        self.submissions: dict[tuple[str, str], list[Submission]] = {}
        self.verifications: dict[tuple[str, str], list[Verification]] = {}
        self.decisions: list[Decision] = []
        self.passes: dict[str, Pass] = {}
        self.pass_tokens: dict[str, str] = {}
        self.devices: dict[str, GateDevice] = {}
        self.entries_by_receipt: dict[str, Entry] = {}
        self.entries_by_pass_venue: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}

    # 小工具 ----------------------------------------------------------------

    def _now(self) -> datetime:
        return self._clock()

    def _new_id(self, kind: str) -> str:
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        return f"{kind}-{n:04d}"

    def _decide(self, kind, subject_type, subject_id, actor, reason,
                basis=None, effect=None, supersedes=()) -> Decision:
        d = Decision(
            decision_id=self._new_id("dec"),
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            at=self._now(),
            actor=actor,
            reason=reason,
            basis=tuple(basis or ()),
            effect=effect or {},
            supersedes=tuple(supersedes),
        )
        self.decisions.append(d)
        return d

    def decisions_for(self, subject_type: str, subject_id: str) -> list[Decision]:
        return [
            d for d in self.decisions
            if d.subject_type == subject_type and d.subject_id == subject_id
        ]

    # 赛区规则 ---------------------------------------------------------------

    def publish_rule_set(self, zone, requirements, effective_from, actor,
                         effective_until=None, published_at=None) -> RuleSet:
        """赛区发布材料规则；同赛区版本号递增，生效期不可与既有版本重叠。"""
        from dataclasses import replace

        effective_from = parse_ts(effective_from)
        effective_until = parse_ts(effective_until) if effective_until else None
        with_zone = [r for r in self.rule_sets if r.zone == zone]
        existing = sorted(with_zone, key=lambda r: r.version)
        for r in existing:
            if r.effective_until is None and r.effective_from <= effective_from:
                # 新版生效即截断上一版的开放生效期，保证任一时点只有一版有效。
                self.rule_sets[self.rule_sets.index(r)] = replace(
                    r, effective_until=effective_from)
            elif r.active_at(effective_from):
                raise DomainError(f"赛区 {zone} 在该时点已有生效规则 {r.rule_set_id}")
        version = (existing[-1].version + 1) if existing else 1
        reqs = tuple(
            Requirement(
                code=spec["code"],
                title=spec.get("title", REQ_TITLES.get(spec["code"], spec["code"])),
                roles=frozenset(spec.get("roles", ROLES)),
                minor_only=spec.get("minor_only", spec["code"] == GUARDIAN_CONSENT),
            )
            for spec in requirements
        )
        rs = RuleSet(
            rule_set_id=f"rs-{zone}-v{version}",
            zone=zone,
            version=version,
            requirements=reqs,
            published_at=parse_ts(published_at) if published_at else self._now(),
            effective_from=effective_from,
            effective_until=effective_until,
            actor=actor,
        )
        self.rule_sets.append(rs)
        return rs

    def active_rule_set(self, zone: str, at: datetime) -> RuleSet:
        candidates = [r for r in self.rule_sets if r.zone == zone and r.active_at(at)]
        if not candidates:
            raise DomainError(f"赛区 {zone} 在 {format_ts(at)} 没有生效的材料规则")
        return max(candidates, key=lambda r: r.version)

    # 机构与账号 -------------------------------------------------------------

    def register_agency(self, agency_id, name, region, req_codes) -> Agency:
        if region not in REGIONS:
            raise DomainError(f"未知地区 {region}")
        agency = Agency(agency_id, name, region, frozenset(req_codes))
        self.agencies[agency_id] = agency
        return agency

    def add_principal(self, principal_id, roles, agency_id=None,
                      delegation_id=None, token=None) -> Principal:
        roles = frozenset(roles)
        if agency_id and agency_id not in self.agencies:
            raise DomainError(f"未知机构 {agency_id}")
        if delegation_id and delegation_id not in self.delegations:
            raise DomainError(f"未知代表队 {delegation_id}")
        p = Principal(principal_id, roles, agency_id, delegation_id, token)
        self.principals[principal_id] = p
        if token:
            self.tokens[token] = principal_id
        return p

    def authenticate(self, token: str | None) -> Principal:
        if not token or token not in self.tokens:
            raise DomainError("未认证")
        return self.principals[self.tokens[token]]

    def register_device(self, device_id, venue, zone, secret) -> GateDevice:
        device = GateDevice(device_id, venue, zone, secret)
        self.devices[device_id] = device
        return device

    # 赛事与代表队 -----------------------------------------------------------

    def create_event(self, event_id, title, host_zone, starts_at, ends_at, venues) -> Event:
        event = Event(
            event_id=event_id,
            title=title,
            host_zone=host_zone,
            starts_at=parse_ts(starts_at),
            ends_at=parse_ts(ends_at),
            venues=tuple(venues),
        )
        self.events[event_id] = event
        return event

    def register_delegation(self, delegation_id, name, home_region) -> Delegation:
        if home_region not in REGIONS:
            raise DomainError(f"未知地区 {home_region}")
        d = Delegation(delegation_id, name, home_region)
        self.delegations[delegation_id] = d
        return d

    def submit_roster(self, delegation_id, members, actor, note="",
                      effective_from=None) -> RosterVersion:
        """提交（换人后的）新名单版本。member_id 稳定则材料与历史决定跟随个人。"""
        if delegation_id not in self.delegations:
            raise DomainError(f"未知代表队 {delegation_id}")
        at = self._now()
        history = self.rosters.setdefault(delegation_id, [])
        sequence = history[-1].sequence + 1 if history else 1
        ids: list[str] = []
        for spec in members:
            if spec["role"] not in ROLES:
                raise DomainError(f"未知职责 {spec['role']}")
            mid = spec["member_id"]
            if mid not in self.members:
                self.members[mid] = Member(
                    member_id=mid,
                    name=spec["name"],
                    role=spec["role"],
                    date_of_birth=spec["date_of_birth"],
                    delegation_id=delegation_id,
                    home_region=spec.get("home_region",
                                        self.delegations[delegation_id].home_region),
                )
            ids.append(mid)
        if len(set(ids)) != len(ids):
            raise DomainError("名单中存在重复队员")
        roster = RosterVersion(
            roster_id=f"roster-{delegation_id}-v{sequence}",
            delegation_id=delegation_id,
            sequence=sequence,
            member_ids=tuple(ids),
            effective_from=parse_ts(effective_from) if effective_from else at,
            created_at=at,
            actor=actor,
            note=note,
        )
        history.append(roster)
        prior = history[-2].roster_id if sequence > 1 else None
        self._decide(
            "roster_change", "delegation", delegation_id, actor,
            note or f"提交第 {sequence} 版名单",
            basis=([{"type": "roster", "id": prior}] if prior else []),
            effect={"roster_id": roster.roster_id, "member_ids": ids},
        )
        return roster

    def roster_at(self, delegation_id: str, at: datetime) -> RosterVersion:
        history = self.rosters.get(delegation_id, [])
        visible = [r for r in history if r.effective_from <= at]
        if not visible:
            raise DomainError(f"代表队 {delegation_id} 在该时点没有生效名单")
        return visible[-1]

    # 材料提交与机构核验 -----------------------------------------------------

    def upload_document(self, member_id, req_code, body_digest, actor,
                        expires_at=None, issued_at=None) -> Submission:
        member = self._require_member(member_id)
        at = self._now()
        sub = Submission(
            submission_id=self._new_id("sub"),
            member_id=member_id,
            req_code=req_code,
            body_digest=body_digest,
            issued_at=parse_ts(issued_at) if issued_at else at,
            expires_at=parse_ts(expires_at) if expires_at else None,
            uploaded_at=at,
            actor=actor,
        )
        self.submissions.setdefault((member_id, req_code), []).append(sub)
        return sub

    def document_body(self, principal: Principal, member_id: str,
                      req_code: str) -> dict:
        """原件仅向负责该项目的授权审核岗开放。"""
        if "reviewer" not in principal.roles or not principal.agency_id:
            raise DomainError("仅授权审核岗可查看原件")
        agency = self.agencies[principal.agency_id]
        if req_code not in agency.req_codes:
            raise DomainError("该机构无权查看本项材料")
        subs = self.submissions.get((member_id, req_code), [])
        if not subs:
            raise DomainError("材料不存在")
        latest = subs[-1]
        member = self._require_member(member_id)
        return {
            "member_id": member_id,
            "member_name": member.name,
            "req_code": req_code,
            "body_digest": latest.body_digest,
            "submission_id": latest.submission_id,
        }

    def verify_document(self, principal: Principal, member_id, req_code,
                        approved, note="") -> tuple[Verification, Decision]:
        """授权机构给出核验结论；续证即对新材料再次核验并声明 supersedes。"""
        if "reviewer" not in principal.roles or not principal.agency_id:
            raise DomainError("仅授权审核岗可核验材料")
        agency = self.agencies[principal.agency_id]
        if req_code not in agency.req_codes:
            raise DomainError(f"机构 {agency.agency_id} 不核验 {req_code}")
        subs = self.submissions.get((member_id, req_code), [])
        if not subs:
            raise DomainError("尚无材料可核验")
        submission = subs[-1]
        at = self._now()
        prior = self.verifications.setdefault((member_id, req_code), [])
        same_agency_prior = [v for v in prior if v.agency_id == agency.agency_id]
        verification = Verification(
            verification_id=self._new_id("ver"),
            member_id=member_id,
            req_code=req_code,
            agency_id=agency.agency_id,
            region=agency.region,
            approved=approved,
            reviewer=principal.principal_id,
            at=at,
            valid_until=submission.expires_at if approved else None,
            submission_id=submission.submission_id,
            note=note,
        )
        prior.append(verification)
        decision = self._decide(
            "verification", "member", member_id, principal.principal_id,
            note or ("核验通过" if approved else "核验不通过"),
            basis=[
                {"type": "agency", "id": agency.agency_id},
                {"type": "submission", "id": submission.submission_id},
            ],
            effect={
                "req_code": req_code,
                "approved": approved,
                "valid_until": format_ts(submission.expires_at)
                if approved and submission.expires_at else None,
            },
            supersedes=tuple(v.verification_id for v in same_agency_prior),
        )
        self._detect_conflicts(member_id, actor=principal.principal_id)
        return verification, decision

    def _latest_per_region(self, member_id, req_code, at) -> dict[str, Verification]:
        out: dict[str, Verification] = {}
        for v in self.verifications.get((member_id, req_code), []):
            if v.at > at:
                continue
            # 核验按时间追加；同时间戳（同一时刻续证）以后到者为准。
            prev = out.get(v.region)
            if prev is None or v.at >= prev.at:
                out[v.region] = v
        return out

    def _detect_conflicts(self, member_id, actor) -> list[Decision]:
        """两地结论不一致：暂停仅限该个人，并作废其未使用凭证。"""
        at = self._now()
        if self._active_suspension(member_id) is not None:
            return []
        conflicting: set[str] = set()
        for (mid, code), verifs in self.verifications.items():
            if mid != member_id:
                continue
            latest = self._latest_per_region(member_id, code, at)
            regions = set(latest)
            if len(regions) < 2:
                continue
            approved_regions = {r for r, v in latest.items() if v.valid_approval(at)}
            rejected_regions = {r for r, v in latest.items() if not v.approved}
            if approved_regions and rejected_regions:
                conflicting.add(code)
        if not conflicting:
            return []
        basis = []
        for code in sorted(conflicting):
            for v in self._latest_per_region(member_id, code, at).values():
                basis.append({"type": "verification", "id": v.verification_id})
        decision = self._decide(
            "suspension", "member", member_id, actor or "system",
            "两地核验结论冲突，暂停本人通行资格，交指定人员复核（不影响同队其他人员）",
            basis=basis,
            effect={"hold": True, "req_codes": sorted(conflicting)},
        )
        for pid, token in list(self.pass_tokens.items()):
            p = self.passes[pid]
            if p.member_id == member_id and not p.revoked:
                self.passes[pid] = Pass(**{**p.__dict__, "revoked": True,
                                           "revoke_reason": decision.decision_id})
        return [decision]

    def _active_suspension(self, member_id) -> Decision | None:
        for d in self.decisions_for("member", member_id):
            if d.kind == "suspension" and d.effect.get("hold") and d.closed_by is None:
                return d
        return None

    def resolve_conflict(self, principal: Principal, member_id, resolution,
                         reason, req_codes=None) -> Decision:
        """指定复核人对冲突作出权威结论；暂停只在复核后解除。"""
        if "conflict_resolver" not in principal.roles:
            raise DomainError("仅指定复核人可处理冲突")
        if resolution not in ("uphold_approved", "uphold_rejected"):
            raise DomainError("resolution 必须是 uphold_approved / uphold_rejected")
        suspension = self._active_suspension(member_id)
        if suspension is None:
            raise DomainError("该队员没有待复核的冲突暂停")
        at = self._now()
        effect = {
            "hold": False,
            "resolution": resolution,
            "req_codes": req_codes or suspension.effect.get("req_codes", []),
        }
        decision = self._decide(
            "resolution", "member", member_id, principal.principal_id, reason,
            basis=[{"type": "decision", "id": suspension.decision_id}],
            effect=effect,
        )
        suspension.__dict__["closed_by"] = decision.decision_id
        return decision

    # 申诉与临时医疗豁免 ------------------------------------------------------

    def decide_appeal(self, principal: Principal, member_id, req_code, granted,
                      reason, valid_until=None, evidence_digest=None) -> Decision:
        if "appeal_officer" not in principal.roles:
            raise DomainError("仅申诉审核岗可裁决申诉")
        at = self._now()
        if granted and valid_until is None:
            raise DomainError("申诉通过需给出结论有效期")
        if granted and parse_ts(valid_until) <= at:
            raise DomainError("申诉结论有效期已过")
        return self._decide(
            "appeal", "member", member_id, principal.principal_id, reason,
            basis=([{"type": "evidence", "id": evidence_digest}]
                   if evidence_digest else []),
            effect={
                "req_code": req_code,
                "outcome": "granted" if granted else "denied",
                "valid_until": format_ts(parse_ts(valid_until)) if valid_until else None,
            },
        )

    def grant_medical_exemption(self, principal: Principal, member_id, req_code,
                                valid_until, reason, evidence_digest) -> Decision:
        if "medical_officer" not in principal.roles:
            raise DomainError("仅医疗官可批准临时医疗豁免")
        until = parse_ts(valid_until)
        if until <= self._now():
            raise DomainError("豁免有效期已过")
        return self._decide(
            "exemption", "member", member_id, principal.principal_id, reason,
            basis=[{"type": "medical_evidence", "id": evidence_digest}],
            effect={"req_code": req_code, "valid_until": format_ts(until)},
        )

    def _active_exception(self, member_id, req_code, at) -> Decision | None:
        """当前有效的申诉通过/医疗豁免，视为该项满足。"""
        best = None
        for d in self.decisions_for("member", member_id):
            if d.effect.get("req_code") != req_code:
                continue
            if d.kind == "exemption":
                until = parse_ts(d.effect["valid_until"])
                if at < until:
                    best = d if best is None or d.at > best.at else best
            elif d.kind == "appeal" and d.effect.get("outcome") == "granted":
                until = parse_ts(d.effect["valid_until"])
                if at < until:
                    best = d if best is None or d.at > best.at else best
        return best

    def _active_resolution(self, member_id, req_code) -> Decision | None:
        """指定复核人对冲突的最新权威结论，压过两地分歧；以新核验重开冲突。"""
        latest_verification_at = max(
            (v.at for verifs in self.verifications.values() for v in verifs
             if v.member_id == member_id and v.req_code == req_code),
            default=None,
        )
        resolution = None
        for d in self.decisions_for("member", member_id):
            if d.kind != "resolution":
                continue
            if req_code not in d.effect.get("req_codes", []):
                continue
            if resolution is None or d.at > resolution.at:
                resolution = d
        if resolution is not None and (
                latest_verification_at is None
                or resolution.at >= latest_verification_at):
            return resolution
        return None

    # 资格评估 ---------------------------------------------------------------

    def _require_member(self, member_id) -> Member:
        if member_id not in self.members:
            raise DomainError(f"未知队员 {member_id}")
        return self.members[member_id]

    def evaluate(self, member_id, event_id, at=None) -> dict:
        member = self._require_member(member_id)
        event = self.events.get(event_id)
        if event is None:
            raise DomainError(f"未知赛事 {event_id}")
        at = parse_ts(at) if at else self._now()
        rule_set = self.active_rule_set(event.host_zone, at)
        roster = self.roster_at(member.delegation_id, at)
        on_roster = member_id in roster.member_ids
        minor = is_minor(member.date_of_birth, event.starts_at)
        items = []
        for req in rule_set.requirements:
            if not req.applies_to(member.role, minor):
                continue
            items.append(self._evaluate_item(member, req, event, at))
        hold = self._active_suspension(member_id)
        if hold is not None:
            status = "suspended"
        elif not on_roster:
            status = "off_roster"
        elif any(i["status"] == "rejected" for i in items):
            status = "ineligible"
        elif any(i["status"] in ("missing", "expired", "in_review", "conflict")
                 for i in items):
            status = "pending"
        else:
            status = "eligible"
        return {
            "member_id": member_id,
            "member_name": member.name,
            "role": member.role,
            "event_id": event_id,
            "at": format_ts(at),
            "status": status,
            "on_roster": on_roster,
            "minor": minor,
            "rule_set_id": rule_set.rule_set_id,
            "roster_id": roster.roster_id,
            "hold_decision_id": hold.decision_id if hold else None,
            "items": items,
        }

    def _evaluate_item(self, member, req, event, at) -> dict:
        exception = self._active_exception(member.member_id, req.code, at)
        if exception is not None:
            return {
                "code": req.code,
                "title": req.title,
                "status": "exempted" if exception.kind == "exemption" else "appeal_upheld",
                "decision_id": exception.decision_id,
                "valid_until": exception.effect.get("valid_until"),
            }
        resolution = self._active_resolution(member.member_id, req.code)
        if resolution is not None:
            if resolution.effect.get("resolution") == "uphold_approved":
                approved_regions = [
                    v for v in self._latest_per_region(
                        member.member_id, req.code, at).values()
                    if v.valid_approval(at)
                ]
                v = sorted(approved_regions, key=lambda x: x.at)[-1]
                return {"code": req.code, "title": req.title,
                        "status": "verified", "agency": v.agency_id,
                        "verification_id": v.verification_id,
                        "resolution_id": resolution.decision_id,
                        "valid_until": format_ts(v.valid_until) if v.valid_until else None}
            return {"code": req.code, "title": req.title, "status": "rejected",
                    "resolution_id": resolution.decision_id}
        latest = self._latest_per_region(member.member_id, req.code, at)
        approved = [v for v in latest.values() if v.valid_approval(at)]
        rejected = [v for v in latest.values() if not v.approved]
        expired_approved = [
            v for v in latest.values()
            if v.approved and not v.valid_approval(at)
        ]
        if approved and rejected:
            return {"code": req.code, "title": req.title, "status": "conflict",
                    "agencies": sorted(v.agency_id for v in latest.values())}
        if rejected:
            v = sorted(rejected, key=lambda x: x.at)[-1]
            return {"code": req.code, "title": req.title, "status": "rejected",
                    "agency": v.agency_id, "verification_id": v.verification_id}
        if approved:
            v = sorted(approved, key=lambda x: x.at)[-1]
            return {"code": req.code, "title": req.title, "status": "verified",
                    "agency": v.agency_id, "verification_id": v.verification_id,
                    "valid_until": format_ts(v.valid_until) if v.valid_until else None}
        if expired_approved:
            v = sorted(expired_approved, key=lambda x: x.valid_until)[0]
            return {"code": req.code, "title": req.title, "status": "expired",
                    "agency": v.agency_id, "verification_id": v.verification_id,
                    "valid_until": format_ts(v.valid_until)}
        if self.submissions.get((member.member_id, req.code)):
            return {"code": req.code, "title": req.title, "status": "in_review"}
        return {"code": req.code, "title": req.title, "status": "missing"}

    # 办赛人员看板：按紧迫程度排列的缺件与到期项 -----------------------------

    _URGENCY_WEIGHT = {
        "conflict": 0,
        "expired": 1,
        "rejected": 2,
        "missing": 3,
        "in_review": 4,
        "expiring_during_event": 5,
    }

    def urgency_dashboard(self, event_id, at=None) -> dict:
        event = self.events[event_id]
        at = parse_ts(at) if at else self._now()
        rows = []
        for delegation_id in self.rosters:
            roster = self.roster_at(delegation_id, at)
            for member_id in roster.member_ids:
                result = self.evaluate(member_id, event_id, at)
                for item in result["items"]:
                    state = item["status"]
                    deadline = None
                    if state == "expired":
                        deadline = item["valid_until"]
                    elif state == "verified" and item.get("valid_until"):
                        expires = parse_ts(item["valid_until"])
                        if expires < event.ends_at:
                            state = "expiring_during_event"
                            deadline = format_ts(expires)
                    if state not in self._URGENCY_WEIGHT:
                        continue  # verified / exempted / appeal_upheld 不进缺件看板
                    deadline_dt = parse_ts(deadline) if deadline else event.starts_at
                    rows.append({
                        "member_id": member_id,
                        "member_name": result["member_name"],
                        "delegation_id": delegation_id,
                        "req_code": item["code"],
                        "req_title": item["title"],
                        "state": state,
                        "deadline": format_ts(deadline_dt),
                        "hours_to_deadline": round(
                            (deadline_dt - at).total_seconds() / 3600, 1),
                    })
                if result["status"] == "suspended":
                    rows.append({
                        "member_id": member_id,
                        "member_name": result["member_name"],
                        "delegation_id": delegation_id,
                        "req_code": "*",
                        "req_title": "两地结论冲突，暂停待复核",
                        "state": "conflict",
                        "deadline": format_ts(event.starts_at),
                        "hours_to_deadline": round(
                            (event.starts_at - at).total_seconds() / 3600, 1),
                    })
        rows.sort(key=lambda r: (self._URGENCY_WEIGHT[r["state"]],
                                 r["deadline"], r["member_name"]))
        return {"event_id": event_id, "at": format_ts(at), "items": rows}

    # 通行凭证 ---------------------------------------------------------------

    def issue_pass(self, principal: Principal, member_id, event_id,
                   venues=None, ttl=DEFAULT_PASS_TTL) -> Pass:
        """资格合格才发证；凭证载荷只含闸机判断通行所需的最小信息。"""
        if "pass_officer" not in principal.roles:
            raise DomainError("仅发证岗可签发通行凭证")
        at = self._now()
        result = self.evaluate(member_id, event_id, at)
        if result["status"] != "eligible":
            raise DomainError(f"资格状态为 {result['status']}，不能签发通行凭证")
        event = self.events[event_id]
        venue_list = tuple(venues) if venues else event.venues
        unknown = [v for v in venue_list if v not in event.venues]
        if unknown:
            raise DomainError(f"赛事不含场馆 {unknown}")
        member = self.members[member_id]
        pid = self._new_id("pass")
        payload = {
            "v": 1,
            "pass_id": pid,
            "member_id": member_id,
            "name": member.name,
            "role": member.role,
            "delegation_id": member.delegation_id,
            "event_id": event_id,
            "venues": list(venue_list),
            "verdict": "GREEN",
            "iat": format_ts(at),
            "exp": format_ts(at + ttl),
            "rule_set_id": result["rule_set_id"],
            "roster_id": result["roster_id"],
        }
        token = encode_pass_token(payload, self._secret)
        p = Pass(
            pass_id=pid,
            member_id=member_id,
            event_id=event_id,
            zones=venue_list,
            issued_at=at,
            expires_at=at + ttl,
            rule_set_id=result["rule_set_id"],
            roster_id=result["roster_id"],
            token=token,
        )
        self.passes[pid] = p
        self.pass_tokens[pid] = token
        return p

    def validate_pass(self, token, at=None) -> dict:
        """在线校验：场馆/接驳人员只能看到能否通行的结论与最小信息。"""
        at = parse_ts(at) if at else self._now()
        payload, trusted = decode_pass_token(token, self._secret)
        if not trusted:
            return {"verdict": "DENY", "reason": "invalid_signature"}
        pid = payload["pass_id"]
        pass_ = self.passes.get(pid)
        if pass_ is None:
            return {"verdict": "DENY", "reason": "unknown_pass"}
        if pass_.revoked:
            return {"verdict": "DENY", "reason": "revoked",
                    "member_id": payload["member_id"], "name": payload["name"]}
        if at > pass_.expires_at:
            return {"verdict": "DENY", "reason": "pass_expired",
                    "member_id": payload["member_id"], "name": payload["name"]}
        return {
            "verdict": "GREEN",
            "name": payload["name"],
            "role": payload["role"],
            "venues": payload["venues"],
            "event_id": payload["event_id"],
            "expires_at": payload["exp"],
            # 注意：不含证件号、材料摘 要、出生日期等任何原件信息。
        }

    # 闸机回执与入场记录 ------------------------------------------------------

    def upload_receipt(self, envelope: dict, at=None) -> dict:
        """接收离线闸机回执；同一回执重复上传永远只产生一条入场记录。"""
        at = parse_ts(at) if at else self._now()
        inner = envelope.get("receipt", "")
        sig = envelope.get("sig", "")
        try:
            receipt = json.loads(unb64u(inner).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise DomainError("回执格式错误")
        device = self.devices.get(receipt.get("device_id", ""))
        if device is None:
            raise DomainError("未知设备")
        if not hmac.compare_digest(sign(inner.encode("ascii"), device.secret), sig):
            raise DomainError("设备签名校验失败")
        receipt_id = receipt["receipt_id"]
        if receipt_id in self.entries_by_receipt:
            entry = self.entries_by_receipt[receipt_id]
            entry.__dict__["duplicate_uploads"] += 1
            return {"entry_id": entry.entry_id, "deduplicated": True,
                    "verdict": entry.verdict}
        if receipt["gate_verdict"] != "GREEN":
            raise DomainError(f"闸机判定为 {receipt['gate_verdict']}，不入入场账")
        scan_at = parse_ts(receipt["scan_at"])
        if scan_at > at + timedelta(seconds=1):
            raise DomainError("扫描时间异常")
        if at - scan_at > RECEIPT_GRACE:
            raise DomainError("回执超过离线宽限，需现场复核")
        payload, trusted = decode_pass_token(receipt["token"], self._secret)
        if not trusted:
            raise DomainError("凭证签名不可信")
        pid = payload["pass_id"]
        pass_ = self.passes.get(pid)
        if pass_ is None:
            raise DomainError("凭证不存在")
        if scan_at > pass_.expires_at:
            raise DomainError("扫描时凭证已过期")
        if receipt["venue"] not in pass_.zones:
            raise DomainError("场馆不在凭证范围")
        venue_key = (pid, receipt["venue"])
        if venue_key in self.entries_by_pass_venue:
            # 不同回执但同一凭证同场馆重复扫：仍只算一次通行。
            prior_id = self.entries_by_pass_venue[venue_key]
            prior = next(e for e in self.entries_by_receipt.values()
                         if e.entry_id == prior_id)
            prior.__dict__["duplicate_uploads"] += 1
            self.entries_by_receipt[receipt_id] = prior
            return {"entry_id": prior.entry_id, "deduplicated": True,
                    "verdict": prior.verdict}
        # 入场快照：以扫描/发证时点的版本为准，事后规则换人不改变这条记录。
        member_id = pass_.member_id
        member = self.members[member_id]
        event = self.events[pass_.event_id]
        eval_at = min(scan_at, pass_.expires_at)
        result = self.evaluate(member_id, pass_.event_id, eval_at)
        checks = tuple(
            {"req_code": i["code"], "status": i["status"],
             "agency": i.get("agency"), "verification_id": i.get("verification_id"),
             "decision_id": i.get("decision_id")}
            for i in result["items"]
        )
        exceptions = tuple(
            i["decision_id"] for i in result["items"]
            if i["status"] in ("exempted", "appeal_upheld")
        )
        entry = Entry(
            entry_id=self._new_id("entry"),
            receipt_id=receipt_id,
            device_id=device.device_id,
            venue=device.venue,
            pass_id=pid,
            member_id=member_id,
            delegation_id=member.delegation_id,
            event_id=pass_.event_id,
            scan_at=scan_at,
            recorded_at=at,
            rule_set_id=pass_.rule_set_id,
            roster_id=pass_.roster_id,
            verdict="GREEN",
            checks=checks,
            exception_decisions=exceptions,
            receipt_sig=sig,
        )
        self.entries_by_receipt[receipt_id] = entry
        self.entries_by_pass_venue[venue_key] = entry.entry_id
        return {"entry_id": entry.entry_id, "deduplicated": False, "verdict": "GREEN"}

    def entry_trace(self, entry_id: str) -> dict | None:
        """从一条入场记录查回名单版本、核验机构、例外决定与设备回执。"""
        entry = next((e for e in self.entries_by_receipt.values()
                      if e.entry_id == entry_id), None)
        if entry is None:
            return None
        verifications = []
        agencies_seen = set()
        for check in entry.checks:
            if check.get("verification_id"):
                v = next(v for vs in self.verifications.values() for v in vs
                         if v.verification_id == check["verification_id"])
                agencies_seen.add(v.agency_id)
                verifications.append({
                    "verification_id": v.verification_id,
                    "agency_id": v.agency_id,
                    "region": v.region,
                    "reviewer": v.reviewer,
                    "approved": v.approved,
                    "at": format_ts(v.at),
                })
        exceptions = [
            d.public() for d in self.decisions
            if d.decision_id in entry.exception_decisions
        ]
        roster = next(r for rs in self.rosters.values() for r in rs
                      if r.roster_id == entry.roster_id)
        return {
            "entry_id": entry.entry_id,
            "verdict": entry.verdict,
            "scan_at": format_ts(entry.scan_at),
            "recorded_at": format_ts(entry.recorded_at),
            "member_id": entry.member_id,
            "delegation_id": entry.delegation_id,
            "event_id": entry.event_id,
            "rule_set": next(r.public() for r in self.rule_sets
                             if r.rule_set_id == entry.rule_set_id),
            "roster_version": roster.public(),
            "verifications": verifications,
            "agencies": sorted(agencies_seen),
            "exception_decisions": exceptions,
            "device_receipt": {
                "receipt_id": entry.receipt_id,
                "device_id": entry.device_id,
                "venue": entry.venue,
                "sig": entry.receipt_sig,
            },
            "duplicate_uploads": entry.duplicate_uploads,
        }

    def all_entries(self) -> list[Entry]:
        seen = {}
        for e in self.entries_by_receipt.values():
            seen[e.entry_id] = e
        return sorted(seen.values(), key=lambda e: e.entry_id)
