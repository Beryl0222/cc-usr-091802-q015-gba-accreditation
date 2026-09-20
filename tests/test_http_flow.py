"""HTTP API 端到端测试：真实起服务，演练“赛前—赛中—赛后”完整链路。"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import timedelta
from http.server import ThreadingHTTPServer

from accreditation import OfflineGate, format_ts, parse_ts
from demo import TOKENS, build_demo_store, publish_initial_rules
from service import create_handler

T0 = "2026-09-18T08:00:00Z"
T1 = "2026-09-19T08:00:00Z"


class ApiClient:
    def __init__(self, base):
        self.base = base

    def call(self, method, path, token=None, body=None, expect=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req) as resp:
                out = json.loads(resp.read().decode("utf-8"))
                if expect:
                    self._status = resp.status
                return out
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            if expect is not None and exc.code == expect:
                return payload
            raise AssertionError(f"{method} {path} -> {exc.code}: {payload}") from exc


class HttpFlowTest(unittest.TestCase):
    def setUp(self):
        t = [parse_ts(T0)]
        self.clock = t
        store = build_demo_store(clock=lambda: t[0])
        publish_initial_rules(store, T0)
        self.store = store
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(store))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api = ApiClient(f"http://127.0.0.1:{self.port}")

    def tearDown(self):
        self.server.shutdown()

    def test_full_journey(self):
        api = self.api
        # 健康检查无需认证。
        health = api.call("GET", "/health")
        self.assertEqual(health["service"], "gba-accreditation")

        # 未认证被拒。
        api.call("GET", "/events", expect=400)

        # 报名：港队提交一名成年运动员。
        api.call("POST", "/delegations/del-hk/roster", TOKENS["manager_hk"], {
            "members": [{"member_id": "m-wong", "name": "黃大文", "role": "athlete",
                         "date_of_birth": "2000-01-01"}]}, expect=201)
        # 不能替别的队操作。
        r = api.call("POST", "/delegations/del-gd/roster", TOKENS["manager_hk"],
                     {"members": []}, expect=400)
        self.assertIn("本代表队", r["error"])

        # 赛前看板：缺件按紧迫度排列。
        dash = api.call("GET", "/events/evt-baycup-2026/dashboard", TOKENS["organizer"])
        self.assertEqual({row["state"] for row in dash["items"]}, {"missing"})

        # 交材料 + 三机构分别核验。
        def doc(code, reviewer, expires=None):
            api.call("POST", "/members/m-wong/documents", TOKENS["manager_hk"],
                     {"req_code": code, "body_digest": f"dig-{code}",
                      **({"expires_at": expires} if expires else {})}, expect=201)
            return api.call("POST", "/verifications", reviewer,
                            {"member_id": "m-wong", "req_code": code,
                             "approved": True}, expect=201)

        doc("id_document", TOKENS["reviewer_gd"],
            format_ts(self.clock[0] + timedelta(days=30)))
        doc("insurance", TOKENS["insurer"])
        doc("anti_doping_declaration", TOKENS["anti_doping"])

        # 原件访问受岗级限制：保险机构看不到证件原件。
        denied = api.call("GET", "/members/m-wong/documents/id_document",
                          TOKENS["insurer"], expect=400)
        self.assertIn("无权", denied["error"])
        # 证件机构可以。
        body = api.call("GET", "/members/m-wong/documents/id_document",
                        TOKENS["reviewer_gd"])
        self.assertEqual(body["body_digest"], "dig-id_document")

        eligible = api.call("GET", "/members/m-wong/eligibility?event_id=evt-baycup-2026",
                            TOKENS["organizer"])
        self.assertEqual(eligible["status"], "eligible")

        # 发证。
        pas = api.call("POST", "/passes", TOKENS["pass"],
                       {"member_id": "m-wong", "ttl_minutes": 4320}, expect=201)
        # 场馆端只拿到结论。
        verdict = api.call(
            "GET", f"/validate?token={pas['token']}", TOKENS["venue"])
        self.assertEqual(verdict["verdict"], "GREEN")
        self.assertNotIn("body_digest", verdict)

        # 断网闸机在比赛日扫描，恢复后上传。
        self.clock[0] = parse_ts(T1)
        gate = OfflineGate(self.store.devices["dev-gate-1"], "demo-shared-secret")
        gate.scan(pas["token"], self.clock[0])
        up = api.call("POST", "/gates/receipts", TOKENS["gate"],
                      {"envelope": gate.queued_uploads()[0],
                       "at": T1}, expect=201)
        self.assertFalse(up["deduplicated"])
        # 网络抖动重传：仍只一次。
        again = api.call("POST", "/gates/receipts", TOKENS["gate"],
                         {"envelope": gate.queued_uploads()[0], "at": T1}, expect=201)
        self.assertTrue(again["deduplicated"])

        # 赛后追溯。
        trace = api.call("GET", f"/entries/{up['entry_id']}/trace",
                         TOKENS["organizer"])
        self.assertEqual(trace["roster_version"]["sequence"], 1)
        self.assertEqual(len(trace["verifications"]), 3)
        self.assertTrue(trace["device_receipt"]["sig"])

        # 场馆岗无权看追溯。
        api.call("GET", f"/entries/{up['entry_id']}/trace",
                 TOKENS["venue"], expect=400)

    def test_conflict_flow_via_http(self):
        api = self.api
        api.call("POST", "/delegations/del-hk/roster", TOKENS["manager_hk"], {
            "members": [{"member_id": "m-wong", "name": "黃大文", "role": "athlete",
                         "date_of_birth": "2000-01-01"}]}, expect=201)
        for code, reviewer in (("id_document", TOKENS["reviewer_gd"]),
                               ("insurance", TOKENS["insurer"]),
                               ("anti_doping_declaration", TOKENS["anti_doping"])):
            api.call("POST", "/members/m-wong/documents", TOKENS["manager_hk"],
                     {"req_code": code, "body_digest": f"dig-{code}",
                      **({"expires_at": "2026-10-31T00:00:00Z"}
                         if code == "id_document" else {})}, expect=201)
            api.call("POST", "/verifications", reviewer,
                     {"member_id": "m-wong", "req_code": code, "approved": True},
                     expect=201)
        # 港方给出相反结论：冲突，暂停仅本人。
        api.call("POST", "/verifications", TOKENS["reviewer_hk"],
                 {"member_id": "m-wong", "req_code": "id_document",
                  "approved": False, "note": "签注存疑"}, expect=201)
        elig = api.call("GET", "/members/m-wong/eligibility?event_id=evt-baycup-2026",
                        TOKENS["organizer"])
        self.assertEqual(elig["status"], "suspended")
        # 发证被拒。
        blocked = api.call("POST", "/passes", TOKENS["pass"],
                           {"member_id": "m-wong"}, expect=400)
        self.assertIn("suspended", blocked["error"])
        # 只有指定复核人能解除。
        resolved = api.call("POST", "/conflicts/resolve", TOKENS["resolver"], {
            "member_id": "m-wong", "resolution": "uphold_approved",
            "reason": "复核确认粤方结论"}, expect=201)
        self.assertFalse(resolved["effect"]["hold"])
        elig2 = api.call("GET", "/members/m-wong/eligibility?event_id=evt-baycup-2026",
                         TOKENS["organizer"])
        self.assertEqual(elig2["status"], "eligible")


if __name__ == "__main__":
    unittest.main()
