# FL 演进：bug-log 缺陷知识层

- 日期：2026-07-17
- 状态：设计讨论（对抗式收敛后固化）→ 待细化实现
- 编号：`FL-028`
- 依赖：`FL-021 L3`（代码锚点指针 + 指纹）、现有 `decisions` 类别、现有 eval 层、现有 export/search 投影机制
- 姊妹：`FL-024a`（session-log + handoff）——同为 append-only 兄弟结构，共享形状（见 §九）
- 触发：审代码时需知「这块以前有过什么 bug、怎么修的」；后期用 bug × eval 反查 agent 行为、调优 agent 系统。

---

## 零、纲领（一句话，governing principle）

> **FL 只管理事实，不消费事实。**

FL 的职责到「把缺陷记录**存好 + 暴露好**（四属性：完整/当前/一致/可溯源）」为止。**同类检测、bug×eval 反查 agent、调优**——都是**消费者**，不在 FL 职责内（§六）。这条线决定了本 spec 的一切取舍：store 做小、refs 做富、分析不进 FL。

---

## 一、需求（真实用途，全部来自用户）

1. **评审上下文**：审代码时知道「这块以前有过什么 bug、我们用什么方式处理的」。
2. **同类缺陷检测**：查与某 bug 同类型的其他内容。
3. **bug × eval 反查 agent**（大后期）：用 bug 历史反过来审查 agent 行为上的问题，和 eval 一起对 agent 系统调优。

用途 3 落在 FL 的 **§5 可自证/eval** 地界——是 bug-log 归属 FL 的最强论据（不是「它是日志」，而是它的**用途**接自证层）。

---

## 二、边界：缺陷**知识层**，不是缺陷**工单层**

| 属于 FL（知识/历史层） | 不属于 FL（工作流层） |
|---|---|
| bug 是什么、在哪、怎么修的、属哪一类 | 谁负责、指派、优先级、sprint |
| status：未修正→已修正 | 看板列、流转审批 |
| 引用：代码锚点 / eval trace / decision | 通知、评论线程 |

守住左列 = FL；滑向右列 = GitHub Issues 劣质复制，不是 FL 该做的。

**为什么不进 canonical slot（同 FL-024a §二理由）**：append-only 历史，staleness/tier 复核对它空转、一致性检查空转、无界增长污染 completeness 指标。正确原语 = 与 `dependencies.yaml`、eval traces 并列的**兄弟结构**。

---

## 三、store 结构（小，append-only，永不删）

每条缺陷记录：

- `bug_id` / `date`（date 由 CLI 取系统时间；脚本禁 `Date.now()`）
- `what`：一行缺陷描述（禁段落——正文/复现细节 drill 进 refs 指向的 eval/文档）
- `where`：代码锚点 + **content_hash**（见 §五；只存 `file:line` = 断根）
- `how_fixed`：一行处理方式（禁段落）
- `class`：缺陷类别标签（供同类检测的下游消费者用；FL 只存标签不做聚类）
- `status`：见 §四
- `refs`：**富引用**——eval trace id（哪个 session/turn 引入或修复，用途 3 的钥匙）、`decisions.*` slot（走依赖边模型）、可选 session-log 条目

**append-only 永不删**：它是缺陷历史 + agent 审计语料，删了无法复查、无法反查 agent。过期记录**不载入但不删除**。

---

## 四、status 生命周期

最小：`未修正(open) → 已修正(fixed)`。
可选扩展（待定，勿默认建）：`已知不修(wontfix)` / `复发(regressed)`。状态是 mutable 字段（条目不删、状态可迁移）——这是与 session-log 的关键差异（session-log 的 status 退化，bug-log 实用）。

---

## 五、代码锚点指针 + 指纹（FL-021 L3）

`where` 指向代码位置，而代码会移/改/删 → **指针会失真**。只存路径 = 断根悬空指针。必须存**锚点 + content_hash**，代码变了能探测该 bug 记录的位置指针失真（并入 FL-021 L3 的指针机制，勿另造一套）。探测时机：接入 `fl check` staleness 主循环，还是独立命令，待定（同 FL-024a §八）。

---

## 六、消费者（明确在 FL **之外**——纲领 §零的落地）

以下**不是 FL 的职责**，FL 只提供 data + 富 refs + 读接口（get/search/export）来**使它们可能**：

- **同类缺陷检测**：跑在 `class` 标签 + `what` 文本上的聚类/检索（消费者自建，或复用 `facts_search`）。
- **bug × eval 反查 agent + 调优**：关联 bug 的 `refs`（eval trace）与 eval 语料，找 agent 失败模式。这是独立分析能力，与 `fl eval stats` 同层但不同工具。

FL 不做聚类、不做 agent 调优判断。**FL 管理事实，不消费事实。**

---

## 七、接口二元性（CLI + MCP 对等）

| 能力 | CLI | MCP |
|---|---|---|
| 登记一条 bug | `fl bug log` | `facts_bug_log` |
| 改状态（open→fixed） | `fl bug resolve` | `facts_bug_set_status` |
| 读/列/drill | `fl bug list` | `facts_bug_list` |

（命令名待实现时定；此处锁语义与对等性。改状态**只改 status 字段、条目永不删**。）

---

## 八、待办（roadmap）

- [ ] bug-log 兄弟结构落盘格式 + loader（append-only，永不删，status 可迁移）
- [ ] `where` 代码锚点 + content_hash + drift 探测（并入 FL-021 L3）
- [ ] `refs` 走现有依赖边模型（`DependencyTarget`）指向 decisions / eval trace / session-log
- [ ] status 迁移接口（open→fixed），条目不删
- [ ] CLI + MCP 双路对等（§七）
- [ ] （下游、非 FL）同类检测 / bug×eval 审 agent —— 记为消费者，不在本 spec 实现范围

---

## 九、开放问题 + 跨切引用

- **落盘归属**：独立 `bug-log.yaml`，还是复用/泛化 eval 层？与下方「统一基座」决策强耦合。
- **统一 append-only-status 日志基座（跨切 roadmap）**：`session-log`（FL-024a）+ `bug-log`（本 spec）+ warden 判定（旧 plan 2026-07-06 §三）**三者同形**（append-only + 永不删 + 可选 mutable status；status 为 bug/warden 实用、session-log 退化）。
  - **次序（rule of three）**：**先各自落地 session-log 与 bug-log 两个具体实现，让共性从能跑的东西里浮出来；待 warden（第三消费者）真要上时再正式抽取基座**（候选 = 把现有 eval 层泛化一层）。自上而下预设基座，抽出来的形状八成错。
  - FL-024a §八 与本节交叉引用同一条。
- `class` 标签体系是否需要受控枚举，还是自由文本 + 下游聚类，待实第一批 bug 后定。

---

## 十、首批实录（2026-07-22 治理 dogfood 钓出，实现后作为种子数据导入）

> 这两条不是假想样例，是本 spec 讨论期间「手动跑一次 `fl check`+`fl audit`」真实钓出的 FL 工具自身缺陷。当前先寄存于 `work-in-progress.known-issues`，bug-log 实现后迁入。

| bug | what | where | how_fixed | class | status |
|---|---|---|---|---|---|
| B-001 | `fl check` 漏检悬空依赖边：边指向不存在的槽（`build-deploy.docker`、`tech-stack.framework`）是纯结构事实，却只有 `fl audit`(LLM) 抓到、`fl check` 报 0 errors | `core/checker.py` 依赖校验分支 | 待定（应在确定性 check 加「边 target 必须是已存在 slot」的校验，不劳 LLM） | 检查覆盖缺口 | 未修正 |
| B-002 | 无依赖边编辑接口：CLI/MCP 均无增/删/改 `dependencies.yaml` 边的命令 → B-001 的悬空边无法经 FL 接口修复，只能违铁律手改 | 缺失接口（editor 层无 edge op） | 待定（FL-025 类：补 `fl dep add/rm` + MCP 对等） | 接口缺口 | 未修正 |

**元观察**：B-001 + B-002 复合出一个尴尬——治理动作**发现了**不一致（悬空边），却**没有合规路径去修**（无编辑接口）。这本身是「能力×触发」之外的第三条：**发现 → 响应之间还得有可用的修复接口**，否则治理停在「看见但动不了」。
