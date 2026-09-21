"""核对基础服务和领域样例。"""

import json
import unittest
from pathlib import Path

from service import SERVICE_ID, health_payload


class BaselineContractTest(unittest.TestCase):
    def test_service_identity(self):
        self.assertEqual(health_payload()["service"], SERVICE_ID)

    def test_fixture_matches_project(self):
        data = json.loads(Path("fixtures/sample.json").read_text(encoding="utf-8"))
        self.assertEqual(data["service"], SERVICE_ID)
        self.assertIsInstance(data["context"], dict)
        self.assertTrue(data["context"])

    def test_fixture_offline_ttl_matches_domain(self):
        from accreditation import DEFAULT_OFFLINE_TTL_MINUTES

        data = json.loads(Path("fixtures/sample.json").read_text(encoding="utf-8"))
        self.assertEqual(
            data["context"]["offline_ttl_minutes"], DEFAULT_OFFLINE_TTL_MINUTES
        )


if __name__ == "__main__":
    unittest.main()
