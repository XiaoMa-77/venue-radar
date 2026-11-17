#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data/venues.json 数据契约与一致性校验。

这是「硬数据」的守门测试：确保 31 个条目的字段齐全、枚举合法、
DDL 全部为带时区的 ISO8601、链接可点击、置信度与毕业映射自洽。
"""

import re
import unittest
from datetime import datetime

from _helpers import DATA_FILE, load

# 直接读文件，避免同步引擎在 import 时读到真实 .env
import json

DATA = json.loads(DATA_FILE.read_text(encoding="utf-8"))
VENUES = DATA.get("venues", [])
META = DATA.get("meta", {})

VENUE_KEYS = {"id", "name", "full", "type", "ccf", "school", "indexing",
              "relevance", "tz", "confidence", "req", "links",
              "verifiedAt", "source"}
# ddl 仅会议需要；期刊为滚动投稿，不设固定截稿（ECCV-2028 等未官宣会议的 ddl 值为 None 占位）
DDL_KEYS = {"arr", "abstract", "full", "supp", "commitment", "stage2", "notify"}
TYPES = {"conference", "journal"}
CCF_LEVELS = {None, "A", "B", "C"}
CONFIDENCE = {"official", "tracked", "estimated"}
SCHOOL_LEVELS = {"A", "B", "C", "D", "E"}
RATINGS = {"高", "中", "低"}
INDEXING = {"EI", "SCIE", "SCIE + EI"}

ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TestDataIntegrity(unittest.TestCase):
    """顶层结构与全局不变量。"""

    def test_top_level_keys(self):
        for key in ("meta", "venues"):
            self.assertIn(key, DATA)

    def test_meta_required_fields(self):
        for key in ("title", "subtitle", "generatedAt", "ccfEdition", "graduation"):
            self.assertIn(key, META)
        self.assertIn("baseline", META["graduation"])
        self.assertIsInstance(META["graduation"]["rules"], list)

    def test_venue_count(self):
        self.assertEqual(len(VENUES), 31, "当前应收录 31 个会议/期刊条目")

    def test_unique_ids(self):
        ids = [v["id"] for v in VENUES]
        self.assertEqual(len(ids), len(set(ids)), "id 必须唯一")

    def test_type_distribution(self):
        confs = [v for v in VENUES if v["type"] == "conference"]
        journals = [v for v in VENUES if v["type"] == "journal"]
        self.assertEqual(len(confs) + len(journals), len(VENUES))
        self.assertGreater(len(confs), 0)
        self.assertGreater(len(journals), 0)


class TestVenueSchema(unittest.TestCase):
    """逐条校验字段类型、枚举与格式。"""

    def test_required_keys(self):
        for v in VENUES:
            with self.subTest(id=v.get("id")):
                missing = VENUE_KEYS - set(v.keys())
                self.assertFalse(missing, "缺少字段: %s" % sorted(missing))

    def test_enums(self):
        for v in VENUES:
            with self.subTest(id=v["id"]):
                self.assertIn(v["type"], TYPES)
                self.assertIn(v["ccf"], CCF_LEVELS)
                self.assertIn(v["confidence"], CONFIDENCE)
                self.assertIn(v["indexing"], INDEXING)
                self.assertIn(v["school"]["level"], SCHOOL_LEVELS)
                self.assertIn(v["relevance"]["rating"], RATINGS)

    def test_id_format(self):
        for v in VENUES:
            with self.subTest(id=v["id"]):
                self.assertRegex(v["id"], r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_ddl_is_iso_with_timezone(self):
        checked = 0
        for v in VENUES:
            for key, iso in (v.get("ddl") or {}).items():
                with self.subTest(id=v["id"], key=key, iso=iso):
                    self.assertIn(key, DDL_KEYS)
                    # 数据中存在少量待官宣占位值（null），显式允许
                    if iso is None:
                        continue
                    self.assertIsInstance(iso, str)
                    self.assertTrue(ISO_RE.match(iso), "非 ISO8601 带偏移: %s" % iso)
                    parsed = datetime.fromisoformat(iso)
                    self.assertIsNotNone(parsed.tzinfo, "缺少时区偏移: %s" % iso)
                    self.assertTrue(2026 <= parsed.year <= 2030, "年份越界: %s" % iso)
                    checked += 1
        self.assertGreater(checked, 20, "应至少有 20 个有效 DDL 时间")

    def test_conferences_have_reasonable_ddl(self):
        for v in VENUES:
            if v["type"] != "conference":
                continue
            with self.subTest(id=v["id"]):
                ddl = v.get("ddl") or {}
                self.assertIn("ddl", v, "会议条目应含 ddl 字段（可为 null 占位）")
                # 未官宣的预估条目（如 ECCV-2028）允许全 null 占位
                if v["confidence"] == "estimated" and not any(ddl.values()):
                    continue
                self.assertTrue(any(ddl.get(k) for k in ("abstract", "full", "arr")),
                                "会议应有摘要/全文/ARR 截稿日期（未官宣请标注 estimated + null）")

    def test_journals_are_rolling(self):
        for v in VENUES:
            if v["type"] != "journal":
                continue
            with self.subTest(id=v["id"]):
                self.assertIn("journalInfo", v)
                for k in ("zone", "jcr", "if", "review"):
                    self.assertIn(k, v["journalInfo"])

    def test_links_are_https(self):
        for v in VENUES:
            with self.subTest(id=v["id"]):
                links = v.get("links") or {}
                self.assertGreater(len(links), 0, "至少应有一个官网/CFP 链接")
                for label, url in links.items():
                    self.assertTrue(isinstance(url, str) and url.startswith("https://"),
                                    "%s -> %s 不是 https 链接" % (label, url))

    def test_verified_at_format(self):
        for v in VENUES:
            with self.subTest(id=v["id"]):
                self.assertTrue(DATE_RE.match(v["verifiedAt"]))
                datetime.strptime(v["verifiedAt"], "%Y-%m-%d")

    def test_school_basis_nonempty(self):
        for v in VENUES:
            with self.subTest(id=v["id"]):
                self.assertTrue(v["school"]["basis"].strip())
                self.assertTrue(v["full"].strip())
                self.assertTrue(v["req"].strip())

    def test_relevance_tags(self):
        for v in VENUES:
            with self.subTest(id=v["id"]):
                self.assertIsInstance(v["relevance"]["tags"], list)
                self.assertGreater(len(v["relevance"]["tags"]), 0)


class TestSyncConfig(unittest.TestCase):
    """同步相关配置与 CCFDDL 映射表的一致性。"""

    def test_env_example_has_required_keys(self):
        env = (DATA_FILE.parent.parent / "server" / ".env.example").read_text(encoding="utf-8")
        for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
            self.assertIn(key + "=", env)

    def test_ccfddl_map_ids_exist(self):
        module = load("venue_radar_sync_for_data_test", "server/sync.py")
        ids = {v["id"] for v in VENUES}
        for vid in module.CCFDDL_MAP:
            self.assertIn(vid, ids, "CCFDDL_MAP 中的 %s 不在数据集里" % vid)

    def test_requirements_declared(self):
        req = (DATA_FILE.parent.parent / "server" / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("flask", req.lower())
        self.assertIn("requests", req.lower())


if __name__ == "__main__":
    unittest.main()
