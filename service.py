"""湾区参赛资格通行的服务入口与 HTTP API。

角色与最小披露：
* reviewer（分属各机构）可看本机构负责项目的原件并给出核验结论；
* venue_staff / 通行证校验只拿到“能否通行 + 姓名/职责/场馆/到期”结论；
* organizer 可看缺件看板与入场追溯；原件摘 要不对其开放。
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from accreditation import (
    AccreditationStore,
    DEFAULT_PASS_TTL,
    DomainError,
    format_ts,
    parse_ts,
)
from demo import EVENT_ID, build_demo_store, publish_initial_rules

SERVICE_ID = "gba-accreditation"
SERVICE_NAME = "湾区参赛资格通行"


def health_payload():
    """返回稳定的服务身份信息。"""
    return {"status": "ok", "service": SERVICE_ID, "name": SERVICE_NAME}


def create_handler(store: AccreditationStore):
    class Handler(BaseHTTPRequestHandler):
        # ---- 基础收发 -----------------------------------------------------

        def _send(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise DomainError(f"请求体不是合法 JSON：{exc}") from exc
            if not isinstance(data, dict):
                raise DomainError("请求体必须是 JSON 对象")
            return data

        def _principal(self):
            return store.authenticate(
                self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                or None
            )

        def _require_role(self, principal, *roles):
            if not any(r in principal.roles for r in roles):
                raise DomainError(f"需要岗位之一：{', '.join(roles)}")

        def _require_delegation(self, principal, delegation_id):
            if "organizer" in principal.roles:
                return
            if not ("delegation_manager" in principal.roles
                    and principal.delegation_id == delegation_id):
                raise DomainError("只能操作本代表队")

        def log_message(self, *_args):
            return

        # ---- 路由 ---------------------------------------------------------

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            path = parsed.path.strip("/")
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            parts = path.split("/") if path else []
            try:
                if method == "GET" and path == "health":
                    self._send(health_payload())
                    return
                if method == "GET" and path == "events":
                    p = self._principal()
                    self._require_role(p, "organizer", "pass_officer",
                                       "delegation_manager", "venue_staff")
                    self._send({"events": [
                        {"event_id": e.event_id, "title": e.title,
                         "host_zone": e.host_zone,
                         "starts_at": format_ts(e.starts_at),
                         "ends_at": format_ts(e.ends_at),
                         "venues": list(e.venues)}
                        for e in store.events.values()
                    ]})
                    return
                if method == "POST" and path == "admin/rules":
                    self._publish_rules()
                    return
                if method == "GET" and parts[:1] == ["rules"]:
                    zone = query.get("zone")
                    at = parse_ts(query["at"]) if query.get("at") else store._now()
                    rs = store.active_rule_set(zone, at)
                    self._send(rs.public())
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "delegations" \
                        and parts[2] == "roster":
                    self._submit_roster(parts[1])
                    return
                if method == "POST" and len(parts) == 3 and parts[0] == "members" \
                        and parts[2] == "documents":
                    self._upload_document(parts[1])
                    return
                if method == "GET" and len(parts) == 4 and parts[0] == "members" \
                        and parts[2] == "documents":
                    self._read_document(parts[1], parts[3])
                    return
                if method == "POST" and path == "verifications":
                    self._verify()
                    return
                if method == "GET" and len(parts) == 3 and parts[0] == "members" \
                        and parts[2] == "eligibility":
                    self._eligibility(parts[1], query)
                    return
                if method == "GET" and len(parts) == 3 and parts[0] == "events" \
                        and parts[2] == "dashboard":
                    self._dashboard(parts[1], query)
                    return
                if method == "POST" and path == "appeals":
                    self._appeal()
                    return
                if method == "POST" and path == "exemptions":
                    self._exemption()
                    return
                if method == "POST" and path == "conflicts/resolve":
                    self._resolve()
                    return
                if method == "POST" and path == "passes":
                    self._issue_pass()
                    return
                if method == "GET" and path == "validate":
                    self._validate(query)
                    return
                if method == "POST" and path == "gates/receipts":
                    self._upload_receipt()
                    return
                if method == "GET" and len(parts) == 3 and parts[0] == "entries" \
                        and parts[2] == "trace":
                    self._trace(parts[1])
                    return
                self.send_error(404)
            except DomainError as exc:
                self._send({"error": str(exc)}, 400)
            except KeyError as exc:
                self._send({"error": f"缺少字段 {exc}"}, 400)

        # ---- 各端点 -------------------------------------------------------

        def _publish_rules(self):
            p = self._principal()
            self._require_role(p, "organizer")
            body = self._read_json()
            rs = store.publish_rule_set(
                zone=body["zone"],
                requirements=body["requirements"],
                effective_from=body["effective_from"],
                effective_until=body.get("effective_until"),
                actor=p.principal_id,
            )
            self._send(rs.public(), 201)

        def _submit_roster(self, delegation_id):
            p = self._principal()
            self._require_delegation(p, delegation_id)
            body = self._read_json()
            roster = store.submit_roster(
                delegation_id=delegation_id,
                members=body["members"],
                actor=p.principal_id,
                note=body.get("note", ""),
                effective_from=body.get("effective_from"),
            )
            self._send(roster.public(), 201)

        def _upload_document(self, member_id):
            p = self._principal()
            member = store._require_member(member_id)
            self._require_delegation(p, member.delegation_id)
            body = self._read_json()
            sub = store.upload_document(
                member_id=member_id,
                req_code=body["req_code"],
                body_digest=body["body_digest"],
                actor=p.principal_id,
                expires_at=body.get("expires_at"),
                issued_at=body.get("issued_at"),
            )
            self._send({"submission_id": sub.submission_id,
                        "member_id": member_id, "req_code": sub.req_code,
                        "expires_at": format_ts(sub.expires_at)
                        if sub.expires_at else None}, 201)

        def _read_document(self, member_id, req_code):
            p = self._principal()
            self._send(store.document_body(p, member_id, req_code))

        def _verify(self):
            p = self._principal()
            body = self._read_json()
            verification, decision = store.verify_document(
                p, body["member_id"], body["req_code"],
                approved=bool(body["approved"]), note=body.get("note", ""),
            )
            self._send({"verification_id": verification.verification_id,
                        "decision_id": decision.decision_id,
                        "region": verification.region,
                        "approved": verification.approved}, 201)

        def _eligibility(self, member_id, query):
            p = self._principal()
            member = store._require_member(member_id)
            if "organizer" not in p.roles and "pass_officer" not in p.roles:
                self._require_delegation(p, member.delegation_id)
            result = store.evaluate(member_id, query.get("event_id", EVENT_ID),
                                    query.get("at"))
            self._send(result)

        def _dashboard(self, event_id, query):
            p = self._principal()
            self._require_role(p, "organizer", "pass_officer")
            self._send(store.urgency_dashboard(event_id, query.get("at")))

        def _appeal(self):
            p = self._principal()
            self._require_role(p, "appeal_officer")
            body = self._read_json()
            d = store.decide_appeal(
                p, body["member_id"], body["req_code"], bool(body["granted"]),
                body["reason"], valid_until=body.get("valid_until"),
                evidence_digest=body.get("evidence_digest"),
            )
            self._send({"decision_id": d.decision_id, "effect": d.effect}, 201)

        def _exemption(self):
            p = self._principal()
            self._require_role(p, "medical_officer")
            body = self._read_json()
            d = store.grant_medical_exemption(
                p, body["member_id"], body["req_code"], body["valid_until"],
                body["reason"], body["evidence_digest"],
            )
            self._send({"decision_id": d.decision_id, "effect": d.effect}, 201)

        def _resolve(self):
            p = self._principal()
            self._require_role(p, "conflict_resolver")
            body = self._read_json()
            d = store.resolve_conflict(
                p, body["member_id"], body["resolution"], body["reason"],
                req_codes=body.get("req_codes"),
            )
            self._send({"decision_id": d.decision_id, "effect": d.effect}, 201)

        def _issue_pass(self):
            p = self._principal()
            self._require_role(p, "pass_officer")
            body = self._read_json()
            ttl = timedelta(minutes=int(body.get("ttl_minutes",
                                                 DEFAULT_PASS_TTL.total_seconds() // 60)))
            pas = store.issue_pass(p, body["member_id"],
                                   body.get("event_id", EVENT_ID),
                                   venues=body.get("venues"), ttl=ttl)
            self._send({"pass_id": pas.pass_id, "token": pas.token,
                        "expires_at": format_ts(pas.expires_at),
                        "rule_set_id": pas.rule_set_id,
                        "roster_id": pas.roster_id}, 201)

        def _validate(self, query):
            p = self._principal()
            self._require_role(p, "venue_staff", "gate_operator", "pass_officer",
                               "organizer")
            self._send(store.validate_pass(query["token"], query.get("at")))

        def _upload_receipt(self):
            p = self._principal()
            self._require_role(p, "gate_operator")
            body = self._read_json()
            result = store.upload_receipt(body["envelope"], body.get("at"))
            self._send(result, 201)

        def _trace(self, entry_id):
            p = self._principal()
            self._require_role(p, "organizer")
            trace = store.entry_trace(entry_id)
            if trace is None:
                self._send({"error": "入场记录不存在"}, 404)
            else:
                self._send(trace)

    return Handler


def build_server(port: int, store: AccreditationStore | None = None):
    store = store or build_demo_store()
    if not store.rule_sets:
        publish_initial_rules(store, format_ts(store._now()))
    return ThreadingHTTPServer(("0.0.0.0", port), create_handler(store))


def main():
    parser = argparse.ArgumentParser(description=SERVICE_NAME)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        assert health_payload()["service"] == SERVICE_ID
        store = build_demo_store()
        publish_initial_rules(store, format_ts(store._now()))
        assert store.active_rule_set("Guangdong", store._now()).version == 1
        print("基础检查通过")
        return
    build_server(args.port).serve_forever()


if __name__ == "__main__":
    main()
