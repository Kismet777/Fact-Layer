# Session 交接稿（新 session 从这里接手）

- 日期：2026-07-14
- 用途：本 session 的工作交接给下一个 session 继续。自包含。
- 记忆入口：[[project-fl-tool-evolution]]（自动加载）指向本稿。

---

## 一、使命（两条线）

1. **FL 工具自身的演进**（本仓 `fact-layer`）：把 FL 从"无状态快照底座"演进为"版本化 + 可回退 + 文档式真源 + 溯源一致"的底座；补齐接口缺口；写好思想/需求文档。指导思想见 `docs/architecture-philosophy.md`（**注意：该文档质量仍不达标，待重写**）与 `docs/plans/2026-07-06`、`2026-07-05`、`2026-07-13`。
2. **贷后催收项目的 FL 维护**（`.facts/` 治理）：2026-07-09 治理交接稿已执行完（见下）；真值以该项目 FL 的 `work-in-progress` 为准。

核心不变量（判断任何 FL 改动是否走歪）：**每个功能只为守"完整/当前/一致/可溯源"四属性之一而存在；不引入"文档内容存储"或"推理"。**

---

## 二、本 session 已完成

### 贷后催收 FL 治理交接（2026-07-09 稿）已执行
- 新建 17 slot：`data-model` 6 枚举 + `table-metrics-daily`；`decisions` dec-007~010；`architecture` P 系列 5 条 + capacity-model；`conventions.enum-contract-governance`。
- 更新 5 slot：DEC-006（全量+10% holdout，灰度不可行）、DEC-001（34→15）、architecture.ab-test/layers/self-built-db-tables。
- `facts_check`：0 errors（仅遗留 staleness 告警，非本次造成）。
- 详见该项目 FL `work-in-progress.next-steps`。

### 两个 FL 工具 bug 已修 + 测试（但**未提交**，见 §四）
- **FL-026**：`mcp_server.py` 加 `facts_add`（MCP 此前只能更新、不能新建 slot——这是前任 agent 误判"不能建 dec-007"并覆盖 dec-006 的根因）。+3 测试。
- **Bug B**：`exporter.py` budgeted export 不再从 display_name 反推 slot_id（下划线槽位曾 updated=None 被误判）；`_extract_active_slots` 携带真实 `slot_id`。+1 测试，已验证退回 bug 会变红。
- 全量 **421 passed**。

---

## 三、待办（新 session 按此推进，优先级见标注）

### 文档类
1. **【高】写 FL 需求文档**（新增，用户明确要）——一份**树形 need→code 溯源**文档，实用视角，与 philosophy（灵魂/动机）互补。规格：
   - **根（最抽象）**：agent 长线开发下项目事实不够稳定——同时存在**多重备份、带延迟的不一致、相关信息缺失**——为解决此，才有 FL。（个人动机不进此文档，留 philosophy。）
   - 逐层具体化，每子需求派生实现，每叶子**钉到具体代码**。示例分支：让 agent 易用→MCP；消除不一致→网状视图(dependencies+impact)+定期检查(fl check)；约束质量→初始化(fl init)+限制输入(schema 守卫)；读写事实→新增 slot(fl add / facts_add)、更新(fl set)、发现(facts_search 待建)。
   - **双重审计价值**：功能向上追不到需求=多余；需求向下是空叶子=缺口（如 facts_search 未建）。
2. **【中】重写 `docs/architecture-philosophy.md`**——用户评"仍写得很烂"。上一版已按 Diátaxis（explanation 类型，与 reference 分离）重构，但**结构验收未过**。原则：单一核心=必然性（接地成为瓶颈、真相在模型外、价值随 agent 进步而涨）；四属性为定义；正向表述边界（不写"它不是什么"，用不变量）；reference 内容移出。与需求文档划清职责（灵魂/动机 vs need→code）。

### 代码类（FL 演进 roadmap）
3. **FL-025** 类别生命周期接口（`fl category enable/add` + 对应 MCP）——本 session 暴露：**创建/启用类别无任何 FL 接口，只能改 framework.yaml**（铁律禁止），导致治理交接被迫把枚举塞进 data-model。详见 `docs/plans/2026-07-13-fl-interface-gaps.md`。
4. 更大的演进：FL-022 并发底座 / FL-021 L3 文档式真源 / FL-024 角色记忆 / FL-023 warden / 冷热分层——详见 `docs/plans/2026-07-06-multi-agent-state-and-memory.md`。
5. 文件真源漂移检测（uncontrolled external file）+ code↔FL 漂移对账——统一为一个机制，见 2026-07-06 稿与治理规则第 4 条。

### 贷后催收项目类
6. **【项目】复核并修正 `historical_max_overdue_days` 计算口径**：曾用 `customer_order WHERE status=5` 当"逾期中"，但 DDL 实为 `5=loaned`（见该项目 FL `data-model.enum-customer-order-status`），口径可能算错。

---

## 四、未提交状态（重要，勿误操作）

`fact-layer` 仓工作区**大量未提交**，分两类：

- **不是本 session 的**：一个进行中的 "LLM 统一调用重构"（`config.py`/`llm.py`/`auditor.py`/`scanner/*`/`codex_ingest.py`/`suggest_cmd.py`/`transcript_ingest.py`/`cli.py` + 各自测试 + `test_model_config_single_source.py`）。CLAUDE.md 注明其为 in-progress。**勿擅自提交或回退。**
- **本 session 的**（与上者在 `mcp_server.py`/`exporter.py` 里有文件级纠缠）：
  - `src/fact_layer/mcp_server.py`：新增 `facts_add`（其余 model=None 等属重构）
  - `src/fact_layer/core/exporter.py`：下划线修复（`_extract_active_slots` 加 slot_id + `build_budgeted_context` 用真 slot_id）
  - `tests/test_mcp_server.py`、`tests/test_budget_export.py`：对应测试
  - `docs/plans/2026-07-13-fl-interface-gaps.md`（新，可独立提）
  - `docs/plans/2026-07-14-session-handoff.md`（本稿）
  - `docs/architecture-philosophy.md`（**待重写，勿提**）

**未提交是有意的**：不把 bug 修复混进别人在飞的重构 commit。建议由人决定提交策略（或先 `git stash` 分离重构再单独提 bug 修复）。全量测试当前全绿。

---

## 五、操作注意

- **运行中的 `fl-mcp` 是旧进程**：需重启才会暴露新的 `facts_add` 工具，并使 `facts_set_batch`/`facts_audit` 的 `model=None`（走 config 策略、指向 deepseek）生效——否则 batch 自动 audit 会报 "claude-haiku 发到 deepseek 端点被拒"。
- **建新 slot 用 `fl add`（CLI）或 `facts_add`（MCP，重启后）**；`facts_set` 只更新既有 slot、对不存在的报 "slot not found"。
- 一切对 `.facts/` 的读写走 FL 接口，勿直接编辑。
