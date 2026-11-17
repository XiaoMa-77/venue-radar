/* ============================================================
   投稿雷达 · 前端逻辑测试（Node 内置 test runner，零依赖）
   ------------------------------------------------------------
   app.js 是自执行 IIFE，无导出。这里用 vm 沙箱加载源码，在 IIFE 结束前
   注入一行把内部纯函数挂到 globalThis.__api，再配合最小 DOM stub 测试：
   状态计算、排序、筛选、转义、北京时间换算、卡片渲染与数据契约。
   所有时间通过固定 Date.now 控制，测试完全确定性。
   ============================================================ */
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..", "..");
const APP = fs.readFileSync(path.join(ROOT, "assets", "app.js"), "utf8");
const DATA = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "venues.json"), "utf8"));

const NOW = Date.parse("2026-11-17T00:00:00+08:00");
const isoIn = (days) => new Date(NOW + days * 86400000).toISOString();

/** 在沙箱中加载 app.js，返回内部 API 与 DOM stub。 */
function loadApp(options = {}) {
  const fixedNow = options.now == null ? NOW : options.now;
  const els = {};
  function makeEl() {
    return {
      innerHTML: "", textContent: "", className: "", value: "", checked: false,
      classList: { add() {}, remove() {} },
      addEventListener() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
      getAttribute() { return null; },
    };
  }
  const documentStub = {
    querySelector(sel) { return (els[sel] = els[sel] || makeEl()); },
    querySelectorAll() { return []; },
    addEventListener() { /* 不触发 init，避免 fetch */ },
  };
  const sandbox = {
    window: { SYNC_API: null },
    document: documentStub,
    localStorage: { getItem() { return null; }, setItem() {} },
    location: { protocol: "http:", href: "http://localhost/" },
    fetch() { return Promise.reject(new Error("no fetch in unit test")); },
    setInterval() { return 0; }, clearInterval() {}, setTimeout() { return 0; }, clearTimeout() {},
    console,
  };
  vm.createContext(sandbox);

  // 固定时间：只覆盖沙箱内的 Date.now，不污染宿主环境
  const preamble = "\n  Date.now = function () { return " + fixedNow + "; };\n";
  const withPreamble = APP.replace('"use strict";', '"use strict";' + preamble);
  const close = withPreamble.lastIndexOf("})();");
  assert.ok(close > 0, "app.js 应以 IIFE 结束");
  const exportLine =
    "\n  globalThis.__api = { state, esc, fmtBeijing, fmtDate, dayDiff, stars," +
    " statusOf, targetOf, sortKey, catOf, ddlRows, countdownHtml, cardHtml," +
    " statusSignature, render, renderStats, renderChips, CAT_DEFS };\n";
  const patched = withPreamble.slice(0, close) + exportLine + withPreamble.slice(close);
  vm.runInContext(patched, sandbox, { filename: "app.js" });

  return { api: sandbox.__api, els, sandbox };
}

function conf(override = {}) {
  return Object.assign({
    id: "test-conf", name: "TEST 2027", full: "Test Conference", type: "conference",
    ccf: "A", school: { level: "C", basis: "CCF-A → C 等" }, indexing: "EI",
    relevance: { rating: "高", tags: ["VLN", "GNN"] },
    ddl: {}, tz: "AoE（UTC−12）", confidence: "official", req: "双盲评审",
    links: { "官网": "https://example.org" }, verifiedAt: "2026-11-17",
  }, override);
}

/* ---------------------------------------------------------- 工具函数 */
test("esc 转义 HTML 特殊字符", () => {
  const { api } = loadApp();
  assert.equal(api.esc('<b a="x">&\'</b>'), "&lt;b a=&quot;x&quot;&gt;&amp;&#39;&lt;/b&gt;");
  assert.equal(api.esc(null), "");
  assert.equal(api.esc(undefined), "");
  assert.equal(api.esc(0), "0");
});

test("fmtBeijing 将带时区 ISO 换算为北京时间", () => {
  const { api } = loadApp();
  assert.equal(api.fmtBeijing("2026-12-15T11:59:59-05:00"), "2026-12-16 00:59");
  assert.equal(api.fmtBeijing("2026-12-15T23:59:59-12:00"), "2026-12-16 19:59");
  assert.equal(api.fmtBeijing("bad-date"), "");
});

test("fmtDate 输出 UTC 基准时间", () => {
  const { api } = loadApp();
  assert.equal(api.fmtDate("2026-12-15T11:59:59-05:00"), "2026-12-15 16:59");
});

test("dayDiff 返回距今天数（可正可负）", () => {
  const { api } = loadApp();
  assert.equal(api.dayDiff(NOW + 86400000), 1);
  assert.equal(api.dayDiff(NOW - 86400000 * 3), -3);
});

test("stars 映射相关度", () => {
  const { api } = loadApp();
  assert.equal(api.stars("高"), "★★★");
  assert.equal(api.stars("中"), "★★☆");
  assert.equal(api.stars("低"), "★☆☆");
  assert.equal(api.stars("未知"), "★☆☆");
});

/* ---------------------------------------------------------- 状态与目标 */
test("statusOf 覆盖五种状态", () => {
  const { api } = loadApp();
  assert.equal(api.statusOf(conf({ type: "journal" })).key, "rolling");
  assert.equal(api.statusOf(conf({ ddl: { full: isoIn(30) } })).key, "open");
  assert.equal(api.statusOf(conf({ ddl: { abstract: isoIn(5) } })).key, "soon");
  assert.equal(api.statusOf(conf({ ddl: { full: isoIn(-3) } })).key, "closed");
  assert.equal(api.statusOf(conf()).key, "tba");
  assert.deepEqual(api.statusOf(conf({ statusOverride: "自定义" })), "自定义");
});

test("targetOf 选择最近的未截止日期", () => {
  const { api } = loadApp();
  const v = conf({ ddl: {
    arr: isoIn(50), abstract: isoIn(20), full: isoIn(10), notify: isoIn(3),
  } });
  assert.equal(api.targetOf(v).k, "full", "notify 不参与目标选择");
  assert.equal(api.targetOf(conf({ type: "journal" })), null);
  assert.equal(api.targetOf(conf({ ddl: { full: isoIn(-1) } })), null);
});

test("targetOf 在摘要先于全文时选择摘要", () => {
  const { api } = loadApp();
  const v = conf({ ddl: { abstract: isoIn(7), full: isoIn(14) } });
  assert.equal(api.targetOf(v).k, "abstract");
});

test("sortKey 排序：期刊最后、开放按时间、无日期垫底", () => {
  const { api } = loadApp();
  const journal = api.sortKey(conf({ type: "journal" }));
  const open = api.sortKey(conf({ ddl: { full: isoIn(30) } }));
  const closed = api.sortKey(conf({ ddl: { full: isoIn(-5) } }));
  const tba = api.sortKey(conf());
  assert.equal(journal, Infinity);
  assert.ok(open < 1e13, "开放条目按绝对时间(~1.8e12)");
  // 源码：已截止 = -latest + 1e13（约 8.2e12），未开放 = 9e15
  assert.ok(closed > open && closed < 9e15, "已截止条目排在开放之后、未开放之前");
  assert.equal(tba, 9e15, "无日期条目最后");
});

test("catOf 分类正确", () => {
  const { api } = loadApp();
  assert.equal(api.catOf(conf({ type: "journal" })), "journal");
  assert.equal(api.catOf(conf({ ccf: "A" })), "ccf-a");
  assert.equal(api.catOf(conf({ ccf: "B" })), "ccf-b");
  assert.equal(api.catOf(conf({ ccf: "C" })), "ccf-c");
  assert.equal(api.catOf(conf({ ccf: null })), "nonccf");
});

/* ---------------------------------------------------------- 渲染 */
test("ddlRows 输出所有截稿行与北京时间", () => {
  const { api } = loadApp();
  const html = api.ddlRows(conf({ ddl: {
    abstract: isoIn(10), full: isoIn(20), notify: isoIn(-5),
  } }));
  assert.match(html, /摘要截稿/);
  assert.match(html, /全文截稿/);
  assert.match(html, /评审通知/);
  assert.match(html, /北京时间/);
  assert.match(html, /passed/, "过期日期应有 passed 样式");
  assert.match(html, /main/, "主目标应有 main 样式");
});

test("cardHtml 渲染徽章、状态、链接与投稿要求", () => {
  const { api } = loadApp();
  const html = api.cardHtml(conf({ ddl: { full: isoIn(20) } }), 0);
  assert.match(html, /TEST/);
  assert.match(html, /CCF-A/);
  assert.match(html, /学院 C 等/);
  assert.match(html, /st-open/);
  assert.match(html, /双盲评审/);
  assert.match(html, /官网/);
  assert.match(html, /✓ 官方/);
});

test("cardHtml 对即将截止加入 is-soon 与脉动点", () => {
  const { api } = loadApp();
  const html = api.cardHtml(conf({ ddl: { full: isoIn(3) } }), 0);
  assert.match(html, /is-soon/);
  assert.match(html, /st-soon/);
  assert.match(html, /距截稿/);
});

test("render 按分类/搜索/显示已截止筛选", () => {
  const { api, els } = loadApp();
  api.state.data = { meta: { graduation: { baseline: "x", rules: [] } }, venues: [
    conf({ id: "a", name: "AAA 2027", ccf: "A", ddl: { full: isoIn(30) } }),
    conf({ id: "b", name: "BBB 2027", ccf: "B", ddl: { full: isoIn(-2) } }),
    conf({ id: "j", name: "JJJ", type: "journal", ccf: null }),
  ] };

  api.state.cat = "all"; api.state.showClosed = false; api.state.q = "";
  api.render();
  assert.match(els["#board"].innerHTML, /AAA/);
  assert.doesNotMatch(els["#board"].innerHTML, /BBB/, "默认隐藏已截止");
  assert.match(els["#board"].innerHTML, /JJJ/);

  api.state.showClosed = true; api.render();
  assert.match(els["#board"].innerHTML, /BBB/);

  api.state.showClosed = false; api.state.cat = "ccf-b"; api.render();
  assert.match(els["#board"].innerHTML, /没有符合条件的条目/, "分类筛选下已截止仍隐藏");
  assert.doesNotMatch(els["#board"].innerHTML, /AAA/);

  api.state.showClosed = true; api.state.cat = "ccf-b"; api.render();
  assert.match(els["#board"].innerHTML, /BBB/, "打开显示已截止后 CCC-B 可见");
  assert.doesNotMatch(els["#board"].innerHTML, /AAA/);

  api.state.showClosed = true; api.state.cat = "all"; api.state.q = "jjj"; api.render();
  assert.match(els["#board"].innerHTML, /JJJ/);
  assert.doesNotMatch(els["#board"].innerHTML, /AAA/);

  api.state.q = "不存在的会议"; api.render();
  assert.match(els["#board"].innerHTML, /没有符合条件的条目/);
});

test("renderStats 统计四类状态", () => {
  const { api, els } = loadApp();
  api.state.data = { meta: {}, venues: [
    conf({ id: "s", ddl: { full: isoIn(3) } }),
    conf({ id: "o", ddl: { full: isoIn(30) } }),
    conf({ id: "c", ddl: { full: isoIn(-3) } }),
    conf({ id: "j", type: "journal" }),
    conf({ id: "t" }),
  ] };
  api.renderStats(api.state.data.venues);
  assert.match(els["#stats"].innerHTML, /即将截止（≤14天）/);
});

test("CAT_DEFS 分类集合完整", () => {
  const { api } = loadApp();
  assert.equal(JSON.stringify(api.CAT_DEFS.map((d) => d.key)),
    JSON.stringify(["all", "ccf-a", "ccf-b", "ccf-c", "nonccf", "journal"]));
});

/* ---------------------------------------------------------- 真实数据 */
test("真实数据 31 条均可渲染且状态计算不抛错", () => {
  const { api, els } = loadApp();
  api.state.data = DATA;
  api.state.cat = "all"; api.state.showClosed = true; api.state.q = "";
  assert.doesNotThrow(() => api.render());
  const cards = (els["#board"].innerHTML.match(/<article class=/g) || []).length;
  assert.equal(cards, DATA.venues.length);
});

test("statusSignature 随 DDL 越过而变化", () => {
  const a = loadApp({ now: NOW }).api;
  const b = loadApp({ now: NOW + 20 * 86400000 }).api;
  const v = conf({ id: "x", ddl: { full: isoIn(10) } });
  a.state.data = { venues: [v] };
  b.state.data = { venues: [v] };
  assert.notEqual(a.statusSignature(), b.statusSignature());
});
