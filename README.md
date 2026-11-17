# 📡 投稿雷达 · Venue Radar

为 **VLN（视觉语言导航）/ 多目标导航 / GNN / MAPF** 方向量身打造的会议·期刊投稿 DDL 看板。

参考苏州大学未来科学与工程学院学术型硕士学位成果要求，把「哪些会值得投、投了算什么等级、什么时候截稿」集中到一页：**名称 · CCF 分级（第七版）· 学院毕业等级映射 · 方向相关性 · 投稿要求摘要 · 官网链接 · DDL（年月日/时刻/时区/北京时间换算）· 实时倒计时 · 数据置信度与核验时间**。

纯前端零依赖，手机端自适应，支持一键更新与自动同步。

---

## ✨ 特性

- 🗂 **31 个会议/期刊**：CCF-A/B/C 会议、非 CCF 顶会（CoRL / RSS）、顶刊与性价比期刊（RA-L / T-RO / IJRR / TPAMI …）
- ⏱ **实时倒计时**：14 天内逐秒倒数并脉动提醒，自动按「即将截止 → 开放中 → 未开放 → 期刊 → 已截止」排序
- 🏷 **三重等级标注**：CCF（第七版口径）+ 学院毕业等级（A–E 等）+ EI/SCIE 检索
- 🔍 **置信度分级**：`✓ 官方`（官网 CFP 已公布）/ `≈ 追踪`（主流 DDL 库）/ `~ 预估`（按往年规律），每条附核验日期与来源
- 🔄 **一键更新**：按钮带缓存击穿重新拉取；部署后端后可触发 CCFDDL 结构化同步 + MiniMax 官网抽取核对
- 🤖 **每日自动同步**：GitHub Actions 每天 09:00（北京时间）刷新 DDL 并自动提交
- 📱 **手机适配**：单列卡片、横向筛选 chips、粘性筛选栏

## 🚀 本地预览

```bash
cd venue-radar
python -m http.server 8000
# 浏览器打开 http://localhost:8000
```

> 直接双击 index.html（file://）无法 fetch 数据，请通过任意静态服务器访问。

## ☁️ 部署

### 方式一：纯静态（最简）

任意静态托管（GitHub Pages / Vercel / nginx）直接上传根目录即可。此时「立即更新」= 强制绕过缓存重新拉取 `data/venues.json`，配合 GitHub Actions 每日自动同步即可保持数据新鲜。

<details>
<summary>GitHub Pages 开启方法</summary>

仓库 Settings → Pages → Source 选 `main` 分支根目录，保存后访问 `https://xiao-ma-77.github.io/venue-radar/`（注意路径下访问时 fetch 的相对路径 `data/venues.json` 依然正确）。
</details>

### 方式二：带同步后端（推荐部署到云服务器）

```bash
git clone https://github.com/XiaoMa-77/venue-radar.git
cd venue-radar/server
pip install -r requirements.txt
cp .env.example .env      # 填入 MiniMax 密钥（见下）
python app.py             # 0.0.0.0:8787
```

页面会自动探测到 `/api/sync`，点击「立即更新」即触发真实同步。

生产环境建议：`gunicorn -w 1 -b 0.0.0.0:8787 app:app`（单 worker，避免同步锁竞争）。

## 🤖 配置 MiniMax（用于官网 DDL 抽取核对）

`server/.env`（已被 `.gitignore` 排除，**永远不会进入仓库**）：

```ini
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_API_KEY=你的密钥
LLM_MODEL=MiniMax-M2      # 以 MiniMax 开放平台实际模型列表为准
```

配置后 `python server/sync.py` 会依次抓取各会议官网 CFP 页面正文，交给模型抽取
摘要/全文/通知日期与时区，成功则把条目升级为 `✓ 官方` 置信度；未配置密钥时自动跳过该环节，
仅做 CCFDDL 结构化同步。

## 🔁 同步机制说明

```
点击「立即更新」 / 每日 GitHub Actions
        │
        ├─ ① CCFDDL（github.com/ccfddl/ccf-deadlines）
        │     社区维护的结构化 DDL 库 → 置信度「追踪」
        │
        ├─ ② 官网抽取（可选，需 MiniMax key）
        │     抓 CFP 页面 → 模型抽取日期/时区 → 置信度「官方」
        │
        └─ ③ 合并写回 data/venues.json（official 条目不被低优先级来源覆盖）
              meta.syncedAt / syncLog 记录每次变更，可回溯
```

## 📊 学院毕业等级速查（已内置页面）

学术硕士需 **≥1 项第 1-4 类 E 等以上成果**：

| 成果类型 | 学院等级 | 备注 |
|---|---|---|
| CCF-A 国际会议（CVPR/ICCV/ICLR/ICML/NeurIPS/ACL/AAAI/ACM MM） | **C 等** | 录用通知即可，无需见刊 |
| CCF-B 国际会议（ICRA/ECCV/EMNLP/NAACL/IJCAI⑦/ICAPS/AAMAS） | **D 等** | 须正式见刊 |
| CCF-C 会议（IROS/ACCV/BMVC 等，均 EI 收录） | **E 等** | |
| CCF-A 期刊（TPAMI/IJCV/TMM/JMLR） | **B 等** | |
| SCIE 中科院 1-2 区 | **C 等** | RA-L(2区)/PR/TNNLS/T-ITS 等 |
| 附件1 增补（T-RO/IJRR/Science Robotics/TAC/Automatica…） | **B 等** | |
| EI 收录国际会议/期刊 | **E 等** | 保底线 |

署名要求：苏州大学第一署名单位 + 学生第一作者 + 导师署名；英文论文须 online（有 DOI）。

> ⚠️ CCF 第七版（2026-03）将 IJCAI 降为 B、ICLR 升为 A；学院认定适用版本请与学院确认。
> IROS 在 CCF 目录中长期为 **C 类**（ICRA 为 B 类），经 EI 收录口径满足 E 等。

## 🧪 测试与验证

项目包含完整的离线自动化测试（网络与 LLM 调用全部 mock，不消耗 token）：

```bash
pip install -r server/requirements.txt
bash scripts/verify.sh
```

一键脚本会依次运行：Python 语法检查、同步引擎单元测试、31 条数据契约校验、Flask 集成测试、
JS 语法检查、前端逻辑测试（Node 内置 test runner，无需 npm）、JSON 校验。当前 **62 Python + 18 Node = 80 项测试全通过**。

手动分组运行：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v   # 后端 + 数据 + 集成
node --test tests/js/*.test.js                           # 前端
```

CI：`.github/workflows/ci.yml` 在每次 push / PR 到 `main` 时自动跑全套校验；
`.github/workflows/sync.yml` 每日 09:00（北京时间）自动同步 DDL。

## 📐 设计文档

架构、接口、数据流、数据契约、边界与异常场景、假设与待确认项见 **[DESIGN.md](DESIGN.md)**。

## 🗃 数据维护

- 手动修订：直接编辑 `data/venues.json`（字段说明见文件内注释风格：`ddl` 各键存 ISO8601 带时区偏移的时间，JS 自动换算北京时间并计算倒计时）
- 新增条目：复制一个同类条目改字段即可，页面自动纳入筛选与统计
- 撤销同步：`meta.syncLog` 保留最近 50 次变更记录

## 📁 结构

```
venue-radar/
├── index.html            # 单页应用
├── assets/
│   ├── style.css         # 纸感手帐 × 现代简约样式
│   └── app.js            # 渲染/倒计时/筛选/更新逻辑
├── data/
│   └── venues.json       # 唯一数据源（31 条，人工核验于 2026-11-17）
├── server/
│   ├── app.py            # 可选 Flask 后端：静态托管 + POST /api/sync
│   ├── sync.py           # 同步引擎：CCFDDL + MiniMax 官网抽取
│   ├── .env.example      # 密钥配置模板（.env 不入库）
│   └── requirements.txt
├── tests/
│   ├── _helpers.py       # 测试辅助：按路径加载模块
│   ├── test_sync.py      # 同步引擎单元测试
│   ├── test_data.py      # 数据契约校验
│   ├── test_app.py       # Flask 集成测试
│   └── js/app.test.js    # 前端逻辑测试（Node test runner）
├── scripts/
│   └── verify.sh         # 一键校验脚本
├── DESIGN.md             # 设计文档
├── .github/workflows/
│   ├── sync.yml          # 每日自动同步
│   └── ci.yml            # push/PR 自动测试
```

## ⚠️ 免责

本工具仅用于个人科研管理。DDL、分级、分区信息均可能变动，投稿前务必以官网最新 CFP 与学院最新文件为准。
