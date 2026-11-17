#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""server/sync.py 单元测试。

覆盖：.env 解析、时区换算、CCFDDL YAML 解析、合并规则（含 official 保护）、
LLM 抽取健壮性、日期合理性校验、fetch 文本清理。
全部用例均为离线测试：严格 mock 网络与 LLM，不消耗任何 token。
"""

import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _helpers import sync


class TestLoadEnv(unittest.TestCase):
    """load_env(): 解析 KEY=VALUE，忽略注释/空行，去引号。"""

    def _env(self, text):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text(text, encoding="utf-8")
            with mock.patch.object(sync, "__file__", str(Path(td) / "sync.py")):
                return sync.load_env()

    def test_parses_pairs_and_ignores_noise(self):
        cfg = self._env(
            "# 注释\n"
            "\n"
            'LLM_API_KEY="abc123"\n'
            "LLM_MODEL=MiniMax-M2\n"
            "NO_QUOTE =  spaced  \n"
            "BROKEN_LINE\n"
            "WITH_EQUALS=a=b=c\n"
        )
        self.assertEqual(cfg["LLM_API_KEY"], "abc123")
        self.assertEqual(cfg["LLM_MODEL"], "MiniMax-M2")
        self.assertEqual(cfg["NO_QUOTE"], "spaced")
        self.assertNotIn("BROKEN_LINE", cfg)
        self.assertEqual(cfg["WITH_EQUALS"], "a=b=c")

    def test_single_quotes_and_missing_file(self):
        self.assertEqual(self._env("K='v'\n")["K"], "v")
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(sync, "__file__", str(Path(td) / "sync.py")):
                self.assertEqual(sync.load_env(), {})


class TestIsoFrom(unittest.TestCase):
    """iso_from(): CCFDDL 的 deadline + timezone → ISO8601 带偏移。"""

    def test_known_timezones(self):
        cases = [
            ("2027-09-15 23:59:59", "UTC-8", "2027-09-15T23:59:59-08:00"),
            ("2027-09-15T23:59:59", "AoE", "2027-09-15T23:59:59-12:00"),
            ("2027-09-15 23:59:59", "PST", "2027-09-15T23:59:59-08:00"),
            ("2027-09-15 23:59:59", "SGT", "2027-09-15T23:59:59+08:00"),
            ("2027-09-15 23:59:59", "utc+9", "2027-09-15T23:59:59+09:00"),
            ("2027-09-15 23:59:59", "CET", "2027-09-15T23:59:59+01:00"),
        ]
        for deadline, tz, expected in cases:
            with self.subTest(deadline=deadline, tz=tz):
                self.assertEqual(sync.iso_from(deadline, tz), expected)

    def test_unknown_timezone_defaults_to_utc(self):
        self.assertEqual(
            sync.iso_from("2027-09-15 23:59:59", "MARS"),
            "2027-09-15T23:59:59+00:00",
        )

    def test_bad_deadline_returns_none(self):
        self.assertIsNone(sync.iso_from("not a date", "UTC"))
        self.assertIsNone(sync.iso_from(None, "UTC"))
        self.assertIsNone(sync.iso_from("", "UTC"))

    def test_utc_offset_regex_extracts_hours(self):
        self.assertEqual(
            sync.iso_from("2028-01-02 12:00:00", "UTC+13"),
            "2028-01-02T12:00:00+13:00",
        )


class TestParseCcfddlYaml(unittest.TestCase):
    """parse_ccfddl_yaml(): 轻量解析 CCFDDL 条目式 YAML。"""

    YAML = """\
- title: ICAPS 2027
  year: 2027
  deadline: '2026-12-14 23:59:59'
  timezone: AoE
  link: 'https://icaps27.org/'
  date: '2027-06-27 ~ 07-02'
  place: 'Columbia, SC, USA'
  note: some free text

- title: IJCAI 2027
  year: 2027
  deadline: "2027-01-20 23:59:59"
  timezone: UTC+8
  link: 'https://ijcai27.org/'

- title: NoYear 2027
  link: 'https://example.org/'
"""

    def test_extracts_fields(self):
        entries = sync.parse_ccfddl_yaml(self.YAML)
        self.assertEqual(len(entries), 2, "缺 year 的条目应被跳过")
        first = entries[0]
        self.assertEqual(first["title"], "ICAPS 2027")
        self.assertEqual(first["year"], 2027)
        self.assertEqual(first["deadline"], "2026-12-14 23:59:59")
        self.assertEqual(first["timezone"], "AoE")
        self.assertEqual(first["link"], "https://icaps27.org/")
        self.assertEqual(first["date"], "2027-06-27 ~ 07-02")
        self.assertEqual(first["place"], "Columbia, SC, USA")
        self.assertEqual(entries[1]["timezone"], "UTC+8")

    def test_empty_text(self):
        self.assertEqual(sync.parse_ccfddl_yaml(""), [])

    def test_real_nested_confs_format(self):
        """ccf-deadlines 实际采用 confs:/timeline: 嵌套，而非扁平字段。"""
        nested = """\
- title: ICAPS
  sub: AI
  confs:
    - year: 2026
      id: icaps26
      link: https://icaps26.icaps-conference.org/
      timeline:
        - abstract_deadline: '2025-12-02 23:59:59'
          deadline: '2025-12-08 23:59:59'
      timezone: UTC-12
      date: June 27 - July 2, 2026
      place: Dublin, Ireland
    - year: 2027
      id: icaps27
      link: https://icaps27.icaps-conference.org/
      timeline:
        - abstract_deadline: '2026-12-07 23:59:59'
          deadline: '2026-12-14 23:59:59'
      timezone: UTC-12
      date: June 27 - July 2, 2027
      place: Columbia, SC, USA
"""
        entries = sync.parse_ccfddl_yaml(nested)
        self.assertEqual(len(entries), 2)
        y2027 = next(e for e in entries if e["year"] == 2027)
        self.assertEqual(y2027["title"], "ICAPS")
        self.assertEqual(y2027["deadline"], "2026-12-14 23:59:59")
        self.assertEqual(y2027["timezone"], "UTC-12")
        self.assertEqual(y2027["link"], "https://icaps27.icaps-conference.org/")
        self.assertEqual(y2027["place"], "Columbia, SC, USA")
        self.assertEqual(entries[0]["year"], 2026)

    def test_nested_format_end_to_end_into_sync(self):
        """回归：真实嵌套格式应能在 sync_from_ccfddl 中被解析并更新条目。"""
        nested = """\
- title: ICAPS
  confs:
    - year: 2027
      link: https://icaps27.icaps-conference.org/
      timeline:
        - deadline: '2026-12-14 23:59:59'
      timezone: UTC-12
"""
        v = {"id": "icaps-2027", "name": "ICAPS 2027", "type": "conference",
             "confidence": "estimated", "ddl": {"full": "2026-01-01T23:59:59-12:00"}}
        log = []
        with mock.patch.object(sync, "http_get", return_value=nested):
            sync.sync_from_ccfddl([v], log)
        self.assertEqual(v["ddl"]["full"], "2026-12-14T23:59:59-12:00")
        self.assertEqual(log[0]["result"], "update")


class TestSaneDate(unittest.TestCase):
    """sane_date(): 拦截明显错误/越界的 LLM 输出。"""

    def test_valid_range(self):
        self.assertTrue(sync.sane_date("2027-05-01T23:59:59-12:00"))
        self.assertTrue(sync.sane_date("2029-12-31T23:59:59+08:00"))

    def test_out_of_range_or_malformed(self):
        for bad in (None, "", "2025-01-01T00:00:00+00:00",
                    "2030-01-01T00:00:00+00:00", "garbage", "2027-13-99T99:99:99+00:00"):
            with self.subTest(bad=bad):
                self.assertFalse(sync.sane_date(bad))


class TestSyncFromCcfddl(unittest.TestCase):
    """sync_from_ccfddl(): 合并规则与置信度保护。"""

    YAML = """\
- title: ICAPS 2027
  year: 2027
  deadline: '2026-12-14 23:59:59'
  timezone: AoE
  link: 'https://icaps27.org/'
"""

    def _venue(self, confidence="estimated", full="2026-01-01T23:59:59-12:00"):
        return {
            "id": "icaps-2027", "name": "ICAPS 2027", "type": "conference",
            "confidence": confidence, "ddl": {"full": full},
        }

    def _run(self, venue, yaml=YAML):
        log = []
        with mock.patch.object(sync, "http_get", return_value=yaml):
            sync.sync_from_ccfddl([venue], log)
        return log

    def test_estimated_updated_to_tracked(self):
        v = self._venue()
        log = self._run(v)
        self.assertEqual(v["ddl"]["full"], "2026-12-14T23:59:59-12:00")
        self.assertEqual(v["confidence"], "tracked")
        self.assertEqual(v["source"], "CCFDDL 同步")
        self.assertEqual(log[0]["result"], "update")
        self.assertEqual(log[0]["old"], "2026-01-01T23:59:59-12:00")

    def test_official_never_overwritten(self):
        v = self._venue(confidence="official", full="2026-11-01T23:59:59-12:00")
        log = self._run(v)
        self.assertEqual(v["ddl"]["full"], "2026-11-01T23:59:59-12:00",
                         "official 条目不得被 CCFDDL 覆盖")
        self.assertEqual(log[0]["result"], "conflict-kept-official")

    def test_same_deadline_promotes_estimated_to_tracked(self):
        v = self._venue(full="2026-12-14T23:59:59-12:00")
        log = self._run(v)
        self.assertEqual(v["confidence"], "tracked")
        self.assertEqual(log[0]["result"], "confirm")

    def test_no_matching_entry_logs_skip(self):
        v = self._venue()
        log = self._run(v, yaml="- title: OTHER\n  year: 2028\n  deadline: '2028-01-01 00:00:00'\n")
        self.assertEqual(log[0]["result"], "skip")

    def test_journal_and_unmapped_are_ignored(self):
        journal = {"id": "ral", "name": "IEEE RA-L", "type": "journal", "ddl": {}}
        unmapped = {"id": "unknown-2027", "name": "UNKNOWN 2027",
                    "type": "conference", "ddl": {}}
        log = []
        with mock.patch.object(sync, "http_get") as get:
            sync.sync_from_ccfddl([journal, unmapped], log)
        get.assert_not_called()
        self.assertEqual(log, [])

    def test_network_error_is_tolerated(self):
        v = self._venue()
        log = []
        with mock.patch.object(sync, "http_get", side_effect=OSError("offline")):
            sync.sync_from_ccfddl([v], log)
        self.assertEqual(log[0]["result"], "skip")
        self.assertEqual(v["confidence"], "estimated")


class TestFetchPageText(unittest.TestCase):
    """fetch_page_text(): 抓取失败返回 None；剥离标签、压缩空白、截断。"""

    def test_strips_tags_and_collapses_whitespace(self):
        html = "<html><script>x()</script><style>a{}</style><body>A&nbsp;B\n\n  C</body></html>"
        with mock.patch.object(sync, "http_get", return_value=html):
            text = sync.fetch_page_text("https://example.org/cfp")
        self.assertNotIn("<", text)
        self.assertNotIn("x()", text)
        self.assertIn("A B C", text)

    def test_fetch_failure_returns_none(self):
        with mock.patch.object(sync, "http_get", side_effect=OSError("timeout")):
            self.assertIsNone(sync.fetch_page_text("https://example.org"))

    def test_truncates_to_9000_chars(self):
        with mock.patch.object(sync, "http_get", return_value="x" * 20000):
            self.assertEqual(len(sync.fetch_page_text("https://example.org")), 9000)


class TestLlmExtract(unittest.TestCase):
    """llm_extract(): 无 key 跳过；容错 markdown 代码块；坏 JSON 返回 None。"""

    def _response(self, content):
        payload = json.dumps({"choices": [{"message": {"content": content}}]})
        cm = mock.MagicMock()
        cm.__enter__ = mock.Mock(return_value=io.BytesIO(payload.encode("utf-8")))
        cm.__exit__ = mock.Mock(return_value=False)
        return cm

    def test_no_api_key_returns_none(self):
        with mock.patch.object(sync, "LLM_API_KEY", ""):
            self.assertIsNone(sync.llm_extract("some text"))

    def test_extracts_json_from_markdown_fence(self):
        content = '```json\n{"full_ddl": "2027-05-01T23:59:59-12:00", "timezone_note": "AoE"}\n```'
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync.urllib.request, "urlopen", return_value=self._response(content)):
            out = sync.llm_extract("deadline: 2027-05-01 AoE")
        self.assertEqual(out["full_ddl"], "2027-05-01T23:59:59-12:00")
        self.assertEqual(out["timezone_note"], "AoE")

    def test_broken_json_returns_none(self):
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync.urllib.request, "urlopen",
                               return_value=self._response("{not valid json")):
            self.assertIsNone(sync.llm_extract("text"))

    def test_non_dict_json_returns_none(self):
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync.urllib.request, "urlopen",
                               return_value=self._response("[1,2,3]")):
            self.assertIsNone(sync.llm_extract("text"))

    def test_request_failure_returns_none(self):
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync.urllib.request, "urlopen", side_effect=OSError("network")):
            self.assertIsNone(sync.llm_extract("text"))


class TestSyncFromLlm(unittest.TestCase):
    """sync_from_llm(): 升级 official、跳过无日期、拒绝不合理日期。"""

    def _venue(self):
        return {
            "id": "icaps-2027", "name": "ICAPS 2027", "type": "conference",
            "confidence": "estimated", "ddl": {"full": "2026-01-01T23:59:59-12:00"},
            "links": {"CFP": "https://icaps27.org/cfp"},
        }

    def test_no_key_skips_all(self):
        v = self._venue()
        log = []
        with mock.patch.object(sync, "LLM_API_KEY", ""), \
             mock.patch.object(sync, "fetch_page_text") as fetch:
            sync.sync_from_llm([v], log)
        fetch.assert_not_called()
        self.assertEqual(log, [])

    def test_successful_extract_upgrades_to_official(self):
        v = self._venue()
        log = []
        obj = {"full_ddl": "2026-12-14T23:59:59-12:00",
               "abstract_ddl": "2026-12-07T23:59:59-12:00",
               "timezone_note": "AoE"}
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync, "fetch_page_text", return_value="page text"), \
             mock.patch.object(sync, "llm_extract", return_value=obj):
            sync.sync_from_llm([v], log)
        self.assertEqual(v["confidence"], "official")
        self.assertEqual(v["ddl"]["full"], obj["full_ddl"])
        self.assertEqual(v["ddl"]["abstract"], obj["abstract_ddl"])
        self.assertEqual(v["tz"], "AoE")
        self.assertEqual(log[0]["result"], "update")

    def test_no_dates_and_fetch_fail_logged(self):
        v = self._venue()
        log = []
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync, "fetch_page_text", return_value=None):
            sync.sync_from_llm([v], log)
        self.assertEqual(log[0]["result"], "fetch-fail")

        log = []
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync, "fetch_page_text", return_value="text"), \
             mock.patch.object(sync, "llm_extract", return_value={"none": True}):
            sync.sync_from_llm([v], log)
        self.assertEqual(log[0]["result"], "no-dates")

    def test_absurd_date_is_ignored(self):
        v = self._venue()
        log = []
        obj = {"full_ddl": "2010-01-01T00:00:00+00:00"}  # 越界
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync, "fetch_page_text", return_value="text"), \
             mock.patch.object(sync, "llm_extract", return_value=obj):
            sync.sync_from_llm([v], log)
        self.assertEqual(v["ddl"]["full"], "2026-01-01T23:59:59-12:00")
        self.assertEqual(log[0]["result"], "same")

    def test_journal_is_skipped(self):
        journal = {"id": "ral", "name": "IEEE RA-L", "type": "journal", "ddl": {}}
        log = []
        with mock.patch.object(sync, "LLM_API_KEY", "test-key"), \
             mock.patch.object(sync, "fetch_page_text") as fetch:
            sync.sync_from_llm([journal], log)
        fetch.assert_not_called()


class TestMainDryRun(unittest.TestCase):
    """main(): dry-run 不落盘；syncLog 结构正确。"""

    def test_dry_run_preserves_file(self):
        data = {"meta": {"syncedAt": "old", "syncLog": []}, "venues": []}
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "venues.json"
            target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(sync, "DATA_FILE", target), \
                 mock.patch.object(sync, "sync_from_ccfddl"), \
                 mock.patch.object(sync, "sync_from_llm"), \
                 mock.patch.object(sync.sys, "argv", ["sync.py", "--dry-run"]), \
                 mock.patch.object(sync, "LLM_API_KEY", ""), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                sync.main()
            self.assertIn("dry-run，未落盘", out.getvalue())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["meta"]["syncedAt"], "old")

    def test_normal_run_writes_sync_log(self):
        data = {"meta": {"syncedAt": "old", "syncLog": []}, "venues": []}
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "venues.json"
            target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(sync, "DATA_FILE", target), \
                 mock.patch.object(sync, "sync_from_ccfddl"), \
                 mock.patch.object(sync, "sync_from_llm"), \
                 mock.patch.object(sync.sys, "argv", ["sync.py"]), \
                 mock.patch.object(sync, "LLM_API_KEY", ""), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                sync.main()
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertNotEqual(written["meta"]["syncedAt"], "old")
            self.assertEqual(len(written["meta"]["syncLog"]), 1)
            self.assertIn("time", written["meta"]["syncLog"][0])
            self.assertIn("changes", written["meta"]["syncLog"][0])


if __name__ == "__main__":
    unittest.main()
