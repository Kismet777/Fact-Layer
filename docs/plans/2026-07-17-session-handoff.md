# Session 交接稿（新 session 从这里接手）

- 日期：2026-07-17
- 用途：接续 2026-07-14 交接稿，记录此后进展。自包含。
- 记忆入口：[[project-fl-tool-evolution]]（自动加载）指向本稿。
- 前一份：`docs/plans/2026-07-14-session-handoff.md`（使命两条线、更早的已完成/待办仍有效，未被本稿覆盖的部分照旧）。

---

## 一、使命（不变，两条线）

1. **FL 工具自身演进**（本仓 `fact-layer`）：无状态快照底座 → 版本化/可回退/文档式真源/溯源一致。核心不变量：**每个功能只为守"完整/当前/一致/可溯源"四属性之一而存在；不引入"文档内容存储"或"推理"。**
2. **贷后催收项目的 FL 维护**（该项目 `.facts/`）：真值以该项目 FL 的 `work-in-progress` 为准。本 session 未动这条线。

协作基调：agent 做批判性对手，用户掌控节奏；发现事实/文档/代码不一致先核实再改、不搁置；写下即须自洽（脱离对话也能无歧义复现）。

---

## 二、本 session 已完成（2026-07-14 → 07-17）

### 1. need→code 需求树（已写 + 已提交）
- `docs/requirements-need-to-code.md`：实用视角，与 philosophy（灵魂/动机）互补、职责分离。
- 结构：根（agent 长线开发事实不稳定：多重备份/延迟不一致/信息缺失）→ 四属性（完整/当前/一致/可溯源）+ 可自证元需求；每叶子钉到 `file.py:function`；双向审计（功能追不到需求=多余；空叶子=缺口）+ 缺口登记表。
- **每个代码锚点都已逐一核实**（读了 cli/mcp_server/exporter/editor/checker/models/scanner）。过程中修正 4 处初稿错误、抓出一处 **philosophy↔code 漂移**（philosophy 把 `source-of-record`/`derived_from`/slot→文档边当已实现叙述，代码里 `SlotMeta`/`DependencyTarget` 均无）。
- 用户已亲自审过树，认可当前结构。

### 2. delta 水位线 export（已写 + 已提交 commit 86de58c）
- 解决"agent 反复 export 同样内容污染上下文"（污染的**前半**：少重复吐）。
- 无状态：令牌 `<max_updated_date>:<sha8>` 由调用者持有回传；hash 判"整体变没变"，date 驱动增量过滤。
- 接口：`exporter.compute_watermark` / `render_export_delta`；CLI `fl export --since <token>`；MCP `facts_export(since=...)`；`render_export`/budgeted 尾行都吐 `fl-watermark:`。
- 三态：无 since→全量+令牌；无变化→极小 "No fact changes"；有变化→只给该日期及之后的 slot。
- TDD：9 新测试 + 全量 **430 passed**；已在真实贷后催收 `.facts/` 用 CLI 端到端验证。
- **已知边界（写进代码注释）**：date 颗粒度（同日重复带上、绝不漏）；不报删除。精确到条+报增删属完整版 **FL-022**。

### 3. 提交与远端
- 已提交并**推送到 origin/main**（截至 `15eb280`）：`904adcf` LLM 单源重构 / `3827683` FL-026 facts_add + Bug B / `15eb280` 需求树+plans。
- 本地领先 origin 的未推：`86de58c`（delta export）。**用户此前只让"提交"delta、未让 push** → 需确认是否 push。
- `docs/architecture-philosophy.md` 按约定**未提交**（待重写勿提，仍是未跟踪文件）。

### 4. FL 缺口 roadmap 增补
- `docs/plans/2026-07-16-fl-completeness-gaps.md`：**FL-027** 内外完整性对账（缺失+失真统一，补 `scan_integrity._check_value_mismatch`）。
- **编号勘误**：`facts_search` = **FL-021 L1**（早规划于 07-05，非新项，初稿曾误标 FL-027）；`facts_trace` = **FL-021 L2**（初稿曾遗漏，已补进需求树 §3.4）。

---

## 三、当前正在讨论（下一步的直接入口）

**facts_search（FL-021 L1）要实现什么——设计讨论进行中，5 个待定决策：**
- ① 匹配机制：**倾向离线子串**（大小写不敏感，多词 AND），因项目事实**中英混合**（中文需分词、BM25 麻烦；子串绕开分词、零依赖、离线，合 FL 气质）；语义/embeddings 推后（引模型依赖，虽过身份测试但违离线气质）。
- ② 搜索字段：倾向 slot-id + value(拍平) + reason + 类别名 + 决策 title/rationale；只搜活跃(active/uncertain)。
- ③ 返回形态：倾向**直接带命中 slot 的完整值 + 命中字段**（省一次 facts_get 往返，正合"少 export"目的），`--limit` 封顶防退化为全量。
- ④ 排序：slot-id 精确 > slot-id 子串 > value > reason；`--category` 过滤。
- ⑤ 边界确认：search 只搜 **FL 里的 slot**，不搜文档/快照正文；与 `facts_trace`（沿边遍历，FL-021 L2）分工不同、本次不做。

**用户尚未拍板 ①②③（尤其①要不要现在上语义）与⑤边界。** 敲定后 TDD 实现（CLI `fl search` + MCP `facts_search`，纯检索不合成、过 philosophy 原则 2）。

---

## 四、其他待办（优先级）

- **【文档·中】重写 `architecture-philosophy.md`**：用户评"仍很烂"；需区分"已实现的地面"与"设计意图"（校正上面那处 philosophy↔code 漂移）。排在 search 之后。
- **【项目】** 复核贷后催收 `historical_max_overdue_days` 口径（status=5 曾当"逾期中"，DDL 疑为 loaned）——贷后催收线，本 session 未碰。
- **FL 演进大件（roadmap）**：FL-022 并发底座(P0) / FL-021 L3 文档式真源(P1) / FL-024 角色记忆(P1) / FL-023 warden(P2) / 冷热分层(P3)——见 `docs/plans/2026-07-06`。
- **边界开放问题（philosophy 重写须界定）**：FL-023/FL-024/冷热分层挂不进四属性（参考态非真源）；网状可视化（拖拽/点击的交互式依赖图）过身份测试但 FL 无前端——"内建 vs 独立 viewer"是表面积决策。二者置疑性质不同，见需求树缺口表下 ⚠️ 备注。

---

## 五、操作注意（重要）

- **运行中的 `fl-mcp` 是旧进程**：需重启才暴露 `facts_add`、`facts_export` 的 `since` 参数，并使 `facts_set_batch`/`facts_audit` 的 `model=None` 走 config（deepseek）。CLI 与库用的是工作区新代码、已生效。
- **一切对 `.facts/` 的读写走 FL 接口**（MCP 指向的是**贷后催收**项目；要写 **fact-layer 自己**的 `.facts/` 用 **CLI `fl`** 从本仓目录跑，勿手编辑）。本 session 已用 CLI 把本仓 `work-in-progress` 5 槽位更新到当前状态。
- **建新 slot** 用 `fl add` / `facts_add`（重启后）；`facts_set` 只更新既有。
- git 提交作者被自动记为 `Kai Yuan <nokismet@…local>`（未配 user.name/email），不影响功能。

---

## 六、给新 session 的一句话

先读本稿 + `docs/requirements-need-to-code.md`（需求树，含缺口表），再看本仓 `fl export --stdout` 里的 `work-in-progress`。当前活是**接着敲定 facts_search（FL-021 L1）设计（①②③⑤）再 TDD 实现**；philosophy 重写随后。
