# FL 查询模型重构 + export 缺陷修复

- 日期：2026-07-05
- 状态：设计讨论 → 待实现
- 涉及：`FL-020`（export 缺陷，bug）、`FL-021`（查询模型：条式 vs 文档式，设计增量）
- 触发：dogfood 项目「贷后催收匹配」中，agent 反复调用 `facts_export` 却拿不全上下文，且无法建模逻辑链路。

---

## 一、背景与问题陈述

agent 目前把 `facts_export` 当成"获取全量上下文"的入口，实际暴露出两个层面的问题：

1. **export 拿不全、且重复无意义**：agent 频繁 export，但每次返回内容一致且不完整 → 污染对话、无增量价值。
2. **get 无法建模逻辑链路**：`facts_get` 要求调用方**预先知道某条事实存在**（发现问题），且返回的只是一条孤立数据，**无法表达"A 决策牵动 B/C 事实"这类推理链路**。

根因是 FL 现在用**同一套机制（slot + get/export）**处理了两种本质不同的数据。

---

## 二、FL-020：export 静默丢弃未登记类别（确认为 bug）

### 现象
dogfood `.facts/` 有 8 个已启用类别、42 槽位全填，但 `facts_export` 输出**完全不含 `user-profile` 类别**（9 个已填槽位全部消失）。

### 根因
`core/exporter.py` 的 `build_export_context()` 只遍历一个**硬编码白名单** `CATEGORY_ORDER`，`CATEGORY_TITLES` 同样是硬编码 dict：

```python
CATEGORY_ORDER = ["project-overview","tech-stack","architecture","conventions",
                  "work-in-progress","decisions","data-model","api-contracts",
                  "testing","build-deploy","security"]
# for cat_name in CATEGORY_ORDER:
#     if cat_name not in categories or cat_name not in enabled: continue
```

`user-profile` 既不在 `CATEGORY_ORDER` 也不在 `CATEGORY_TITLES` 里 → 任何**不在这两个硬编码列表中的扩展/自定义类别都会被静默丢弃**。framework.yaml 允许启用任意扩展类别，但 exporter 对此一无所知。

### 修复方向
- export 遍历 `enabled` 全集，而非硬编码 `CATEGORY_ORDER`；`CATEGORY_ORDER` 退化为"排序偏好"，未登记类别按 tier 追加在后。
- 标题走 `CATEGORY_TITLES.get(name, _slot_display_name(name))`（fallback 已存在，只是取不到）。
- 加回归测试：启用一个白名单外的扩展类别，断言 export 含其槽位。

### 关联缺陷
`build_budgeted_context()`（带 token 预算的 export）直接调用 `build_export_context()`，**继承同一丢弃行为** → 预算路径也看不到 user-profile 类。修 `build_export_context` 即可一并解决，测试需覆盖两条路径。

另注：`build_budgeted_context` 用 `display_name.lower().replace(" ", "-")` 反推 slot_id，对含下划线的 slot 会反推失败（打分时 `updated` 取不到、退化为 None）。当前 dogfood 槽位均用连字符，暂未触发，但属隐患。

### 风险
低。纯补全遗漏，不改已有类别的输出格式。

---

## 三、FL-021：区分「条式数据」与「文档式数据」的查询模型

### 核心区分

| | 条式数据（现擅长） | 文档式数据（现缺失） |
|---|---|---|
| 形态 | 原子事实：枚举值、字段定义、单条决策 | 推理链路：为何 A→B→C、跨槽位论证 |
| 例子 | `situation=1/9/11/14=接通` | "为何选 Two-Tower，它约束哪些下游" |
| 正确访问 | 精确 get（但需先知存在） | 图遍历 / 叙事，非原子 get |

FL 里**已埋了链路的边**却没暴露给查询层：`decisions.affected-slots`、`dependencies.yaml`（derives-from / constrains / references / implies / conflicts-with）。get 只返回单点、export 只拍平快照，**没有任何工具沿这些边遍历**。

### 三个真实缺口

1. **发现（discovery）**：get 需预知 slot 名，否则只能靠 export"看有什么"，而 export 又不全 → 恶性循环。
2. **链路（chain）**：无工具沿 dependencies + affected-slots 遍历，无法把"一条决策牵动哪些事实"作为链返回。
3. **污染（pollution）**：export 被当成发现机制反复调用；它应只做**一次性 bootstrap**，日常由 search + get + trace 承担。

### 分层方案（便宜 → 根本）

- **L0 / FL-020**：修 export 遍历全集（见上）。立即见效、风险最低。
- **L1 发现**：新增 `facts_search(keyword)`，跨 slot-id / value / reason 检索，返回命中的 slot ref + 摘要。让 get 不再需要预知。
- **L2 链路**：新增 `facts_trace(slot)`，沿 dependencies + `decisions.affected-slots` 遍历，输出推理链（`impact_cmd.py` 已有下游遍历的一半基础，可复用/扩展）。
- **L3 污染 / 文档式**：export 定位为 bootstrap-once + delta 感知（"自上次无变化"不重复吐全量）；评估是否给"文档式事实"一个一等公民类型，与原子 slot 区分存储与查询。

---

## 四、待办（roadmap）

- [x] **FL-020**：exporter 遍历 enabled 全集 + fallback 标题 + 回归测试。✅ 已完成（commit 见下）。
  - 关键修正：`user-profile` 是**项目自定义扩展**（包无模板、不在 CATEGORY_ORDER），故不把它硬编码进包，改为通用兜底：`build_export_context` 遍历 `enabled` 全集，未登记类别按 tier 追加，标题走 `_slot_display_name` fallback（"user-profile" → "User Profile"）。
  - 回归测试：自定义扩展被导出 + 从 CATEGORY_ORDER 移除仍导出。全量 415 passed。
- [ ] **FL-021 L1**：`facts_search` — CLI + MCP tool + schema + 测试。
- [ ] **FL-021 L2**：`facts_trace` — 复用 impact 遍历，双向（上游依赖 + 下游影响 + affected-slots）+ 测试。
- [ ] **FL-021 L3**：export bootstrap/delta 语义；文档式事实类型评估（需单独设计稿）。

## 五、开放问题

- L3 的"文档式事实一等公民"是否值得做，还是用 L2 的图遍历 + 现有 decisions 叙事字段已足够？（倾向先做 L1/L2，用真实使用反馈再决定 L3）
- `facts_search` 是否需要 LLM 语义检索，还是关键词/子串匹配即可起步？（倾向先做无 LLM 的子串+字段名匹配，零依赖、可离线）
