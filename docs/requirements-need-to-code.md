# fact-layer 需求树（need → code 溯源）

## 关于本文

这是一篇**实用导向**的文档：它把 FL 的每一个功能，沿一条 need → code 的链条，钉回它所服务的需求，最终钉到具体代码。它回答的是"这个功能凭什么存在、它实现在哪"。

它与 `architecture-philosophy.md` 互补、职责不重叠：

- **philosophy** 讲**灵魂与动机**——FL 为什么必然存在、"可信"如何定义、原则如何长出功能。读它是为了**判断一个未来的功能该不该存在**。
- **本文** 讲**结构与落地**——已经存在的功能各自挂在哪条需求下、实现在哪个文件哪个函数、哪些需求还悬空没有实现。读它是为了**盘点当前系统覆盖到哪、漏在哪**。

**怎么读这棵树（双向审计）**：

- **自底向上**：任何一个功能/代码，都必须能沿树向上追到一条真实需求。**追不到需求的功能 = 多余**，是要被质疑删除的对象。
- **自顶向下**：任何一条需求，都应能向下派生到非空的叶子（代码）。**向下是空叶子的需求 = 缺口**，是 roadmap 的来源（如 `facts_trace`、源指纹值失真对账、注入式演习尚未建）。

叶子状态标记：
- ✅ **已实现**——有对应代码，命令/工具可用。
- 🟡 **部分**——机制存在但不完整，或仅覆盖部分场景。
- 🔴 **缺口**——需求成立但无实现，或只能靠被铁律禁止的手段（手改 `.facts/`）。
- 🔵 **roadmap**——已在计划文档中设计，尚未落地。

---

## 根需求（最抽象）

> **agent 在长线、并行、跨会话的开发中，需要一层"可信的项目事实地面"来据以行动。**

驱动这条根需求的，是 agent 自主开发时项目事实的**三个不稳定症状**：

1. **多重备份**——同一条事实散落在代码注释、文档、口头约定、各 agent 的私有记忆里，没有一个被公认的收口，谁都不知道该信哪一份。
2. **带延迟的不一致**——世界变了，事实没跟着变；或改了一条，依赖它的另几条没跟着改。矛盾与过期是**静默**的，读起来仍像正确。
3. **相关信息缺失**——需要的事实要么根本没被记录，要么记录了却找不到，于是 agent 退回去从原始素材现推——而现推正是幻觉的产地。

（*为什么这三个症状随 agent 进步而加剧、而非缓解，是 philosophy 的题目，不在此展开。*）

FL 对这条根需求的回答，就是把"可信"拆成**四个可被守卫、可被度量的属性**，让每一个功能都只为守卫其中之一而存在：

- **完整**——需要的事实这里有，且找得到。
- **当前**——事实反映的是现在。
- **一致**——事实之间不自相矛盾。
- **可溯源**——每条事实都知道自己从哪来、还准不准。

外加一条**元需求**（philosophy §6）：

- **可自证**——FL 必须能证明自己确实做到了上面四条；一个要求别人信任、自己却无法自证的事实层，是自我推翻的。

下面五棵子树，就是这五条需求各自派生到代码的展开。

> **接口二元性（横切，非独立需求）**：下列每一个"写/读/查"能力，都要求经由 agent 的原生通道（**MCP tool**）与人的通道（**CLI**）双路可达且语义对等。这不是一条独立需求，而是所有 I/O 叶子的交付形态。历史缺口 FL-026（MCP 只能 `set` 不能 `add`）就是这条对等性被打破的例子，现已由 `facts_add` 补齐。凡叶子同时给出 CLI 命令与 MCP 工具名的，即已双路覆盖。

---

## 一、完整 —— 需要的事实这里有，且找得到

> 敌人：事实虽在却找不到，于是退回去现推。查不到的事实，功能上等于不存在。

**完整这棵树分两层抽象，务必分清：**

- **A 操作层（低抽象，针对具体事实）**——写一条、读一条、以及"知道现在有哪些"（全量清单）。三者平级，都是对**具体事实**的存取。
- **B 完整性层（高抽象，针对"事实全集够不够全"）**——把 FL 内部事实与外部真实相比，回答"是否完整"。它凌驾于 A 层：A 层保证"我能操作我知道的事实"，B 层才回答"我知道的事实是不是就够了"。

```
完整
│
│ ── A. 操作层：对具体事实的存取 ────────────────────────────
│
├── 1.1 地面得先存在（bootstrap 一个 .facts/）
│     └── ✅ CLI `fl init` → core/init_cmd.py:init_facts_dir
│           （建 framework + dependencies + canonical 模板；交互选启用哪些扩展类别）
│
├── 1.2 写事实（声明 = 唯一写入收口，philosophy 原则 1）
│     ├── ✅ 新建 slot：CLI `fl add` → core/editor.py:add_slot
│     │        MCP facts_add → 同上（FL-026 补齐的对等工具）
│     ├── ✅ 更新 slot：CLI `fl set` → core/editor.py:set_slot（经 _set_single）
│     │        MCP facts_set → 同上
│     ├── ✅ 批量写：CLI `fl set --batch` / MCP facts_set_batch → core/editor.py:set_batch
│     ├── ✅ 软删除（保留历史，不真删）：CLI `fl deprecate` → core/editor.py:deprecate_slot
│     └── 🔴 类别生命周期（新建/启用一个类别）：无接口（FL-025）
│              现状：只能手改 framework.yaml 的 enabled + 手建 canonical/<cat>.yaml，
│              而"不得直接编辑 .facts/"是铁律 → 结构性完整缺口。
│              修复方向：`fl category enable/add` + 对应 MCP，见 docs/plans/2026-07-13-fl-interface-gaps.md
│
├── 1.3 读具体事实（已知道要哪条 / 哪类）
│     ├── ✅ 单条读：MCP facts_get（CLI 侧经 export/status 间接可见）
│     ├── ✅ 列一个类别的 slot：CLI（经 export）/ MCP facts_list
│     └── ✅ 按内容发现事实（不预先知道 slot 名也能找到）：facts_search（**FL-021 L1**）
│              CLI `fl search <query>` / MCP facts_search → core/search_cmd.py:compute_search（纯函数）。
│              离线子串匹配（大小写不敏感；多词 = AND；CJK 无空格查询按整段子串），
│              搜 slot-id + 拍平后的 value + reason，命中回完整值 + matched_fields（标出哪些字段命中）。
│              默认只搜 active，`--include-stale` 纳入 stale/superseded；`--limit` 截断（默认 20，超出标 truncated）。
│              兑现 philosophy 原则 5"找得到"这一叶子。**边界**：纯词面，不做语义/embeddings
│              （会引入存储派生物 + 软推理，违原则 2/7）；语义级发现仍靠 facts_scan / audit。
│
├── 1.4 知道现在有哪些事实（全量清单 / 简介）
│     ├── ✅ 全量内容快照：CLI `fl export` / MCP facts_export
│     │        → core/exporter.py:render_export（全量）/ render_export_budgeted（带 token 预算截断）
│     ├── ✅ 分类别概览（填充数/tier，无逐条内容）：
│     │        CLI `fl status` / MCP facts_status → core/status_cmd.py:compute_status
│     └── ✅ 目录式清单（列全部 slot + 每条一行 snippet、不含完整值）：
│              CLI `fl export --outline` / MCP facts_export(outline=True) → core/exporter.py:render_export_outline。
│              补上 export（全量正文，偏重）与 status（纯计数，偏薄）之间的"轻量目录"一档，
│              是"先 outline 认路 → search 模糊 → get 精确"闭环的入口，避免为认路而全量 dump。
│
│ ── B. 完整性层：FL 全集是否够全（更高抽象） ──────────────────
│
└── 1.5 内外对比：FL 内部事实 vs 外部真实 → 判断"是否完整"
      │     （问的是"外部有、FL 没有"= 事实**缺失**，广度问题；
      │      与可溯源 §4.3 的"FL 有、源已变"= 事实**失真**是两回事，见该处）
      ├── 🟡 建设性发现：CLI `fl scan` / MCP facts_scan → core/scanner/pipeline.py:run_scan
      │        从 pyproject/Dockerfile/package.json/CI + README/CLAUDE.md 等提候选，
      │        其 **unmapped 输出**即"外部存在、FL 未纳管"的事实——正是内外对比的建设形态。
      │        经人/agent 确认后走 1.2 的声明入口落地（是发现的助手，不自动派生真源）。
      ├── 🟡 校验性对账：`fl audit --scan-integrity` / MCP facts_scan_integrity
      │        → core/scan_integrity.py（跨源冲突 / 孤儿抽取 / stale sources）
      ├── 🔴 系统性 code↔FL 漂移对账（不止扫描源文件，而是把"应有的事实全集"
      │        与 FL 现状系统比对）：未建。交接稿 §三.5 拟与"文件真源漂移检测"统一为一个机制，
      │        见 docs/plans/2026-07-06-multi-agent-state-and-memory.md。
      └── 🔴 事实缺口率度量（"需要而 FL 没有、被迫现推"的次数）：
               这是把"是否完整"变成可测数字的手段，落在第五棵树 §5 可自证，当前基本待建。
```

---

## 二、当前 —— 事实反映的是现在

> 敌人：漂移。世界变了、事实没变，而它读起来仍像正确。这种错误静默、不报警。

```
当前
├── 2.1 按衰减速率分配复核注意力（philosophy 原则 3）
│     └── ✅ tier 模型（stable / dynamic / working）
│              → models/framework.py + models/category.py（tier 字段）
│              不同类别按波动性标注该多久复核一次，把"当前"从被动期望变成主动策略。
│
├── 2.2 检出过期（staleness）
│     ├── ✅ CLI `fl check` 的 staleness 分支 → core/checker.py:run_check
│     │        （按 tier 的复核周期比对 last_verified，超期即告警）
│     └── ✅ 健康总览（填充率 + staleness + last_verified）：
│              CLI `fl status` / MCP facts_status → core/status_cmd.py:compute_status
│
├── 2.3 检出"源变了但事实没变"的隐形漂移
│     └── 🟡 部分：源索引对每个源文件存 content_hash + status，内容变即标 stale
│              → core/scanner/indexes.py:SourceEntry；
│              `fl audit --scan-integrity` / MCP facts_scan_integrity → core/scan_integrity.py
│              可报 stale_source / orphaned_extraction / cross_source_conflict。
│              三重缺口：① 连接"源变→该 slot 值是否失真"的 _check_value_mismatch 是空壳（未比对）；
│              ② 只覆盖经 scan 进来的事实，人/agent 声明的 slot 无源关联；
│              ③ 未接入 `fl check`/staleness 主循环，是独立命令。详见第四棵树 §4.3。
│
└── 🟡 2.4 版本化 / delta 感知（只报变化，philosophy 原则 6）
        **动机（实测痛点）**：agent 为了解项目反复调 export，同样内容大量重复污染上下文。
        解法两半：① 少 export——用 facts_search（§1.3）+ facts_trace（§3.4）精准取，不必全量 dump；
        ② export 不重复吐——bootstrap-once + delta（"自上次无变化"就不再吐全量）。
        ✅ **v1 已实现（无状态轻量水位线 delta）**：exporter.py:compute_watermark / render_export_delta；
           每次 export 尾行吐 `fl-watermark: <date>:<hash>` 令牌，CLI `fl export --since` / MCP facts_export(since=)。
           无变化→极小 "No fact changes"；有变化→只给该日期及之后的 slot。
           已知边界：date 颗粒度（同日重复带上、绝不漏）、不报删除。杀的是"重复吐"，跨新会话仍需一次全量 bootstrap。
        🔵 **完整版仍 roadmap**：per-slot revision + delta-since-revision = **FL-022**（精确到条、报增删）；
           export bootstrap 语义 + 文档式真源 = **FL-021 L3**。
```

---

## 三、一致 —— 事实之间不自相矛盾

> 敌人：局部编辑。改一条，没意识到另几条依赖它，矛盾悄悄产生。一致是事实之网的整体属性。

```
一致
├── 3.1 单一写入收口（一致只有存在单点收口时才可强制，philosophy 原则 1）
│     └── ✅ 所有写路径（add/set/batch/deprecate）都收敛到 core/editor.py，
│              每次写入先过校验（见第 3.2、3.3）再落地。
│
├── 3.2 输入校验（写时守卫 + 载入时 schema 校验，两个环节）
│     ├── ✅ 写时守卫：core/editor.py:_validate_category_enabled（拒绝写未启用类别）
│     │        + 存在性检查（add 撞已存在报错 / set 找不到报 KeyError）
│     │        + parse_value（值形状解析，editor.py，cli 侧同名）
│     └── ✅ 载入时 schema 校验：models/slot.py:SlotMeta / models/category.py:CategoryFile
│              （pydantic，load_all_categories 时校验）。
│              注意：写路径直接改 YAML dict、并不在写时跑 pydantic，
│              结构性错误是在随后的 load/check 暴露，而非写入当刻拦截。
│
├── 3.3 规则化一致性检查（结构 / 依赖 / 决策）
│     └── ✅ CLI `fl check` / MCP facts_check → core/checker.py:run_check
│              涵盖 structural、dependency、decisions 三类（+ 2.2 的 staleness）。
│
├── 3.4 网状视图：改一条，看清牵动谁
│     ├── ✅ 依赖图数据：models/dependency.py + .facts/dependencies.yaml
│     │        （derives-from / constrains / references / implies / conflicts-with + 决策 affected-slots）
│     ├── ✅ 影响分析（仅下游）：CLI `fl impact` / MCP facts_impact → core/impact_cmd.py:compute_impact
│     │        （给一个 slot，列出下游"必须更新/应检查"的 slot 与相关决策）
│     ├── 🔴 双向链路遍历：facts_trace 未建（**FL-021 L2**，plans/2026-07-05）
│     │        impact 只给下游；沿 dependencies + decisions.affected-slots **双向**输出
│     │        "上游依赖 + 下游影响"的完整推理链，尚无接口（impact_cmd 遍历可复用一半）。
│     └── 🔴 交互式网状可视化（拖拽节点 / 点击看信息 / 高级图探索）：未建
│              ⚠️ 归属待定：数据（依赖图）是 FL 的、且通过身份测试（只渲染已有边、不存新事实/不推理），
│              但 FL 至今无任何前端——"富交互前端内建于 FL" vs "FL 暴露图数据、独立 viewer 渲染"
│              是 scope 决策，未定前不给 FL 编号。后端依赖 facts_trace（FL-021 L2）做遍历。
│
├── 3.5 语义级一致性（规则查不出的矛盾，用 LLM 查）
│     ├── ✅ LLM 审计：CLI `fl audit` / MCP facts_audit → core/auditor.py:run_audit
│     │        （查 contradiction / staleness / missing / redundant / 缺失依赖关系）
│     └── ✅ 修复建议：CLI `fl suggest` → core/suggest_cmd.py:run_suggest
│              （对 `fl check` 发现的问题，用 LLM 生成可交互应用的修复）
│
└── 🔵 3.6 乐观并发 / 可回退（多 agent 并行写不互相踩）
        FL-022 并发底座，见 docs/plans/2026-07-06-multi-agent-state-and-memory.md
```

---

## 四、可溯源 —— 每条事实都知道自己从哪来、还准不准

> 敌人：断根的事实。没有溯源，前三个属性都无从校验。
> **诚实边界**：这是四属性里当前实现最薄的一棵——philosophy §6 直言"可溯源当下约等于零"。

```
可溯源
├── 4.1 真源在哪（source-of-record：一条事实以谁为准）
│     └── 🔴 缺口（比预想更薄）：SlotMeta（models/slot.py）**没有真源指针字段**——
│              其 `source` 只是三值来源类型枚举（human / agent-analysis / code-extracted），
│              不是"指向外部文档/DB/另一条 slot"的 source-of-record。
│              唯一的 slot→源关联在 scan 抽取索引（indexes.py:ExtractionEntry.source_id），
│              且只覆盖经 scan 进来的事实；人/agent 声明的事实完全断根。
│              ⚠️ philosophy §三/§四把 derived_from、source-of-record 当作已存在来叙述，
│              与数据模型现状不符——一处 philosophy↔code 漂移，重写 philosophy 时须校正。
│
├── 4.2 事实之间的溯源边（slot ↔ slot）
│     └── ✅ 边模型 derives-from / constrains / references / implies / conflicts-with
│              已存在（models/dependency.py:DependencyTarget），落在 .facts/dependencies.yaml。
│              边只为漂移检测与影响分析服务、从不合成新事实（philosophy 原则 2）。
│              注意：边的 target 只能是**另一条 slot**，无 slot→文档 的边（与 philosophy 措辞不符）。
│
├── 4.3 源指纹 + 漂移探测（把原子事实层与源变化连起来，philosophy 原则 4）
│     └── 🔴 半成品：源指纹**已有**（indexes.py:SourceEntry.content_hash，内容变即 stale），
│              但"源变了 → 依赖它的 slot 值是否失真、要不要复核"这半条链**没打通**：
│              scan_integrity.py:_check_value_mismatch 是空壳（载入 slot 值却不比对），
│              且不覆盖人/agent 声明的事实、不接入 check/staleness。
│              **这是可溯源这棵树的核心空叶子。**
│
└── 🔵 4.4 文档式真源（L3：长文档不塞进原子模型，FL 只算指纹+连边+指向锚点）
        FL-021 L3，见 docs/plans/2026-07-06-multi-agent-state-and-memory.md（philosophy 原则 7）
```

---

## 五、可自证（元需求）—— FL 能证明自己做到了四属性

> philosophy §6：FL 的原则是"别信任，要核实"，那么它必须能把这条原则用在自己身上。

```
可自证
├── 5.1 承重性地板：FL 到底被不被查（客观、不可粉饰）
│     ├── ✅ 访问日志（每次 get/list/check/export 都记）→ core/access_log.py:log_access
│     │        统计：CLI `fl eval access-stats` / MCP facts_eval_access_stats
│     │        → core/access_log.py:compute_access_stats（按 caller/op/热点槽位聚合）
│     └── ✅ search 专项埋点（度量 §1.3 那条叶子真被用、且真转化为读）：
│              log_search 每次调用记 op=search（args 含 query + hits 数），每个命中槽位另记 op=search-hit；
│              compute_access_stats 由此产出 by_slot_op 交叉表（slot × 触达方式）、search_empty_rate（空结果率）、
│              search_to_get_rate（命中后该槽是否又被 get 的槽级转化率，用 by_slot_op 共现估、顺序不敏感）。
│              CLI access-stats 打印 "search 健康" 行（调用数/空结果率/转化率）；完整 by_slot_op 交叉表经 MCP 返回。
│
├── 5.2 语义化 eval trace（四属性 + bypass 的可测化）
│     ├── ✅ 写 trace：CLI `fl eval log` / MCP facts_eval_log → core/eval_cmd.py:save_trace
│     ├── ✅ 从 transcript 自动重建 L1+L2：
│     │        CLI `fl eval ingest --tool claude|codex`
│     │        → core/transcript_ingest.py:ingest_transcript / core/codex_ingest.py:ingest_rollout
│     ├── ✅ 浏览：CLI `fl eval list` / MCP facts_eval_list → core/eval_cmd.py:load_traces
│     └── ✅ 聚合指标（FL vs 文档比、来源分布、bypass、slot 命中、L2 覆盖、耗时）：
│              CLI `fl eval stats` / MCP facts_eval_stats → core/eval_cmd.py:compute_eval_stats
│
└── 🟡 5.3 结果层：FL 有没有效（"结果真的减少接地失败吗"）
        philosophy §6 列为"基本待建"的空叶子。测量框架见 plans/2026-08-12-eval-effectiveness-measurement.md：
        区分 观测(T2 读链路判 A/B/C) vs 因果(T3 消融)；四格地图 + 三堵墙(方差/干净对照/oracle)；
        原"注入式演习"= 其中 T3a（构造有 oracle 的题、干净因果）。⚠ fl_ratio 只是相关，不得当有效性。
        ├── 🟡 T2 观测（读链路判 A/B/C，产出采纳率 A/(A+B)）：已落，spec plans/2026-08-13-eval-l3-S0-S1-impl-spec.md
        │       ├── S0 数据模型/存储：models/eval_results.py（EvidenceBundle/ABCJudgement/T2Report/make_event_id）
        │       │       + core/eval_t2.py:save_verdict / load_verdict_cache（.facts/eval/results/t2_verdicts.jsonl，幂等缓存）
        │       ├── S1a 证据抽取：core/eval_t2.py:extract_evidence（纯函数，reasoning_span 含读 step 前后相邻推理）
        │       ├── S1b LLM 判定：core/eval_t2.py:judge_evidence / judge_all（禁 regex 代理、幂等缓存、后端失败降级 unknown）
        │       ├── S1c 聚合+出口：core/eval_t2.py:compute_t2_report / run_effectiveness
        │       │       + CLI `fl eval effectiveness` + MCP facts_eval_effectiveness（T1 计数与 T2 采纳率分栏）
        │       └── fl_return 本次留空（选 1，字段保留）
        ├── 🔴 T3a 注入式演习（构造有 oracle 的题、干净受限因果）：未建（S2）
        └── 🔴 T3-turn 配对消融（须现查 FL 的 turn 上 ±FL、pairwise judge）：未建（S3）
```

---

## 缺口登记（自顶向下审计的产物）

把上面所有 🔴/🟡 汇总，即当前"需求成立但落地不足"的清单，按优先级：

| 编号 | 需求归属 | 缺口 | 状态 | 出处 |
|------|----------|------|------|------|
| FL-021 L1 | 1.3 完整 | facts_search：按内容发现事实（离线子串，CLI+MCP 双路）——**已实现** | ✅ 已实现 | commit b627f69 |
| FL-021 L2 | 3.4 一致 | facts_trace：沿依赖+affected-slots 双向遍历推理链未建 | 🔴 待实现 | plans/2026-07-05 |
| FL-027 | 1.5/4.3 完整+可溯源 | 内外完整性对账（缺失+失真统一对账，补 _check_value_mismatch） | 🔴 待实现 | plans/2026-07-16 |
| FL-025 | 1.2 完整 | 类别生命周期无接口，只能手改 framework.yaml | 🔴 待实现 | plans/2026-07-13 |
| 目录式清单 | 1.4 完整 | export --outline / facts_export(outline=)：全 slot + 一行 snippet 轻量目录——**已实现** | ✅ 已实现 | commit b627f69 |
| search 埋点/指标 | 5.1 可自证 | search 专项埋点 + by_slot_op 交叉表 / 空结果率 / search→get 转化率——**已实现** | ✅ 已实现 | commit b627f69 |
| 真源指针字段 | 4.1 可溯源 | SlotMeta 无 source-of-record 字段（结构性缺失，非"占比低"） | 🔴 待实现 | 本文核实 |
| 值失真对账 | 4.3 可溯源 | 源指纹已有，但 _check_value_mismatch 空壳、不覆盖人/agent 事实 | 🔴 半成品 | 本文核实 |
| 有效性测量（原"注入式演习"） | 5.3 可自证 | 结果层：T2 观测(读链路判A/B/C→采纳率)已落(core/eval_t2.py)；因果 T3a注入式/T3-turn配对消融未建；长程整会话消融判不可测 | 🟡 T2 已落 · T3a/T3-turn 未 | plans/2026-08-12 · S0/S1 spec 2026-08-13 |
| scan-integrity 回连 slot | 2.3 当前 | 源哈希只服务扫描增量，未回连 slot（→ 并入 FL-027） | 🟡 部分 | 本文新登记 |
| FL-022 | 3.6 一致 | 并发底座：per-slot revision / compare-and-set / delta / 依赖冲突浮现（P0 地基） | 🔵 roadmap | plans/2026-07-06 |
| delta 水位线 v1 | 2.4 当前 | 无状态水位线 delta export（解 export 反复污染）——**已实现** | ✅ 已实现 | commit 86de58c |
| FL-021 L3 | 2.4/4.4 当前+可溯源 | 精确 delta（FL-022 报增删）+ export bootstrap 语义 + 文档式真源（承重墙） | 🔵 roadmap | plans/2026-07-05/06 |
| 网状可视化 | 3.4 一致（归属待定） | 交互式依赖图前端（拖拽/点击节点看信息）；通过身份测试但 FL 无前端，内建 vs 独立 viewer 待定 | 🔴 待议 | 本文新登记 |
| FL-024 | （协作 state） | 角色记忆系统（参考态、append-only 索引，P1，设计已固化） | 🔵 roadmap | plans/2026-07-06 |
| FL-023 | （协作 state） | warden 审查角色（只标记不回退，P2） | 🔵 roadmap | plans/2026-07-06 |
| 冷热分层 | （协作 state） | 具体层 transcript 冷热存储分层（P3 · later） | 🔵 roadmap | plans/2026-07-06 |

> 注：FL-026（MCP `facts_add` 对等）已实现，不再是缺口——它曾是 1.2 分支下"MCP 只能改不能加"的对等性缺口，现已闭合。
>
> **值失真对账 / scan-integrity 回连 slot 两行同属 FL-027 的"失真"半边**：与"内外对账"共用一次遍历、一个机制（交接稿 §三.5 明确要统一），不重复立项。
>
> **⚠️ 两类不同性质的边界置疑，勿混淆：**
> - **FL-023 / FL-024 / 冷热分层 —— 违反四属性**：它们服务"多持久角色协作的 state / 记忆"，而角色记忆**明确是参考态、永不作真源**（plans/2026-07-06 §四）。按 philosophy §二"每个功能只为守四属性之一"的准绳，它们要么另找归属、要么须说明 FL 的边界是否已从"事实地面"扩张到"协作 state 底座"——是真开发需求，但**本质不一定该由 FL 做**。philosophy 重写必须界定，不可默认属 FL 核心。
> - **网状可视化 —— 不违反四属性，是表面积问题**：它只渲染已有的边（通过身份测试：不存新事实、不推理），需求也真、且服务"一致/可审计"。争议只在 FL 至今无前端——"富前端内建于 FL" vs "FL 暴露图数据、独立 viewer 渲染"。未定前不给 FL 编号。
>
> **本文核实过程中发现的 philosophy↔code 漂移（供 philosophy 重写时校正）**：philosophy §三/§四把 `source-of-record`、`derived_from`、"slot 指向文档的边"当作 FL 既有能力来叙述，但数据模型（`SlotMeta` / `DependencyTarget`）中**均不存在**——真源指针无字段、依赖边只能 slot↔slot。philosophy 描述的是**目标态**而非现状，重写时应明确区分"已实现的地面"与"设计意图"，否则读者会误以为可溯源已成立。

---

## 与 philosophy 的边界（务必不越界）

- 本文**不**论证 FL 为什么必然存在、为什么随 agent 进步而增值——那是 philosophy §一。
- 本文**不**引入任何"存储文档内容"或"从已有事实推理出新事实"的需求——philosophy §七的唯一约束在此同样是硬边界。若某条需求要求 FL 去推理或存正文，它属于另一个工具，不该出现在这棵树里。
- 本文的每一条需求，都必须能对应到 philosophy 的四属性之一（或可自证元需求）。**挂不上四属性的需求，本身就是设计错误的信号。**
