/* ============================================================
   投稿雷达 Venue Radar · 前端逻辑
   ============================================================ */
(function () {
  "use strict";

  var state = {
    data: null,
    cat: "all",
    showClosed: false,
    q: "",
    tickTimer: null,
    syncApi: window.SYNC_API || null
  };

  var CAT_DEFS = [
    { key: "all",       label: "全部" },
    { key: "ccf-a",     label: "CCF-A" },
    { key: "ccf-b",     label: "CCF-B" },
    { key: "ccf-c",     label: "CCF-C" },
    { key: "nonccf",    label: "非CCF会议" },
    { key: "journal",   label: "期刊" }
  ];

  var DDL_LABELS = {
    abstract: "摘要截稿", full: "全文截稿", supp: "补充材料",
    notify: "评审通知", arr: "ARR 周期", commitment: "Commitment",
    stage2: "Stage-2（受邀）"
  };
  var DDL_ORDER = ["arr", "abstract", "full", "supp", "commitment", "stage2", "notify"];

  /* ---------- 工具 ---------- */
  function $(sel) { return document.querySelector(sel); }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function fmtBeijing(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    try {
      var parts = new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit",
        day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
      }).formatToParts(d);
      var map = {};
      parts.forEach(function (x) { map[x.type] = x.value; });
      return map.year + "-" + map.month + "-" + map.day + " " + map.hour + ":" + map.minute;
    } catch (e) {
      return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
        " " + p(d.getHours()) + ":" + p(d.getMinutes());
    }
  }
  function fmtDate(iso) {
    var d = new Date(iso);
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getUTCFullYear() + "-" + p(d.getUTCMonth() + 1) + "-" + p(d.getUTCDate()) +
      " " + p(d.getUTCHours()) + ":" + p(d.getUTCMinutes());
  }
  function dayDiff(t) { return (t - Date.now()) / 86400000; }

  function stars(rating) {
    if (rating === "高") return "★★★";
    if (rating === "中") return "★★☆";
    return "★☆☆";
  }

  /* ---------- 状态计算 ---------- */
  function statusOf(v) {
    if (v.type === "journal") return { key: "rolling", label: "滚动投稿" };
    if (v.statusOverride) return v.statusOverride;
    var t = targetOf(v);
    if (t) {
      var dd = dayDiff(t.t);
      if (dd <= 14) return { key: "soon", label: "即将截止" };
      return { key: "open", label: "投稿开放" };
    }
    var hasAny = v.ddl && DDL_ORDER.some(function (k) { return v.ddl[k]; });
    if (hasAny) return { key: "closed", label: "已截止" };
    return { key: "tba", label: "未开放" };
  }

  function targetOf(v) {
    if (v.type === "journal" || !v.ddl) return null;
    var best = null;
    ["arr", "abstract", "full"].forEach(function (k) {
      if (!v.ddl[k]) return;
      var t = new Date(v.ddl[k]).getTime();
      if (isNaN(t)) return;
      if (t > Date.now() && (best === null || t < best.t)) {
        best = { t: t, k: k, iso: v.ddl[k] };
      }
    });
    return best;
  }

  function sortKey(v) {
    if (v.type === "journal") return Infinity;
    var t = targetOf(v);
    if (t) return t.t;
    var latest = 0;
    DDL_ORDER.forEach(function (k) {
      if (v.ddl && v.ddl[k]) {
        var x = new Date(v.ddl[k]).getTime();
        if (!isNaN(x) && x > latest) latest = x;
      }
    });
    return latest ? -latest + 1e13 : 9e15; /* 已截止按最近在前；无日期最后 */
  }

  var STATUS_RANK = { soon: 0, open: 1, tba: 2, rolling: 3, closed: 4 };

  /* ---------- 渲染 ---------- */
  function catOf(v) {
    if (v.type === "journal") return "journal";
    if (v.ccf === "A") return "ccf-a";
    if (v.ccf === "B") return "ccf-b";
    if (v.ccf === "C") return "ccf-c";
    return "nonccf";
  }

  function confBadge(v) {
    if (v.type === "journal") {
      return v.ccf ? '<span class="badge b-ccf-' + v.ccf.toLowerCase() + '">CCF-' + v.ccf + " 刊</span>"
                   : '<span class="badge b-non">非 CCF 刊</span>';
    }
    if (v.ccf) return '<span class="badge b-ccf-' + v.ccf.toLowerCase() + '">CCF-' + v.ccf + "</span>";
    return '<span class="badge b-non">非 CCF</span>';
  }

  function schoolBadge(v) {
    if (!v.school || !v.school.level) return "";
    return '<span class="badge b-school b-lvl-' + v.school.level + '" title="' + esc(v.school.basis) + '">学院 ' + esc(v.school.level) + " 等</span>";
  }

  function confLabel(v) {
    if (v.confidence === "official") return '<b class="conf conf-official">✓ 官方</b>';
    if (v.confidence === "tracked") return '<b class="conf conf-tracked">≈ 追踪</b>';
    return '<b class="conf conf-estimated">~ 预估</b>';
  }

  function ddlRows(v) {
    if (v.type === "journal") return "";
    if (!v.ddl) return "";
    var main = targetOf(v);
    var html = "";
    DDL_ORDER.forEach(function (k) {
      var iso = v.ddl[k];
      if (!iso) return;
      var label = (v.ddlLabels && v.ddlLabels[k]) || DDL_LABELS[k] || k;
      var t = new Date(iso).getTime();
      var passed = !isNaN(t) && t <= Date.now();
      var isMain = main && main.k === k;
      html += '<div class="ddl-row' + (isMain ? " main" : "") + (passed ? " passed" : "") + '">' +
        '<span class="k">' + esc(label) + "</span>" +
        '<span class="v"><span class="d">' + fmtDate(iso) + "</span>" +
        '<span class="tz">' + esc(v.tz || "") + "</span>" +
        '<span class="beijing">北京时间 ' + fmtBeijing(iso) + "</span></span></div>";
    });
    if (!html) html = '<div class="ddl-row"><span class="k">截稿</span><span class="v"><span class="d">待官方公布</span></span></div>';
    return html;
  }

  function countdownHtml(v) {
    if (v.type === "journal") {
      var ji = v.journalInfo || {};
      return '<div class="countdown"><span class="cd-label">审稿节奏</span><span class="cd-value" style="font-size:12.5px;font-family:var(--font)">' +
        esc(ji.review || "以期刊官网为准") + "</span></div>";
    }
    var t = targetOf(v);
    if (!t) return "";
    var el = '<div class="countdown" data-iso="' + t.iso + '"><span class="cd-label">距截稿</span><span class="cd-value">…</span></div>';
    return el;
  }

  function updateCountdowns() {
    var nodes = document.querySelectorAll(".countdown[data-iso]");
    var now = Date.now();
    nodes.forEach(function (node) {
      var t = new Date(node.getAttribute("data-iso")).getTime();
      if (isNaN(t)) return;
      var ms = t - now;
      var el = node.querySelector(".cd-value");
      if (ms <= 0) {
        el.textContent = "已截止";
        return;
      }
      var d = Math.floor(ms / 86400000);
      var h = Math.floor(ms % 86400000 / 3600000);
      var m = Math.floor(ms % 3600000 / 60000);
      var s = Math.floor(ms % 60000 / 1000);
      var p = function (n) { return (n < 10 ? "0" : "") + n; };
      if (d >= 15) {
        el.innerHTML = d + '<span class="u">天</span>';
      } else {
        el.innerHTML = (d > 0 ? d + '<span class="u">天</span> ' : "") +
          p(h) + '<span class="u">时</span> ' + p(m) + '<span class="u">分</span> ' + p(s) + '<span class="u">秒</span>';
      }
    });
  }

  function cardHtml(v, i) {
    var st = statusOf(v);
    var cats = catOf(v);
    var cls = ["card", cats];
    if (st.key === "soon") cls.push("is-soon");
    if (st.key === "closed") cls.push("is-closed");
    if (v.type === "journal") cls.push("journal");

    var meta = "";
    if (v.type === "conference") {
      meta = '<div class="meta"><span>📅 ' + esc(v.when || "时间待官宣") + '</span><span class="dot">' + esc(v.where || "地点待官宣") + "</span></div>";
    } else {
      var ji = v.journalInfo || {};
      meta = '<div class="journal-facts">' +
        (ji.zone ? "<span>" + esc(ji.zone) + "</span>" : "") +
        (ji.jcr ? "<span>" + esc(ji.jcr) + "</span>" : "") +
        (ji.if ? "<span><b>" + esc(ji.if) + "</b></span>" : "") +
        (ji.review ? "<span>审稿：" + esc(ji.review) + "</span>" : "") + "</div>";
    }

    var rel = v.relevance || { rating: "中", tags: [] };
    var relHtml = '<div class="rel"><span class="stars" title="相关度">' + stars(rel.rating) + "</span>" +
      '<span class="tags">' + (rel.tags || []).map(function (t) {
        return '<span class="tag">' + esc(t) + "</span>";
      }).join("") + "</span></div>";

    var links = v.links || {};
    var linkHtml = Object.keys(links).map(function (k) {
      return '<a href="' + esc(links[k]) + '" target="_blank" rel="noopener">' + esc(k) + "</a>";
    }).join("");

    var ccfNote = v.ccfNote ? '<div class="note">⚑ ' + esc(v.ccfNote) + "</div>" : "";
    var note = v.note ? '<div class="note">' + esc(v.note) + "</div>" : "";

    return '<article class="' + cls.join(" ") + '" style="--i:' + i + '">' +
      '<div class="card-head"><div class="card-title">' +
      "<h3>" + esc(v.name.replace(/ \d{4}$/, "")) + ' <span class="yr">' + esc((v.name.match(/\d{4}$/) || [""])[0]) + "</span></h3>" +
      '<div class="full">' + esc(v.full) + "</div>" +
      '<div class="badges">' + confBadge(v) + schoolBadge(v) +
      (v.indexing ? '<span class="badge b-index">' + esc(v.indexing) + "</span>" : "") +
      "</div></div>" +
      '<span class="status st-' + st.key + '">' + esc(st.label) + "</span></div>" +
      meta +
      '<div class="ddl-box"><div class="ddl-rows">' + ddlRows(v) + "</div>" + countdownHtml(v) + "</div>" +
      relHtml +
      (ccfNote || note ? (ccfNote + note) : "") +
      (v.req ? '<details class="req"><summary>投稿要求摘要</summary><div class="req-text">' + esc(v.req) +
        (v.school ? "<br><b>毕业认定：</b>" + esc(v.school.basis) : "") + "</div></details>" : "") +
      '<div class="card-foot"><div class="card-links">' + linkHtml + "</div>" +
      "<div>" + confLabel(v) + ' <span class="verified">核验 ' + esc(v.verifiedAt || "—") + "</span></div></div>" +
      "</article>";
  }

  function render() {
    var venues = state.data.venues || [];
    var q = state.q.trim().toLowerCase();

    var visible = venues.filter(function (v) {
      var cat = catOf(v);
      if (state.cat !== "all" && cat !== state.cat) return false;
      var st = statusOf(v);
      if (!state.showClosed && st.key === "closed") return false;
      if (q) {
        var hay = [v.name, v.full, v.when, v.where,
          (v.relevance && v.relevance.tags || []).join(" "),
          v.ccf, v.school && v.school.level, v.note, v.full].join(" ").toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });

    visible.sort(function (a, b) {
      var ra = STATUS_RANK[statusOf(a).key], rb = STATUS_RANK[statusOf(b).key];
      if (ra !== rb) return ra - rb;
      return sortKey(a) - sortKey(b);
    });

    var board = $("#board");
    board.innerHTML = visible.length
      ? visible.map(function (v, i) { return cardHtml(v, i); }).join("")
      : '<div class="empty">没有符合条件的条目 —— 试试切换分类或打开「显示已截止」📎</div>';

    updateCountdowns();
    renderStats(venues);
    renderChips(venues);
    state._sig = statusSignature();
  }

  function renderStats(venues) {
    var c = { soon: 0, open: 0, rolling: 0, closed: 0 };
    venues.forEach(function (v) {
      var k = statusOf(v).key;
      if (c[k] !== undefined) c[k]++;
    });
    $("#stats").innerHTML =
      '<div class="stat urgent"><b>' + c.soon + "</b><span>即将截止（≤14天）</span></div>" +
      '<div class="stat open"><b>' + c.open + "</b><span>投稿开放</span></div>" +
      '<div class="stat rolling"><b>' + c.rolling + "</b><span>期刊滚动</span></div>" +
      '<div class="stat closed"><b>' + c.closed + "</b><span>本轮已截止</span></div>";
  }

  function renderChips(venues) {
    var counts = { all: venues.length };
    venues.forEach(function (v) {
      var c = catOf(v);
      counts[c] = (counts[c] || 0) + 1;
    });
    $("#cat-chips").innerHTML = CAT_DEFS.map(function (d) {
      return '<button class="chip' + (state.cat === d.key ? " active" : "") + '" data-cat="' + d.key + '" role="tab" ' +
        'aria-selected="' + (state.cat === d.key) + '">' + d.label +
        '<span class="n">' + (counts[d.key] || 0) + "</span></button>";
    }).join("");
  }

  function renderGradRules() {
    var g = state.data.meta.graduation;
    if (!g) return;
    $("#grad-rules").innerHTML =
      '<p class="baseline">' + esc(g.baseline) + "</p><ol>" +
      g.rules.map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("") + "</ol>";
  }

  function renderMeta() {
    var m = state.data.meta;
    var t = m.syncedAt || m.generatedAt;
    var d = t ? new Date(t) : null;
    $("#sync-time").textContent = d
      ? fmtBeijing(t).replace("T", " ")
      : "—";
    var g = m.generatedAt ? new Date(m.generatedAt) : null;
    $("#gen-time").textContent = g ? fmtBeijing(m.generatedAt) : "—";
  }

  /* ---------- 事件 ---------- */
  function bindEvents() {
    $("#cat-chips").addEventListener("click", function (e) {
      var btn = e.target.closest(".chip");
      if (!btn) return;
      state.cat = btn.getAttribute("data-cat");
      persist();
      render();
    });

    $("#chk-closed").addEventListener("change", function (e) {
      state.showClosed = e.target.checked;
      persist();
      render();
    });

    var deb;
    $("#search").addEventListener("input", function (e) {
      clearTimeout(deb);
      var val = e.target.value;
      deb = setTimeout(function () { state.q = val; render(); }, 160);
    });

    $("#btn-sync").addEventListener("click", syncNow);
  }

  function persist() {
    try {
      localStorage.setItem("vr-filter", JSON.stringify({
        cat: state.cat, showClosed: state.showClosed, q: state.q
      }));
    } catch (e) { /* ignore */ }
  }
  function restore() {
    try {
      var s = JSON.parse(localStorage.getItem("vr-filter") || "null");
      if (s) {
        state.cat = s.cat || "all";
        state.showClosed = !!s.showClosed;
        state.q = s.q || "";
        $("#search").value = state.q;
        $("#chk-closed").checked = state.showClosed;
      }
    } catch (e) { /* ignore */ }
  }

  /* ---------- 同步 ---------- */
  function toast(msg, isErr) {
    var el = $("#toast");
    el.textContent = msg;
    el.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.className = "toast"; }, 3200);
  }

  async function syncNow() {
    var btn = $("#btn-sync");
    btn.classList.add("loading");
    $(".btn-text", btn) && ($(".btn-text").textContent = "同步中…");
    try {
      if (state.syncApi) {
        var r = await fetch(state.syncApi, { method: "POST" });
        if (!r.ok) throw new Error("同步服务返回 " + r.status);
        var j = await r.json();
        if (j && j.data) state.data = j.data;
        var n = j && j.changes ? j.changes.length : 0;
        toast(j && j.message ? j.message : ("后台同步完成" + (n ? "，更新 " + n + " 条" : "，暂无变化")));
      }
      /* 无论是否有后端，都强制刷新静态数据（绕过缓存） */
      var res = await fetch("data/venues.json?t=" + Date.now(), { cache: "no-store" });
      if (!res.ok) throw new Error("数据文件返回 " + res.status);
      state.data = await res.json();
      render();
      renderMeta();
      if (!state.syncApi) toast("已重新拉取最新数据 · " + new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    } catch (err) {
      if (location.protocol === "file:") {
        toast("本地直开不支持 fetch，请用本地服务器预览（见 README）", true);
      } else {
        toast("更新失败：" + err.message, true);
      }
    } finally {
      btn.classList.remove("loading");
      var bt = btn.querySelector(".btn-text");
      if (bt) bt.textContent = "立即更新";
    }
  }

  async function probeSyncApi() {
    if (state.syncApi) return;
    try {
      var r = await fetch("api/venues", { method: "HEAD" });
      if (r.ok) state.syncApi = new URL("api/sync", location.href).pathname;
    } catch (e) { /* 静态部署，无后端 */ }
  }

  /* ---------- 启动 ---------- */
  async function init() {
    restore();
    bindEvents();
    try {
      var res = await fetch("data/venues.json", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      state.data = await res.json();
    } catch (e) {
      $("#board").innerHTML = '<div class="empty">数据加载失败：' + esc(e.message) +
        "<br>若以 file:// 直开本页，请通过本地服务器访问（python -m http.server）</div>";
      return;
    }
    renderGradRules();
    renderMeta();
    render();
    probeSyncApi();

    clearInterval(state.tickTimer);
    state.tickTimer = setInterval(updateCountdowns, 1000);
    /* 每分钟检查一次状态签名：仅当有条目跨越 DDL（状态/排序变化）时才重建列表，
       避免打断用户已展开的「投稿要求」等交互 */
    setInterval(function () {
      var sig = statusSignature();
      if (sig !== state._sig) render();
    }, 60000);
  }

  function statusSignature() {
    return (state.data.venues || []).map(function (v) {
      return v.id + ":" + statusOf(v).key + ":" + sortKey(v);
    }).join("|");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
