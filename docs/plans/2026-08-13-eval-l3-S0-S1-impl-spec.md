# eval-L3 结果层 —— S0 + S1(T2 观测)实现 spec

- 日期：2026-08-13
- 分支：`feat/eval-l3-results-layer`（从 main `6c94fb0` 开出）
- 上游设计：`docs/plans/2026-08-12-eval-effectiveness-measurement.md`（框架）；口径见 FL `decisions.eval-effectiveness-scope`
- 归属：`requirements-need-to-code.md` §5.3 结果层（当前 🔴 空叶子，本次填 T2 部分）
- 角色分工：本 spec 作者负责**规划 + 验收**；另一 agent 负责**实现**（sealed-TDD）
- **本次范围：仅 S0 + S1。** S2(T3a) / S3(T3-turn) / S4(留白守卫) 不在本次，勿提前实现。

> 本 spec 力求自洽：脱离对话单读也能无歧义复现。术语与口径以上游设计稿 + FL 决策槽为准，本文不复述已声明事实，只给实现约束。

---

## 0. 一句话目标

在已建的 L1(access log)/L2(transcript trace)之上，新增**结果层**的第一块：**T2 观测** —— 用 LLM 回看真实链路，把每一次 FL 读判成 A/B/C，产出"事实被正确采纳"的采纳率。**不做因果消融**（那是 S2/S3）。

**A/B/C 语义（唯一权威定义，来自设计稿 §2）：**
- **A 消费并有用**：查 FL 拿到事实 → 直接用了。（唯一算正效）
- **B 消费但白用**：查 FL → 没拿到/不信 → 又去 bash/读源重取同一信息。（负效：计数+1 实际白绕）
- **C 自我维护**：读 FL 是为了写 FL（改前核对 slot 存在性/类型、覆盖审计、export 当背景）。（与"知识供给有效"无关，单列剔除）

---

## 1. 红线 / 不变量（验收硬卡，违反即打回）

1. **禁 regex 代理判定**：A/B/C 必须由 LLM 读证据（含推理文字）得出，不得用字符串/正则匹配 reasoning 来分类。已两次栽在启发式代理（设计稿 §2）。
2. **证据必须含决定性 reasoning 跨度**：抽取器要纳入 FL 读 step **前后相邻的 reasoning step**，不能只取读 step 自身的 rationale/conclusion —— 决定性信号常在旁边那句。cheap 抽取丢了它，proxy 错误就在抽取边界复活。
3. **判定幂等缓存**：按 `event_id` 判一次、缓存；重跑命中缓存不重新调 LLM。结果 append-only。
4. **不破坏读路径**：T2 是独立命令，绝不接进 get/list/export 热路径；LLM 后端失败要优雅降级（该 event 标 unjudged，不 crash、不影响其它）。sail 沿用 access_log 的 best-effort 不变量精神。
5. **T1 ≠ T2**：报告里 `fl_ratio` 等计数（T1 相关）不得当采纳率/有效性呈现；T2 采纳率与 T1 计数必须分栏、措辞区分（设计稿 §0 教训）。
6. **fl_return 留空**：已定（选 1）证据包不取 FL 返回原值，靠 reasoning span + 下游动作判定；`fl_return` 字段保留但本次不填充。

---

## 2. S0 —— 结果层数据模型 + 存储底座

**新文件 `src/fact_layer/models/eval_results.py`**（不污染现有 `models/eval.py`）。

```
ABCVerdict = Literal["A", "B", "C", "unknown"]

EvidenceBundle:
    event_id: str          # 稳定键，见下
    session_id: str
    turn: int
    step_index: int
    slot_ref: str | None    # 被查的 slot/category（facts_get/list），search/export 可为 None
    tool: str               # facts_get / facts_list / facts_search / facts_export
    query: dict             # 该读 step 的 args
    fl_return: None         # 本次固定 None（选 1，字段保留待后续增强）
    reasoning_span: list[str]   # 读 step 前后相邻 reasoning step 的文本（含读 step 自身 rationale/conclusion）
    downstream_actions: list[dict]  # 读之后的后续 tool_call 摘要（tool + args 摘要），用于识别 B（回退重取）
    trace_ref: str          # 来源 trace 文件名，便于溯源

ABCJudgement:
    event_id: str
    verdict: ABCVerdict
    rationale: str          # LLM 判词（为什么判这个）
    confidence: float | None
    judged_at: str
    judge_model: str | None

T2Report:
    total_reads: int                 # 抽出的 FL 读事件总数
    judged: int                      # 已判数
    coverage: float                  # judged / total_reads
    by_verdict: dict[str, int]       # {A, B, C, unknown} 计数
    adoption_rate: float | None      # A / (A + B)，C 与 unknown 均剔除；分母 0 → None
    c_rate: float | None             # C / judged（自维护占比，单列参考，不并入采纳率）
    by_slot: dict[str, dict[str, int]]  # slot_ref -> {A,B,C,unknown}
    sampled: bool                    # 是否抽样
    sample_size: int | None
```

**`event_id` 生成**：`f"{session_id}:{turn:03d}:{step_index}"`（稳定、可读、幂等键）。

**存储**：
- 结果落 `.facts/eval/results/t2_verdicts.jsonl`，一行一个 `ABCJudgement`（append-only）。
- 加载时按 `event_id` 去重取最新（或建缓存 dict）；已判的 event 不重判。
- `results/` 目录不存在则创建；遵循与 `save_trace` 一致的 best-effort 写入风格。

**验收(S0)**：模型能表达 A/B/C+unknown 与采纳率口径；`event_id` 稳定;重复写同一 event_id 读回时幂等（取一条）；不碰任何读热路径。

---

## 3. S1 —— T2 观测层

### S1a 证据抽取（纯函数，`src/fact_layer/core/eval_t2.py`）

`extract_evidence(traces: list[EvalTrace]) -> list[EvidenceBundle]`

- 遍历每个 trace 的 steps，挑出 **FL 读事件**：`step.type == "tool_call"` 且 `step.tool in {facts_get, facts_list, facts_search, facts_export}`（或 `step.source == "fl"` 的 tool_call）。
- 对每个读事件组 `EvidenceBundle`：
  - `reasoning_span`：**读 step 自身的 rationale/result_used_for/conclusion + 其前后相邻的 `type=="reasoning"` step 文本**（相邻窗口，建议前后各 1–2 个 reasoning step，或到下一个 tool_call 为界）。这是红线 2。
  - `downstream_actions`：读事件之后、到该 turn 结束（或下一个 FL 读）之间的 tool_call step 摘要 —— 尤其 bash/read/grep（用于让裁判识别 B：读后又去源头重取）。
  - `query = step.args`；`slot_ref` 复用现有 `_extract_slot_ref` 逻辑（facts_get/list 从 args.slot/category）。
- 纯函数、无 IO、无 LLM，便于 sealed-TDD。

### S1b LLM 判定（`core/eval_t2.py`）

`judge_evidence(bundle, *, backend) -> ABCJudgement`

- 复用现有 LLM 后端（`facts_audit`/`facts_scan` 走的 config 角色与 model 解析）。判定 prompt 要点：
  - 给出 A/B/C 精确定义（§0）+ 证据包（query / reasoning_span / downstream_actions）。
  - 要求结构化输出 `{verdict, rationale, confidence}`；rationale 说明判据。
  - 明确指示：**B 的信号 = 读后又去 bash/读源重取同一信息**；**C 的信号 = 这次读服务于随后的写 FL / 覆盖核对**。
- **幂等缓存**：判前查 `t2_verdicts.jsonl`，`event_id` 已有则直接返回缓存，不调 LLM。
- **降级**：后端异常 → 返回 `verdict="unknown"` 的 judgement（记 rationale=错误摘要），不抛。
- **禁 regex**（红线 1）：verdict 只能来自 LLM 输出解析。

`judge_all(bundles, *, sample=None, backend) -> list[ABCJudgement]`：支持 `sample=N`（随机抽 N 个估率）或全量；跳过已缓存。

### S1c 聚合 + 出口

- `compute_t2_report(judgements, total_reads, *, sampled, sample_size) -> T2Report`：按 §2 口径算 `adoption_rate = A/(A+B)`、`c_rate`、`by_slot`、`coverage`。
- **CLI**：`fl eval effectiveness`（子命令挂在现有 `fl eval` 下）。flags：
  - `--session <glob>` / `--after <date>`：筛 trace（复用 `load_traces`）。
  - `--sample N`：抽样估率；缺省全量。
  - `--dry-run`：只抽证据、不调 LLM（打印将判的 event 数与证据规模，供成本预估）。
  - 输出：先印 T1 计数区（复用现有 stats，标注"相关，非有效性"），再印 T2 采纳率区，两区分栏。
- **MCP**：`facts_eval_effectiveness` 工具，参数与 CLI 对等，返回 `T2Report` 的 dict。

**验收(S1)**：见 §5 清单。

---

## 4. 完成后必做的文档同步

- `docs/README.md` §3 & §4：把 eval-L3 / T2 状态 🔴 → 🟡（T2 落地、T3 未做）。
- `docs/requirements-need-to-code.md` §5.3：把 T2 叶子从空 → 钉到 `core/eval_t2.py` 的函数锚点；缺口表更新。
- FL `work-in-progress` 槽：刷新 focus/next-steps（用 CLI `fl` 从本仓跑，MCP 指向贷后催收，勿混）。**不写进度到稳定 FL 槽。**

---

## 5. 验收清单（作者按此逐条核，全绿才放行 S2）

- [ ] **A/B/C 无 regex**：读判定代码路径，verdict 来自 LLM 输出，非字符串匹配 reasoning。
- [ ] **决定性 span 用例**：一个 sealed 测试，决定性信号只在**相邻 reasoning step**（不在读 step 自身字段）；抽取器纳入它。若人为删掉相邻 span，测试能证明判定会退化（编码红线 2 的教训）。
- [ ] **A/B/C 三语义各有测试**：A(用了)/B(读后 bash 重取)/C(读为写) 各一条，判定正确。
- [ ] **采纳率口径**：`adoption_rate = A/(A+B)`，C 与 unknown 剔除；`c_rate` 单列；分母 0 → None。
- [ ] **幂等缓存**：用 stub LLM 计调用次数，判两遍第二遍命中缓存、0 次新调用。
- [ ] **降级不 crash**：stub 后端抛异常 → 该 event 判 unknown，其余不受影响，命令正常退出。
- [ ] **T1/T2 分栏**：报告不把 fl_ratio 当采纳率；措辞区分"相关 vs 观测"。
- [ ] **读路径零改动**：get/list/export 热路径无改动；T2 全在独立命令内。
- [ ] **sealed-TDD**：RED→GREEN 记录；LLM 在测试中被 stub（无 live 调用）；现有测试保持绿（基线 501 passed）。
- [ ] **CLI/MCP 对等**：同筛选参数下两者报告一致。
- [ ] **`fl check` 干净**；文档 §4 同步完成。