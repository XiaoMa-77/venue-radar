# 📐 投稿雷达 · 设计文档

> 版本：v1.1 · 更新：2026-11-17
> 本文描述 `venue-radar` 的设计背景、架构、接口、数据流与边界/异常场景。
> 事实性内容（会议日期、CCF 分级、学院认定）以 `data/venues.json` 内 `source` / `verifiedAt` 为准；
> 无法从官方文件确认的部分在文末「假设与待确认」中显式列出。

---

## 1. 背景与目标

### 1.1 问题

计算机科学与技术学术型硕士（方向：VLN / 多目标导航 / GNN / MAPF）在投稿时面临三类信息分散：

1. **投哪里**：哪些会议/期刊与方向对口、录用是否算毕业成果；
2. **算几等**：学院对成果等级（A–E）与 CCF / SCIE 分区的映射规则；
3. **何时截止**：各会议摘要/全文/通知 DDL，精确到时刻与时区（AoE / UTC-x / PDT 差异易致错过）。

这些信息散落在官网 CFP、CCF 目录、学院文件、第三方 DDL 站，人工维护成本高且易过期。

### 1.2 目标

- **集中化**：一页展示 31 个会议/期刊的名称、级别、相关性、要求摘要、官网链接、DDL、北京时间换算、置信度与核验时间。
- **可行动**：实时倒计时、临近截止脉动提醒、分类/搜索/显示已截止筛选、手机端可用。
- **可持续**：一键更新 + 每日自动同步；数据来源分级，变更可回溯。
- **可验证**：数据契约、同步合并规则、前端渲染逻辑均有自动化测试守门。

### 1.3 非目标

- 不做账号系统、不做投稿流程管理、不替代官网 CFP 的权威性；
- 不保证第三方数据 100% 准确 —— 页面与 README 均声明投稿前以官网为准。

---

## 2. 总体架构

系统采用「静态前端 + 唯一数据文件 + 可选后端 + 定时同步」的分层结构：

```
┌──────────────────────────── 数据源 ────────────────────────────┐
│  会议官网 CFP/Dates  │  CCFDDL GitHub YAML  │  人工核验基线     │
└──────────┬──────────────────┬──────────────────┬───────────────┘
           │ 抓取             │ 抓取             │ 编辑
           v                 v                 v
      ┌──────────────────────────────────────────────┐
      │  server/sync.py  同步引擎（标准库）          │
      │  · fetch_page_text + llm_extract（官网）     │
      │  · parse_ccfddl_yaml（CCFDDL）               │
      │  · 合并规则 + 置信度保护 + syncLog 记录      │
      └────────────────────┬─────────────────────────┘
                           │ 读写
                           v
                 ┌──────────────────────┐
                 │  data/venues.json    │  ← 唯一数据源（Single Source of Truth）
                 │  meta + venues[31]   │
                 └──────────┬───────────┘
                            │
        ┌───────────────────┼────────────────────┐
        │                   │                    │
        v                   v                    v
  ┌──────────┐       ┌─────────────┐      ┌──────────────┐
  │ index.html│       │ server/app.py│      │ GitHub Actions│
  │ + app.js  │       │ Flask 后端   │      │ 每日 09:00    │
  │ + style   │       │ /api/*       │      │ 定时同步      │
  └────┬──────┘       └──────┬──────┘      └──────────────┘
       │ fetch                │ POST /api/sync
       v                      v
   用户浏览器 ←──── 静态托管 / Caddy 反代 ──── 云服务器
```

### 2.1 模块职责

| 模块 | 文件 | 职责 |
|---|---|---|
| 前端单页 | `index.html` | 页面骨架、筛选/搜索/更新按钮、统计与卡片挂载点 |
| 前端样式 | `assets/style.css` | 纸感手帐 × 现代简约视觉、响应式、动画与脉动提醒 |
| 前端逻辑 | `assets/app.js` | 数据加载、状态计算、排序筛选、倒计时、更新按钮、北京时间换算 |
| 唯一数据源 | `data/venues.json` | 31 条结构化条目 + meta（毕业规则、CCF 版本、同步日志） |
| 同步引擎 | `server/sync.py` | CCFDDL / 官网抽取 → 合并 → 写回，置信度保护 |
| 可选后端 | `server/app.py` | 静态托管 + `GET /api/venues` + `POST /api/sync` |
| 定时同步 | `.github/workflows/sync.yml` | 每日 UTC 01:00（北京 09:00）跑同步并提交 |
| CI | `.github/workflows/ci.yml` | push/PR 时跑全套测试 |
| 校验脚本 | `scripts/verify.sh` | 本地一键运行全部检查 |

---

## 3. 数据模型

### 3.1 `data/venues.json` 顶层结构

```json
{
  "meta": {
    "title": "投稿雷达",
    "subtitle": "...",
    "profile": "...",
    "generatedAt": "2026-11-17T22:55:00+08:00",
    "syncedAt": "2026-11-17T23:55:18+08:00",
    "syncLog": [],
    "ccfEdition": "CCF 目录按第七版（2026-03 发布）...",
    "disclaimer": "...",
    "graduation": { "baseline": "...", "rules": [] }
  },
  "venues": [ /* 31 条 */ ]
}
```

### 3.2 venue 字段契约

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一标识，小写字母数字与连字符，如 `icaps-2027`、`tpami` |
| `name` / `full` | string | 简称（含年份）/ 全称 |
| `type` | `conference` \| `journal` | 会议或期刊（期刊为滚动投稿，无 `ddl`） |
| `ccf` | `A` \| `B` \| `C` \| null | CCF 第七版分级；非 CCF 为 null |
| `school` | `{level, basis}` | 学院成果等级 A–E 与认定依据 |
| `indexing` | `EI` \| `SCIE` \| `SCIE + EI` | 检索收录 |
| `relevance` | `{rating, tags}` | 方向相关度（高/中/低）与标签 |
| `when` / `where` | string | 会议时间地点（期刊无） |
| `ddl` | object \| 缺省 | 截稿日期字典，键见下；值可为 null（未官宣占位） |
| `tz` | string \| null | 时区说明（AoE / UTC−12 / PDT ...） |
| `confidence` | `official` \| `tracked` \| `estimated` | 数据置信度 |
| `req` | string | 投稿要求摘要 |
| `links` | object | 官网/CFP/模板等 https 链接 |
| `verifiedAt` | `YYYY-MM-DD` | 最近核验日期 |
| `source` | string | 数据来源说明 |
| `note` / `ccfNote` / `journalInfo` | string / object | 补充备注 / CCF 说明 / 期刊分区与审稿周期 |

`ddl` 允许的键：`arr`（ARR 周期）、`abstract`、`full`、`supp`、`commitment`、`stage2`、`notify`。
值为 ISO8601 带时区偏移，例：`2026-12-14T23:59:59-12:00`。前端据此统一换算北京时间并计算倒计时。

### 3.3 置信度语义

| 取值 | 含义 | 覆盖规则 |
|---|---|---|
| `official` | 官网 CFP 明确公布 | 仅允许「官网抽取成功」更新；不被 CCFDDL 覆盖 |
| `tracked` | 主流追踪库（CCFDDL）确认 | 可被官网抽取（→official）或 CCFDDL 新值覆盖 |
| `estimated` | 按往年规律预估 | 可被两者覆盖；与 CCFDDL 一致时升为 tracked |

---

## 4. 接口设计

### 4.1 前端 → 数据（fetch）

| 请求 | 用途 | 失败处理 |
|---|---|---|
| `GET data/venues.json` | 首屏加载 | 显示错误提示，引导用本地服务器预览 |
| `GET data/venues.json?t=<ts>` | 更新按钮强制刷新（cache: no-store） | toast 报错 |
| `HEAD api/venues` | 探测后端是否存在（决定同步按钮行为） | 静默忽略，退化为纯静态刷新 |

### 4.2 Flask 后端（`server/app.py`）

| 方法 | 路径 | 返回 | 说明 |
|---|---|---|---|
| `GET` | `/` | index.html | 静态托管入口 |
| `GET` | `/assets/<fname>` | 静态文件 | CSS/JS |
| `GET` | `/data/<fname>` | 静态文件 | 数据文件 |
| `GET` | `/api/venues` | `data/venues.json` 内容 | 供前端/外部读取 |
| `POST` | `/api/sync` | `{ok, data, changes, message, log}` | 触发同步；并发返回 429；异常返回 500 |

`POST /api/sync` 实现要点：
- 使用 `threading.Lock(blocking=False)` 防止并发同步，冲突返回 **429**；
- `subprocess.run([python, sync.py], timeout=600)` 执行同步引擎；
- 返回体含最近一次 `syncLog.changes`，供前端 toast 展示；
- 无论成功失败均在 `finally` 中释放锁。

> ⚠️ 参见「待确认」：当前 `/api/sync` 无鉴权，公网部署需限制来源或加 token。

### 4.3 同步引擎（`server/sync.py`）

| 函数 | 职责 |
|---|---|
| `load_env()` | 解析 `server/.env`（忽略注释/空行，支持引号） |
| `http_get(url, timeout)` | urllib 抓取文本，带 UA |
| `iso_from(deadline, tz)` | CCFDDL `2027-09-15 23:59:59` + `UTC-8` → ISO 带偏移 |
| `parse_ccfddl_yaml(text)` | 解析新版嵌套 `confs:/timeline:` 与旧版扁平 YAML |
| `sync_from_ccfddl(venues, log)` | 按 CCFDDL_MAP 抓取并合并，写 log |
| `fetch_page_text(url)` | 抓官网页面，剥离 script/style/标签，压缩空白，截断 9000 字符 |
| `llm_extract(page_text)` | 调 MiniMax OpenAI 兼容接口抽取日期/时区，容错 markdown 代码块 |
| `sane_date(iso)` | 过滤 2026-01-01 ~ 2029-12-31 之外的异常日期 |
| `sync_from_llm(venues, log)` | 官网抽取 → 升级 official，写 log |
| `main()` | 编排全流程；`--dry-run` 只打印不落盘；维护 `meta.syncedAt` 与 `syncLog`（保留最近 50 次） |

---

## 5. 数据流

### 5.1 首屏渲染流

```
DOMContentLoaded
  → init()
      → restore()           从 localStorage 恢复筛选条件
      → bindEvents()        绑定 chips / 复选框 / 搜索 / 更新按钮
      → fetch data/venues.json
      → renderGradRules() + renderMeta()
      → render()
          → filter（分类 + 状态 + 搜索）
          → sort（STATUS_RANK → sortKey）
          → cardHtml 拼接
          → updateCountdowns()
          → renderStats() + renderChips()
      → probeSyncApi()      探测后端
      → setInterval 倒计时(1s) + 状态签名检查(60s)
```

### 5.2 一键更新流

```
点击「立即更新」
  → syncNow()
      → 若 state.syncApi 存在：POST /api/sync
          → 后端加锁 → 跑 sync.py → 返回最新 data + changes
      → 无论是否有后端：GET data/venues.json?t=<ts>（no-store）强制拉取
      → render() + renderMeta()
      → toast 提示变更条数或"暂无变化"
      → finally 恢复按钮状态
```

### 5.3 同步合并流（sync.py）

```
main()
  → 读 data/venues.json
  → sync_from_ccfddl
      → 遍历 conference 且 id ∈ CCFDDL_MAP
      → 按候选路径抓 YAML → parse_ccfddl_yaml → 按年份匹配
      → 日期相同：estimated → tracked（confirm）
      → 日期不同且 official：保留官方（conflict-kept-official）
      → 日期不同且非 official：覆盖为 tracked（update）
  → sync_from_llm
      → 未配置 key 则跳过
      → 遍历 conference，取 CFP/关键日期/Dates/官网链接
      → fetch_page_text → llm_extract → sane_date 过滤
      → 有变更：升级 official，记录时区
  → 更新 meta.syncedAt + syncLog（最近 50 次）
  → 写回文件（dry-run 除外）
```

### 5.4 状态机（前端 statusOf）

```
journal ─────────────────────────────→ rolling（滚动投稿）
conference + statusOverride ─────────→ 覆盖值
conference + 存在未截止目标:
    距截止 ≤ 14 天 ─────────────────→ soon（即将截止，脉动提醒）
    距截止 > 14 天 ─────────────────→ open（投稿开放）
conference + 所有日期已过 ───────────→ closed（已截止，默认隐藏）
conference + 无任何日期 ─────────────→ tba（未开放）
```

---

## 6. 边界与异常场景

| # | 场景 | 处理策略 |
|---|---|---|
| 1 | `file://` 直接打开页面 | fetch 失败 → 显示提示，引导用本地 HTTP 服务器 |
| 2 | 数据文件加载失败（404/网络） | board 显示错误信息，不抛未捕获异常 |
| 3 | 无后端（纯静态）点更新 | 退化为强制刷新静态数据，toast 显示刷新时间 |
| 4 | 后端同步正在进行时再次请求 | `POST /api/sync` 返回 429 + "已有同步任务在进行中" |
| 5 | 同步进程异常退出 | 返回 500，message 含 stderr 尾部；锁释放；数据文件不被破坏 |
| 6 | MiniMax key 未配置 | 跳过官网抽取，仅做 CCFDDL 同步，日志记录 `"llm": false` |
| 7 | LLM 返回 markdown 代码块 | 正则提取首个 `{...}`，兼容 ```json 包裹 |
| 8 | LLM 返回非法 JSON / 非对象 / 越界日期 | 返回 None / 忽略，保持原数据 |
| 9 | CCFDDL 与 official 数据冲突 | 保留 official，记录 `conflict-kept-official` |
| 10 | CCFDDL 目标年份未收录 | 记 `skip`，保留原值（如 ECCV-2028 未官宣） |
| 11 | 会议多个截稿阶段（摘要/全文/ARR） | `targetOf` 取最近的未截止者为主目标 |
| 12 | 时区不一致（AoE / PDT / UTC+8） | 数据层存带偏移 ISO；前端用 Intl 统一换算北京时间 |
| 13 | 期刊无 DDL | 不参与倒计时/排序时间计算，固定显示"滚动投稿"与审稿节奏 |
| 14 | 未官宣会议（如 ECCV-2028） | `ddl` 值置 null 占位 + `confidence=estimated` + source 说明，前端显示"待官方公布" |
| 15 | 搜索/筛选无结果 | board 显示空状态提示，引导切换分类或显示已截止 |
| 16 | 每分钟状态签名变化 | 仅当条目跨越 DDL 时重建列表，避免打断用户展开的详情 |
| 17 | 同步日志增长 | `meta.syncLog` 只保留最近 50 次 |
| 18 | 前端 XSS（数据含 HTML） | 所有动态文本经 `esc()` 转义后再插入 innerHTML |
| 19 | localStorage 不可用（隐私模式） | try/catch 吞掉，筛选状态不持久化但不影响功能 |

---

## 7. 安全与隐私

- **密钥隔离**：`server/.env` 含 MiniMax key，已加入 `.gitignore`；`.env.example` 仅含模板。
- **历史清理**：曾误提交的含敏感信息部署脚本已从工作区与 Git 历史彻底清除。
- **输入转义**：前端所有来自 JSON 的字符串经 HTML 转义，防止注入。
- **并发保护**：同步接口加锁，避免重复消耗 token 与写文件竞争。

> ⚠️ 待加固：`POST /api/sync` 当前无鉴权，公网暴露可能被滥用。建议加 token 校验或 IP 白名单。

---

## 8. 测试策略

| 层次 | 文件 | 覆盖 |
|---|---|---|
| 单元测试 | `tests/test_sync.py` | .env 解析、时区换算、YAML 解析（含真实嵌套格式）、合并规则、LLM 容错、日期校验 |
| 数据契约 | `tests/test_data.py` | 31 条数据字段/枚举/ISO 时区/链接/毕业映射/CCFDDL 映射一致性 |
| 集成测试 | `tests/test_app.py` | Flask 静态托管、`/api/venues`、POST `/api/sync` 成功/失败/429/锁释放 |
| 前端测试 | `tests/js/app.test.js` | 状态计算、排序、筛选、转义、北京时间、卡片渲染、真实数据渲染 |
| 一键校验 | `scripts/verify.sh` | 上述全部 + Python/JS 语法 + JSON 校验 |
| CI | `.github/workflows/ci.yml` | push/PR 自动运行全套校验 |

所有测试离线运行：网络与 LLM 调用均被 mock，不消耗 token。运行：`bash scripts/verify.sh`。

---

## 9. 假设与待确认

以下内容无法仅凭仓库内文件确认，标注为假设，部署或投稿前请人工复核：

1. **学院认定适用版本**：`meta.ccfEdition` 按 CCF 第七版（2026-03）标注（IJCAI 降 B、ICLR 升 A、TMM 升 A 刊）。学院实际采用哪一版目录需向研究生院/学院确认。
2. **学院等级映射**：README 与数据中的「CCF-A 会议 → C 等、CCF-B → D 等」等映射依据学院页面解读，具体以当年成果认定清单为准。
3. **预估 DDL**：`confidence=estimated` 的条目（如 ECCV-2028、ICCV-2027 等）按双年刊/往年规律预估，官方发布后应通过同步或手工更新。
4. **期刊分区与影响因子**：`journalInfo` 中的中科院分区、JCR 分区、IF 为核验时快照，每年更新，投稿前以最新分区表为准。
5. **MiniMax 模型名**：默认 `MiniMax-M2`，以开放平台实际可用模型列表为准。
6. **`/api/sync` 鉴权**：当前未加鉴权；若公网部署，需补充 token/IP 白名单（列为待办）。
7. **部署拓扑**：`https://8.141.89.147/venue-radar/` 经 Caddy `handle_path` 反代到本机 8787；该端口映射为部署环境事实，非仓库内可验证内容。
