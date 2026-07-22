# FL 演进：session-log 兄弟结构 + handoff 投影视图

- 日期：2026-07-17
- 状态：设计讨论（对抗式收敛后固化）→ 待细化实现
- 编号：`FL-024a`（FL-024 角色记忆「抽象层」的**去范围最小切片**，只服务「稳定 session 交接」）
- 依赖：`FL-021 L3`（外部文档指针 + 指纹）、现有 `decisions` 类别、现有 eval 层、现有 export 投影机制（`--outline`/`--since`）
- 触发：用户诉求收敛——不要多角色/persona apparatus，**只要稳定的 session 交接**。

---

## 零、一句话

交接需要的是**投影**，不是**新拷贝**。手写的 handoff 文档是 FL 之外的第二份拷贝 → 必然漂移、必然过期（正是 FL 要消灭的「多重备份 + 带延迟不一致」病）。解法：把交接做成对 FL 现有状态的**投影视图**，加一层**只存指针/指纹、不存正文**的 append-only session 索引。

> **本 spec 明确去掉的范围**：多持久角色模型、warden、persona/人格、权限强制。那些是 FL-023/FL-024 全量，本切片不碰。

---

## 一、交接 = 三样东西，两样 FL 已有

| 交接内容 | 性质 | 归宿 | 现状 |
|---|---|---|---|
| 现在到哪 / 下一步 / 阻塞 | canonical 当前状态 | `work-in-progress`（focus/next-steps/blockers/recent-changes） | ✅ 已有，本 session 已在用它 bootstrap |
| 决策记录 | canonical 事实 | `decisions.*` | ✅ 已有一等公民；交接**引用**它，不抄内容 |
| 行为叙事（做了啥、为啥试了 X 又弃） | append-only 历史、参考态、**永不作真源** | 新增 `session-log` 兄弟结构 + drill-down 进 eval 具体层 | ⚠️ 唯一缺口，本 spec 要建 |

---

## 二、为什么 session 索引是「兄弟结构」而非 canonical slot

slot 受三套机制管，session 行为索引的形状与三套全部拧着：

| slot 的机制 | session 索引的形状 | 冲突 |
|---|---|---|
| staleness / tier 复核 | 不可变历史（上周做了啥永远是上周） | 复核=空转，且污染 staleness 告警 |
| 一致性 / 依赖图 | 无别的事实从它派生 | consistency check 对它空转 |
| canonical 集应「小而精」 | 随 session 单调增长、永不删 | 无界增长塞进本该小份的真值集；污染 completeness/填充率指标 |

**正确原语 = 与 `dependencies.yaml`、eval traces 并列的第三个兄弟结构**（都「归 FL 管、但不是 slot」）。这恰好是 FL-024 抽象层「每 session 一行索引」的最小版——设计上本就是兄弟结构。

---

## 三、`session-log` 结构（append-only，一行一 session）

落盘为 append-only 索引（形态参照本仓 harness 的 `MEMORY.md` 一行索引 / 记忆文件全文分层）。每条 = 一次 session 收尾追加，字段：

- `session_id` / `date`（date 传入，因脚本禁 `Date.now()`；实现侧由 CLI 取系统时间）
- `summary`：一行「干了什么」——**禁止段落级描述**（这是索引不是正文）
- `doc_ref`（可选）：指向外部行为记录文档的**路径 + 内容指纹（content_hash）**。
  - ⚠️ **只存路径 = 断根指针**。文档被移/改/删时，指纹让 drift 可探测（FL-021 L3 的指针模型）。
- `decision_refs`（可选）：引用的 `decisions.*` slot id 列表 = **slot 引用边**（FL 依赖图已能表达，不抄决策内容）。
- `slot_refs`（可选）：本 session 触碰的 slot id，供 drill-down。

不可变 + 永不删（append-only）：它是 eval 语料的索引，删索引 = 语料变孤儿。过期条目**不载入但不删除**。

**具体层 drill-down**：`summary` 是 eval 具体层（`fl eval` 的 L1/L2 trace，已有 rationale/source）的**物化投影**——同一条 append-only 事件流的两个分辨率，不是两份数据（两份必漂移）。需要细节从索引 drill 进 eval。

---

## 四、`fl handoff` 投影视图（只渲染、零新存储）

一次 bootstrap 读，把已有状态**拼装**成交接：

1. `work-in-progress`（当前 focus/next-steps/blockers）
2. open blockers 高亮
3. 最近 N 条 `session-log`（salience 或 recency 窗口，附 `[truncated: 还有 M 条未载入]` 信号——静默不载 = 伪装成完整的失忆）
4. 自水位线以来变动的 `decisions`（复用 export `--since` 的 watermark delta）

**身份测试**：它**不存任何新事实**，只渲染已有数据——与 `--outline`（本 session 已发）、`render_export_delta` 同物种，通过原则 2/7。

---

## 五、接口二元性（CLI + MCP 对等）

| 能力 | CLI | MCP |
|---|---|---|
| 追加一条 session-log | `fl session log`（收尾追加） | `facts_session_log` |
| 读 session-log（列表/drill） | `fl session list` | `facts_session_list` |
| 交接投影视图 | `fl handoff` | `facts_handoff` |

（具体命令名待实现时定；此处锁语义与对等性。）

---

## 六、边界与去范围

- **不存正文**：正文（完整行为记录文档）留在外部文件，FL 只存指针 + 指纹（原则 7 硬边界）。
- **不作真源**：session-log 是参考态，注入时打「参考·可能过期·真源以 FL 为准」标记（照抄 harness system-reminder 模式），不靠 agent 自觉。
- **跨项目已按 `.facts/` 目录分区**：贷后催收一份、fact-layer 一份。**同一 repo 内除非真出现第二条并行线，否则不加 per-topic 标签**（过度设计）。
- **不含** FL-023 warden / 多角色权限 / persona——那些属 FL-023/024 全量，本切片明确不碰。

---

## 七、待办（roadmap）

- [ ] `session-log` 兄弟结构落盘格式 + loader（append-only，永不删）
- [ ] `doc_ref` 指纹（content_hash）+ drift 探测（并入 FL-021 L3 的指针机制，勿另造一套）
- [ ] `decision_refs` / `slot_refs` 走现有依赖边模型（`DependencyTarget`）而非新字段
- [ ] `fl handoff` 投影视图（拼装 work-in-progress + blockers + session-log 窗口 + decisions delta）
- [ ] CLI + MCP 双路对等（§五）
- [ ] 载入窗口的 salience vs recency + truncation 信号（复用 exporter 的 `_score_slot`/`[truncated]`）

---

## 八、开放问题

- session-log 落盘：独立 `session-log.yaml`（像 dependencies.yaml），还是直接复用 eval 层加一层物化索引？倾向后者（避免与 eval 具体层漂移），待实现时敲定。
- 窗口权重：直接复用 exporter `_score_slot`，还是 session 交接需独立权重（如「本 session 相关性」维度）。
- `doc_ref` 指纹的探测时机：接入 `fl check` staleness 主循环，还是独立 `fl session verify`。
- **bug 登记 = 同形兄弟结构**：诉求「存 bug 的位置、永不删、status 从『未修正』→『已修正』」与本 spec 的 session-log **是同一形状**（append-only、条目永不删、每条带**可迁移的 status 字段**）。按 §二 同理由**不该进 canonical slot**（staleness/一致性机制对它空转、无界增长污染指标）；现状最接近的 `work-in-progress.known-issues` 形状不对（可删的字符串列表、无 per-item status），soft-delete 机制对但作用对象是 slot 非 bug。候选落地 = 本 spec 的兄弟结构再加一个 `status` 字段的实例。⚠️ 边界待定：bug 更像 issue-tracker「运营追踪」而非「真值地面」，是否属 FL 需过身份测试。
- **统一 append-only-status 日志基座（跨切 roadmap，与 FL-028 §九 交叉引用同一条）**：`session-log`（本 spec）+ `bug-log`（**FL-028**，docs/plans/2026-07-17-bug-log-defect-knowledge.md）+ warden 判定（旧 plan 2026-07-06 §三）**三者同形**（append-only + 永不删 + 可选 mutable status；status 为 bug/warden 实用、session-log 退化）。
  - **次序（rule of three）**：**先各自落地 session-log 与 bug-log，让共性从能跑的实现里浮出来；待 warden（第三消费者）真要上时再正式抽取基座**（候选 = 把现有 eval 层泛化一层——eval 本就 append-only）。自上而下预设基座，抽出来的形状八成错。与本节第一条「复用 eval 层」的落盘决策强耦合。
  - **纲领（贯穿两份 spec）**：**FL 只管理事实，不消费事实**——基座/日志层的职责到「存好 + 暴露好」为止，同类检测 / bug×eval 审 agent 等分析是 FL 之外的消费者。
