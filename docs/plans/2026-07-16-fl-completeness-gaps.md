# FL 内外完整性对账（need→code 溯源暴露）

- 日期：2026-07-16
- 状态：设计讨论 → 待实现
- 涉及：`FL-027`（内外完整性对账 = 缺失 + 失真的统一对账机制）
- 触发：撰写 `docs/requirements-need-to-code.md`（need→code 需求树）时，自顶向下审计"完整"与"可溯源"两条属性，暴露一个跨两属性、当前只有半成品的缺口。

---

## 编号勘误（本文首要记录）

撰写需求树初稿时，曾把两个功能误当"新项"各给了新编号，实为既有 roadmap 已规划：

- **facts_search**（按内容/语义发现事实）= **FL-021 L1**，规划于 `plans/2026-07-05-query-model-and-export.md`。**不是**新项（初稿一度误标 FL-027）。
- **facts_trace**（沿 dependencies + `decisions.affected-slots` 双向遍历推理链）= **FL-021 L2**，同一文档规划。需求树初稿**完全遗漏**了它，现已在 §3.4 补登记。

故本文只保留一个**真正的新项**，编号定为 **FL-027**（内外完整性对账）。FL-028 不启用。

---

## FL-027：内外完整性对账（"是否完整/是否失真"无统一机制）

### 现象
"FL 是否覆盖了外部真实存在、而应纳管的事实"（**完整**：缺失）与"FL 已有的事实是否还匹配它的源"（**可溯源**：失真）——两个问题目前都只有**半个**答案，且各自零散：

- 建设形态（缺失半边）：`fl scan` 的 `unmapped` 输出能报"外部存在、FL 未纳管"的候选（core/scanner/pipeline.py）。
- 校验形态：`fl audit --scan-integrity`（core/scan_integrity.py）报 orphaned / stale_source / cross_source_conflict。
- 失真半边**断链**：`scan_integrity._check_value_mismatch` 是空壳（载入 slot 值却不比对），"源变了 → 依赖它的 slot 值是否失真"没打通；且只覆盖经 `scan` 进来的事实，人/agent 声明的 slot 无任何源关联（`SlotMeta` 无真源指针字段，见需求树 §4.1）。

三处（scan unmapped / scan-integrity / value-mismatch）本是同一件事的碎片，缺一个把"应有事实全集 vs FL 现状"整体比对、给出"缺了哪些 + 漂了哪些"的机制。

### 修复方向
- 与交接稿 §三.5、`plans/2026-07-06-multi-agent-state-and-memory.md` 的"文件真源漂移检测 + code↔FL 漂移对账"**统一为一个对账机制**，不各做一套。
- 该机制一次遍历同喂两条属性：**完整**（外部有、FL 没有 = 缺失）与**可溯源**（FL 有、源已变 = 失真）——需求上两条、实现上共用。
- 先补 `_check_value_mismatch`：抽取记录值 vs 当前 slot 值不一致即产 finding。
- 前置依赖：人/agent 声明的事实要能参与失真对账，需先给 `SlotMeta` 加 source-of-record 指针字段（需求树 §4.1 的 🔴，可溯源前置）。
- 对账结果只作**候选/差异报告**提交人或 agent 确认后经声明入口落地，不自动改写事实（守 philosophy 原则 2：核实不推理）。
- 度量侧：把"事实缺口率"（需要而 FL 没有、被迫现推的次数）接入 eval（需求树 §5.3），使"是否完整"成为可测数字。

### 与四属性的关系
主服务**完整**（完整性层，需求树 §1.5），兼服务**可溯源**（失真半边，§4.3）。通过 philosophy §七身份测试：产出待确认候选与差异报告，不合成事实、不存正文。

---

## 待办（roadmap）
- [ ] **FL-027**：与 2026-07-06 的漂移对账统一设计后实现。先补 `_check_value_mismatch` + 给 `SlotMeta` 加真源指针字段（小、解真痛），再做全集对账 + 事实缺口率度量。

## 备注
- 需求归属与 need→code 溯源见 `docs/requirements-need-to-code.md` §1.5 / §4.1 / §4.3 / §5.3 及文末缺口登记表。
- facts_search（FL-021 L1）、facts_trace（FL-021 L2）的实现规划见 `plans/2026-07-05-query-model-and-export.md` §三。
