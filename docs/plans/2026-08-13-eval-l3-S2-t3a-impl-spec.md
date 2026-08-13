# eval-L3 结果层 —— S2(T3a 注入式演习)实现 spec

- 日期：2026-08-13
- 分支：从 main（含 S0+S1，HEAD `474f191`）开新分支 `feat/eval-l3-t3a-drill`
- 上游设计：`docs/plans/2026-08-12-eval-effectiveness-measurement.md`（§3 T3a 行 / §4 三堵墙 / §7② / §8 口径）
- 前置：S0+S1(T2 观测) 已落 main（`models/eval_results.py` / `core/eval_t2.py`）
- 归属：`requirements-need-to-code.md` §5.3 结果层 → T3a 叶子（当前 🔴）
- 角色分工：本 spec 作者负责规划 + 验收；另一 agent 负责实现（sealed-TDD）
- **本次范围：S2 = 完整 T3a 管线一次交付。** S3(T3-turn) / S4(留白) 不在本次。

> 自洽要求（守 CLAUDE.md 规则 0）：脱离对话单读也能无歧义复现。口径以设计稿 + FL `decisions.eval-effectiveness-scope` / `decisions.eval-two-arm-runner` 为准。

---

## 0. 一句话目标

T3a = **注入式演习**：把一条**合成事实**注入一个**隔离 FL**，构造一道答案已知(oracle)的题，让 agent 在 **有该 FL / 无该 FL** 两臂各答一次，对 oracle 打分 + 核算查询成本。它是设计稿 §4 三堵墙下**唯一能做干净因果**的一格。

**测什么（受限因果，设计稿 §8）：** ①**事实供给准不准** —— 有 FL 臂能否凭注入事实答对；②**省不省查** —— 有 FL 臂比无 FL 臂少翻多少源。
**明确不测 / 不外推：** "FL 整体价值"。报告必须显式标注"受限因果"，禁外推。

---

## 1. 架构：FL 建评测，不编排 agent（决策 `decisions.eval-two-arm-runner`）

- **FL 侧（本次全建）**：题/oracle 规格与存储 → 隔离 FL 注入 → ±FL 两臂上下文/prompt 生成 → 答案回填 → 对 oracle 打分 + 成本核算 → 报告。
- **人侧（手动触发）**：拿 FL 生成的 prompt，在一个真实 agent 里各跑一臂，把答案（及观察到的查询计数）贴回。
- **边界铁律**：FL **绝不** shell out agent、绝不编排执行流；它只生成上下文、收答案、打分。这不违背"管 state 不造 orchestrator"主线 —— 本质是**构建评测**。

---

## 2. 干净对照的三条硬前提（设计稿 §4 干净对照墙，验收硬卡）

1. **隔离 FL 只装本题注入事实**：注入写进一个 **temp 隔离 .facts**，**绝不碰真实项目 .facts**。因隔离 FL 只有本题事实，"无 FL 臂整个不可见 FL" = 精确抽掉这条知识（这正是用户选"整个不可见"在本设定下成立的原因）。
2. **注入事实必须是合成/新造的**：值不可由预训练或常识猜出（如虚构枚举/编号/命名），否则无 FL 臂会从上下文/预训练偷带答案 → 低估反事实差距。spec 的题库作者须保证这一点；实现侧提供校验点（见 §5 校验）。
3. **oracle 外部给定**：标准答案由出题人写死，**不得用 FL search/agent 自身产出反推**（防"用 search 自证 search"的循环）。

---

## 3. 数据模型（新文件 `models/eval_drill.py`）

```
InjectedFact:
    category: str
    slot_id: str
    value: <slot 值>
    reason: str | None

DrillTask:
    drill_id: str
    prompt: str                 # 抛给 agent 的题（问题/任务）
    injected_facts: list[InjectedFact]   # 注入隔离 FL 的事实（with-FL 臂可查到）
    oracle: str                 # 外部给定的标准答案（ground truth）
    scoring: Literal["exact", "normalized", "llm"] = "normalized"
    synthetic_check: str | None # 出题人对"值为何不可猜"的说明（§2.2 佐证）
    notes: str = ""

Arm = Literal["with_fl", "no_fl"]

ArmRun:
    drill_id: str
    arm: Arm
    answer: str
    fl_reads: int | None = None       # 人回填；缺 → None（不猜）
    source_lookups: int | None = None # 该臂为答题做的非 FL 源查询次数（bash/read/grep），人回填
    ran_at: str = ""
    notes: str = ""

DrillScore:            # 单臂对 oracle 的判定
    drill_id: str
    arm: Arm
    correct: bool
    score: float                      # exact/normalized→{0,1}；llm→0..1
    detail: str = ""

DrillResult:           # 一题两臂合成
    drill_id: str
    with_fl: DrillScore | None
    no_fl: DrillScore | None
    supply_accuracy: bool | None      # with_fl 是否答对（事实供给准不准）
    query_savings: int | None         # source_lookups(no_fl) − source_lookups(with_fl)；任一缺 → None

DrillReport:           # 跨题聚合
    total_drills: int
    scored_drills: int
    with_fl_accuracy: float | None    # with_fl 答对率
    no_fl_accuracy: float | None      # no_fl 答对率（对照）
    avg_query_savings: float | None
    positioning: str                  # 固定注入"受限因果：事实供给准不准/省不省查，不外推 FL 整体价值"
```

**存储**：
- 题库 `.facts/eval/drills/<drill_id>.yaml`（手工 authored，持久）。
- 臂结果 `.facts/eval/drills/runs/<drill_id>.<arm>.yaml`（人回填）。
- 与 T2 一致：best-effort 写入，不破坏调用方。

---

## 4. 命令管线（CLI + MCP 对等）

1. `fl eval drill new <drill_id>` —— 生成一份 `DrillTask` 模板（含 §2 三前提的填写提示），供人 authored。
2. `fl eval drill prepare <drill_id>` —— 产出两臂上下文：
   - **with_fl 臂**：建一个 temp 隔离项目目录（含 `.facts`），把 `injected_facts` 注入其中；输出「ready-to-run」包 = 任务 prompt + 给人的运行指令（如「在该 temp 目录内启动 agent 跑此 prompt，agent 可 `fl` 查到注入事实」）。
   - **no_fl 臂**：同一任务 prompt，但运行目录**无 FL**（空 temp 目录 / 无 .facts，`fl` 查不到任何东西）。
   - **绝不写真实 .facts**（§2.1）。
3. 人手动各跑一臂 → `fl eval drill record <drill_id> --arm with_fl|no_fl --answer <file|stdin> [--fl-reads N] [--source-lookups M]` 回填。
4. `fl eval drill score <drill_id>` —— 每臂 answer 对 oracle 判 correct（exact/normalized 纯函数；llm 判等价须走后端、可 stub）→ `DrillResult`。
5. `fl eval drill report` —— 跨题聚合 `DrillReport`，**首行强制打印 positioning 标注**（受限因果，禁外推）。
6. MCP：`facts_eval_drill_prepare / record / score / report` 与 CLI 对等（复用同一 orchestrator，参照 S1 的 `run_effectiveness` 单入口模式保证 parity）。

---

## 5. 红线 / 不变量（验收硬卡）

1. **对照干净**：隔离 FL 只装本题事实；no_fl 臂真无该 FL；注入事实合成不可猜；oracle 外部给定不自证（§2 三条）。
2. **不碰真实 .facts**：prepare/inject 只在 temp 目录；有测试证明真实项目 .facts 前后无变化。
3. **不编排 agent**：FL 只生成 prompt/上下文 + 收答案 + 打分；代码里无 subprocess 起 agent、无执行流编排。
4. **定位守卫**：`DrillReport.positioning` 固定为"受限因果…不外推 FL 整体价值"，report 首行必打印；有测试断言该措辞存在。
5. **不猜人工输入**：fl_reads/source_lookups 缺失 → None，不臆造；`query_savings` 任一臂缺 → None。
6. **打分可测**：exact/normalized 走纯函数 sealed-TDD；llm 判等价必须 stub，无 live 调用。

---

## 6. sealed-TDD 要求 + 验收清单（作者按此逐条核）

- [ ] **隔离注入不污染真实 .facts**：prepare 后断言真实项目 .facts 未变（用 tmp_path 构造真实/隔离两处）。
- [ ] **no_fl 臂真查不到**：在 no_fl 上下文里 `fl` 查注入 slot → 空/无。
- [ ] **合成事实校验点**：DrillTask 要求 `synthetic_check`；缺失或注入值疑似可猜时 `fl eval drill new/validate` 给出警告（不强制阻断，但显式提示）。
- [ ] **打分三态**：exact / normalized（大小写/空白归一）/ llm（stub 等价判定）各一条；correct 与 score 对应。
- [ ] **supply_accuracy / query_savings 口径**：with_fl 答对→supply_accuracy True；savings = no_fl.source_lookups − with_fl.source_lookups；缺臂/缺计数 → None（各一条）。
- [ ] **report positioning 强制标注**：report 首行含"受限因果…不外推"，测试断言。
- [ ] **不编排 agent**：grep 实现无 subprocess/exec 起 agent（人工触发边界）。
- [ ] **CLI/MCP 对等**：同 drill 两面报告一致（复用单 orchestrator）。
- [ ] **sealed-TDD**：RED→GREEN；LLM 全 stub；现有测试保持绿（基线 547 passed）。
- [ ] **`fl check` 干净**；文档 §3/§4 + 需求树 §5.3 T3a 叶子 🔴→🟡 并钉代码锚点；wip 槽用 CLI `fl` 刷新（进度类，勿写稳定 FL 槽）。

---

## 7. 交回要求

- 停在 `feat/eval-l3-t3a-drill`，**不合并不推送**，交回等验收。
- 简报：新增/改动文件、测试数变化、验收清单逐条自查、对 spec 的任何偏离与理由。
- 附一个**端到端跑通的示例 drill**（authored 一道合成事实的题 + 两臂 record 的样例命令），证明人工触发管线闭环（可用 stub answer 演示，不需真起 agent）。