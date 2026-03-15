"""API 路由注册测试。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from main import app


class ApiRoutesTestCase(unittest.TestCase):
    """验证模块前缀路由是否全部注册。"""

    def test_module_prefixed_routes_registered(self) -> None:
        expected_paths = {
            "/user/settings",
            "/user/employees",
            "/user/employees/{employee_id}",
            "/user/employees/{employee_id}/reset",
            "/user/employee-messages",
            "/chat/stream",
            "/chat/memory/status",
            "/chat/memory/flush",
            "/storage/tree",
            "/storage/file-content",
            "/storage/file-preview",
            "/storage/file",
            "/storage/brand-library/upload",
        }

        with TestClient(app) as client:
            openapi = client.get("/openapi.json")
            self.assertEqual(200, openapi.status_code)
            paths = set((openapi.json() or {}).get("paths", {}).keys())

        self.assertTrue(expected_paths.issubset(paths))
        # 明确不再使用 /users/{user_id} 前缀路由。
        self.assertFalse(any(path.startswith("/users/") for path in paths))


if __name__ == "__main__":
    unittest.main()
