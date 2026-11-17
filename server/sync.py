#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
venue-radar 同步引擎
====================
数据来源与优先级：
  1) MiniMax（OpenAI 兼容接口，需在 server/.env 配置 LLM_API_KEY）
     —— 抓取各会议官网 CFP/Dates 页面正文，调用模型抽取最新 DDL，置信度=官方
  2) CCFDDL（github.com/ccfddl/ccf-deadlines 原始 YAML）
     —— 结构化 DDL 数据库，置信度=追踪
  3) 本地 data/venues.json 已有数据
     —— 人工核验基线

合并规则：
  * official 条目仅允许「官网抽取成功」更新（保持 official）；
  * tracked/estimated 条目可被 CCFDDL（→tracked）或官网抽取（→official）覆盖；
  * 官网抽取 > CCFDDL > 既有数据；
  * 所有变更写入 meta.syncLog，便于回溯。

用法：
  python server/sync.py            # 全量同步
  python server/sync.py --dry-run  # 只看会改什么，不落盘
"""

import json
import re
import sys
import datetime
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "venues.json"

# ---------------------------------------------------------------- .env 解析
def load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    cfg = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg

ENV = load_env()
LLM_BASE_URL = ENV.get("LLM_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
LLM_API_KEY = ENV.get("LLM_API_KEY", "")
LLM_MODEL = ENV.get("LLM_MODEL", "MiniMax-M2")

# ---------------------------------------------------------------- HTTP
def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (venue-radar-sync/1.0) academic-deadline-tracker"
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

# ---------------------------------------------------------------- CCFDDL
# 候选路径按 CCFDDL 仓库可能的分类目录逐一尝试（会议未收录时自动跳过）
CCFDDL_MAP = {
    "icaps-2027":    ["AI/icaps"],
    "ijcai-2027":    ["AI/ijcai"],
    "icml-2027":     ["AI/icml"],
    "icra-2028":     ["AI/icra", "ROBOT/icra"],
    "iros-2027":     ["AI/iros", "ROBOT/iros"],
    "iccv-2027":     ["CV/iccv", "AI/iccv", "MM/iccv"],
    "acmmm-2027":    ["MM/acmmm", "AI/acmmm"],
    "corl-2027":     ["ROBOT/corl", "AI/corl"],
    "neurips-2027":  ["AI/neurips"],
    "aaai-2028":     ["AI/aaai"],
    "iclr-2028":     ["AI/iclr"],
    "aamas-2028":    ["AI/aamas"],
    "cvpr-2028":     ["CV/cvpr", "AI/cvpr"],
    "eccv-2028":     ["CV/eccv", "AI/eccv"],
    "emnlp-2027":    ["NLP/emnlp", "AI/emnlp"],
    "acl-2027":      ["NLP/acl", "AI/acl"],
    "naacl-2027":    ["NLP/naacl", "AI/naacl"],
    "rss-2027":      ["ROBOT/rss", "AI/rss"],
}

TZ_MAP = {
    "aoe": "-12:00", "utc-12": "-12:00",
    "utc-11": "-11:00", "utc-10": "-10:00",
    "pst": "-08:00", "utc-8": "-08:00",
    "pdt": "-07:00", "utc-7": "-07:00",
    "mst": "-07:00", "utc-6": "-06:00", "cst": "-06:00",
    "est": "-05:00", "utc-5": "-05:00",
    "utc": "+00:00", "utc+0": "+00:00",
    "cet": "+01:00", "utc+1": "+01:00",
    "sgt": "+08:00", "utc+8": "+08:00", "cst+8": "+08:00",
    "jst": "+09:00", "utc+9": "+09:00",
}

def iso_from(deadline_str, tz_str):
    """把 CCFDDL 的 '2027-09-15 23:59:59' + 'UTC-8' 转成 ISO 带偏移字符串"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", deadline_str or "")
    if not m:
        return None
    tz = (tz_str or "").strip().lower().replace(" ", "")
    offset = TZ_MAP.get(tz, "-12:00" if "aoe" in tz else None)
    if offset is None:
        num = re.search(r"utc([+-])(\d+)", tz)
        offset = (num.group(1) + "%02d:00" % int(num.group(2))) if num else "+00:00"
    return "{0}-{1}-{2}T{3}:{4}:{5}{6}".format(*m.groups(), offset)

def parse_ccfddl_yaml(text):
    """轻量解析 CCFDDL YAML（条目式，字段规整，用正则足够）。

    兼容两种布局：
      1) 新版嵌套（ccf-deadlines 实际格式）：
           - title: ICAPS
             confs:
               - year: 2027
                 link: https://...
                 timeline:
                   - abstract_deadline: '2026-12-07 23:59:59'
                     deadline: '2026-12-14 23:59:59'
                 timezone: UTC-12
      2) 旧版扁平：
           - title: ICAPS 2027
             year: 2027
             deadline: '2026-12-14 23:59:59'
    """
    def field(block, name):
        # 允许可选的前导 "- "：顶层 title 为 "- title:"，嵌套年份为 "- year:"
        m = re.search(r"^\s*(?:-\s+)?%s:\s*[\"']?(.*?)[\"']?\s*$" % re.escape(name), block, re.M)
        return m.group(1).strip() if m else None

    entries = []
    for top in re.split(r"\n(?=-\s+title:)", text):
        title = field(top, "title")
        if not title:
            continue
        # 新版：confs: 下按年份拆块；旧版：整块即一年
        confs_pos = re.search(r"^\s*confs:\s*$", top, re.M)
        blocks = (re.split(r"\n(?=\s+-\s+year:)", top[confs_pos.end():])
                  if confs_pos else [top])
        for block in blocks:
            year = field(block, "year")
            if not year or not year.isdigit():
                continue
            entries.append({
                "title": title, "year": int(year),
                "deadline": field(block, "deadline"),
                "timezone": field(block, "timezone"),
                "link": field(block, "link"),
                "date": field(block, "date"),
                "place": field(block, "place"),
            })
    return entries

def sync_from_ccfddl(venues, log):
    raw_base = "https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference/{}.yml"
    for v in venues:
        vid = v.get("id")
        if v.get("type") != "conference" or vid not in CCFDDL_MAP:
            continue
        want_year = int(re.search(r"(\d{4})", v["name"]).group(1))
        found = None
        for path in CCFDDL_MAP[vid]:
            try:
                text = http_get(raw_base.format(path), timeout=15)
                entries = parse_ccfddl_yaml(text)
                found = next((e for e in entries if e["year"] == want_year), None)
                if found:
                    break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
                continue
        if not found or not found.get("deadline"):
            log.append({"id": vid, "src": "ccfddl", "result": "skip", "why": "no matching entry"})
            continue
        new_iso = iso_from(found["deadline"], found.get("timezone"))
        if not new_iso:
            continue
        cur = (v.get("ddl") or {}).get("full")
        if cur == new_iso:
            if v.get("confidence") == "estimated":
                v["confidence"] = "tracked"
                v["source"] = "CCFDDL（与预估一致，升为追踪）"
                log.append({"id": vid, "src": "ccfddl", "result": "confirm", "ddl": new_iso})
            else:
                log.append({"id": vid, "src": "ccfddl", "result": "same"})
            continue
        if v.get("confidence") == "official":
            log.append({"id": vid, "src": "ccfddl", "result": "conflict-kept-official",
                        "ours": cur, "ccfddl": new_iso})
            continue
        v.setdefault("ddl", {})
        v["ddl"]["full"] = new_iso
        v["tz"] = "CCFDDL 记录（{}）".format(found.get("timezone") or "?")
        v["confidence"] = "tracked"
        v["source"] = "CCFDDL 同步"
        v["verifiedAt"] = datetime.date.today().isoformat()
        log.append({"id": vid, "src": "ccfddl", "result": "update", "old": cur, "new": new_iso})

# ---------------------------------------------------------------- LLM 抽取
EXTRACT_PROMPT = """你是学术会议信息抽取助手。下面是某学术会议官网页面（可能是 CFP 或 Dates 页）的正文。
请从中抽取投稿关键日期，输出一个紧凑的 JSON 对象（不要 markdown 代码块、不要多余文字）：
{
 "abstract_ddl": "YYYY-MM-DDTHH:MM:SS+XX:XX 或 null",
 "full_ddl":     "YYYY-MM-DDTHH:MM:SS+XX:XX 或 null",
 "notify":       "YYYY-MM-DDTHH:MM:SS+XX:XX 或 null",
 "timezone_note":"页面上声明的时区（如 AoE / UTC-12 / 23:59 PDT），无则 null",
 "conf_when":    "会议时间，无则 null",
 "conf_where":   "会议地点，无则 null"
}
规则：
- 时区偏移未知时：AoE 用 -12:00；只写日期没写时刻的用 23:59:59 并沿用页面时区，无时区信息用 -12:00；
- 只抽取「论文投稿」相关日期，忽略 workshop/注册/visa 等其它日期；
- 页面上确实没有的信息一律 null，严禁编造；
- 若页面根本没有投稿日期信息，输出 {"none": true}。

页面正文：
"""

HTML_STRIP = re.compile(r"<(script|style)[\s\S]*?</\1>|<[^>]+>", re.I)

def fetch_page_text(url):
    try:
        html = http_get(url, timeout=20)
    except Exception:
        return None
    text = HTML_STRIP.sub(" ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:9000]

def llm_extract(page_text):
    """调用 OpenAI 兼容接口做信息抽取，返回 dict 或 None"""
    if not LLM_API_KEY:
        return None
    payload = json.dumps({
        "model": LLM_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system",
             "content": "你只输出 JSON，不输出任何其它内容。"},
            {"role": "user",
             "content": EXTRACT_PROMPT + page_text},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        LLM_BASE_URL + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + LLM_API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        content = out["choices"][0]["message"]["content"]
    except Exception as e:
        print("  [llm] 调用失败: %s" % e)
        return None
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None

def sane_date(iso):
    if not iso:
        return False
    try:
        d = datetime.datetime.fromisoformat(iso)
        return datetime.date(2026, 1, 1) <= d.date() <= datetime.date(2029, 12, 31)
    except ValueError:
        return False

def sync_from_llm(venues, log):
    if not LLM_API_KEY:
        print("[sync] 未配置 LLM_API_KEY，跳过官网抽取（仅 CCFDDL 同步）")
        return
    print("[sync] 使用模型 %s @ %s 进行官网抽取" % (LLM_MODEL, LLM_BASE_URL))
    for v in venues:
        if v.get("type") != "conference":
            continue
        links = v.get("links") or {}
        url = links.get("CFP") or links.get("关键日期") or links.get("Dates") or links.get("官网")
        if not url:
            continue
        print("  [llm] %s <- %s" % (v["id"], url))
        text = fetch_page_text(url)
        if not text:
            log.append({"id": v["id"], "src": "llm", "result": "fetch-fail"})
            continue
        obj = llm_extract(text)
        if not obj or obj.get("none"):
            log.append({"id": v["id"], "src": "llm", "result": "no-dates"})
            continue
        changed = False
        ddl = v.setdefault("ddl", {})
        for key, field in (("abstract_ddl", "abstract"), ("full_ddl", "full"), ("notify", "notify")):
            iso = obj.get(key)
            if sane_date(iso):
                if ddl.get(field) != iso:
                    ddl[field] = iso
                    changed = True
        if changed:
            v["confidence"] = "official"
            v["source"] = "模型抽取自官网：%s" % url
            v["verifiedAt"] = datetime.date.today().isoformat()
            if obj.get("timezone_note"):
                v["tz"] = str(obj["timezone_note"])
            log.append({"id": v["id"], "src": "llm", "result": "update",
                        "ddl": {k: obj.get(k) for k in ("abstract_ddl", "full_ddl", "notify")}})
        else:
            log.append({"id": v["id"], "src": "llm", "result": "same"})

# ---------------------------------------------------------------- 主流程
def main():
    dry = "--dry-run" in sys.argv
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    venues = data.get("venues", [])
    log = []

    print("[sync] 共 %d 个条目" % len(venues))
    sync_from_ccfddl(venues, log)
    sync_from_llm(venues, log)

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    data["meta"]["syncedAt"] = now
    data["meta"]["syncLog"] = (data["meta"].get("syncLog") or [])[-49:] + [{
        "time": now,
        "llm": bool(LLM_API_KEY),
        "changes": [c for c in log if c.get("result") in ("update", "confirm", "conflict-kept-official")],
        "raw": log,
    }]

    n_changed = len([c for c in log if c.get("result") == "update"])
    print("[sync] 完成：更新 %d 条，其余 %d 条无变化/跳过" % (n_changed, len(log) - n_changed))
    for c in log:
        if c.get("result") in ("update", "conflict-kept-official"):
            print("   *", json.dumps(c, ensure_ascii=False))

    if not dry:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[sync] 已写回 %s" % DATA_FILE)
    else:
        print("[sync] dry-run，未落盘")

if __name__ == "__main__":
    main()
