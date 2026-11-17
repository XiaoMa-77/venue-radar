#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""server/app.py 集成测试（Flask test_client）。

覆盖：静态托管、API 返回结构、POST /api/sync 成功/失败/锁竞争路径。
同步子进程被 mock，不触发真实网络与 LLM 调用。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _helpers import load_flask, DATA_FILE as REAL_DATA_FILE


class TestStaticRoutes(unittest.TestCase):
    """静态页与数据文件可被正确托管。"""

    @classmethod
    def setUpClass(cls):
        cls.app = load_flask()
        cls.app.app.config["TESTING"] = True
        cls.client = cls.app.app.test_client()

    def test_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("投稿雷达", r.data.decode("utf-8"))

    def test_index_contains_mount_points(self):
        r = self.client.get("/")
        text = r.data.decode("utf-8")
        for needle in ("btn-sync", 'id="board"', "grad-rules", "SYNC_API"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_assets_served(self):
        for path in ("/assets/app.js", "/assets/style.css"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_data_file_served(self):
        self.assertEqual(self.client.get("/data/venues.json").status_code, 200)

    def test_missing_asset_404(self):
        self.assertEqual(self.client.get("/assets/no-such-file.js").status_code, 404)


class TestApiVenues(unittest.TestCase):
    """GET /api/venues：与 data/venues.json 同源。"""

    def setUp(self):
        app = load_flask()
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

    def test_matches_data_file(self):
        r = self.client.get("/api/venues")
        self.assertEqual(r.status_code, 200)
        payload = r.get_json()
        on_disk = json.loads(REAL_DATA_FILE.read_text(encoding="utf-8"))
        self.assertIn("meta", payload)
        self.assertIn("venues", payload)
        self.assertEqual(len(payload["venues"]), len(on_disk["venues"]))


class TestApiSync(unittest.TestCase):
    """POST /api/sync：成功、失败、锁竞争三条路径。"""

    def setUp(self):
        self.app = load_flask()
        self.app.app.config["TESTING"] = True
        self.client = self.app.app.test_client()
        self._tmp = tempfile.TemporaryDirectory()
        self.fake_data = Path(self._tmp.name) / "venues.json"
        self.payload = {
            "meta": {"syncedAt": "2026-11-17T00:00:00+08:00",
                     "syncLog": [{"changes": [{"id": "icaps-2027", "result": "update"}]}]},
            "venues": [],
        }
        self.fake_data.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        self._patch_data = mock.patch.object(self.app, "DATA_FILE", self.fake_data)
        self._patch_data.start()
        # 确保锁处于释放状态，避免用例间污染
        if self.app._sync_lock.locked():
            self.app._sync_lock.release()

    def tearDown(self):
        self._patch_data.stop()
        if self.app._sync_lock.locked():
            self.app._sync_lock.release()
        self._tmp.cleanup()

    def _completed(self, code=0, stdout="sync ok", stderr=""):
        return mock.Mock(returncode=code, stdout=stdout, stderr=stderr)

    def test_sync_success(self):
        with mock.patch.object(self.app.subprocess, "run", return_value=self._completed()) as run:
            r = self.client.post("/api/sync")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["changes"]), 1)
        self.assertIn("同步完成", body["message"])
        self.assertIn("data", body)
        run.assert_called_once()
        args = run.call_args[0][0]
        self.assertTrue(str(args[1]).endswith("sync.py"))

    def test_sync_failure_returns_500(self):
        with mock.patch.object(self.app.subprocess, "run",
                               return_value=self._completed(code=1, stdout="", stderr="boom")):
            r = self.client.post("/api/sync")
        self.assertEqual(r.status_code, 500)
        body = r.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("同步脚本异常", body["message"])
        self.assertIn("boom", body["message"])

    def test_sync_lock_busy_returns_429(self):
        # 模拟已有同步任务占用锁
        self.app._sync_lock.acquire(blocking=False)
        with mock.patch.object(self.app.subprocess, "run") as run:
            r = self.client.post("/api/sync")
        self.assertEqual(r.status_code, 429)
        self.assertFalse(r.get_json()["ok"])
        run.assert_not_called()

    def test_lock_released_after_sync(self):
        with mock.patch.object(self.app.subprocess, "run", return_value=self._completed()):
            self.client.post("/api/sync")
        self.assertFalse(self.app._sync_lock.locked(), "同步结束后锁应释放")

    def test_get_method_not_allowed(self):
        self.assertEqual(self.client.get("/api/sync").status_code, 405)


if __name__ == "__main__":
    unittest.main()
