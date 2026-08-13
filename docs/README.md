# fact-layer 文档地图（docs/ 索引）

这份文件是 `docs/` 的**入口与索引**。它**不复述任何事实**（守 FL 原则：不存正文、不复述已声明的事实），
只回答三件事:**从哪读起 / 什么查 FL、什么读 docs / 每份文档和每个 FL 编号是什么、什么状态**。

---

## 1. 从哪读起（新开发者阅读顺序）

1. [`../README.md`](../README.md) — FL 是什么、解决什么、`.facts/` 结构、命令（用户向,先建立直觉）。
2. **本文** — 文档地图 + FL-XXX 台账（知道有哪些设计、各在什么状态）。
3. [`requirements-need-to-code.md`](requirements-need-to-code.md) — **能力索引**：根需求 → 四属性 + 可自证元需求 → 每条能力落到 `code锚点`,末尾带缺口登记表。想知道"某能力有没有、在哪段代码",查这里。
4. 相关 [`plans/`](plans/) — 具体某功能的**设计理由与方案**（按需读，见 §4 清单）。
5. `fl export --stdout`（在 fact-layer 仓跑）— **项目当前真相**（当前进度/决策/架构事实,见 §3 平面桥）。

> `../CLAUDE.md` 是给接手 agent 的**操作规矩**（不是开发文档,但接手前必读）。

---

## 2. 两个平面:什么查 FL、什么读 docs（务必分清）

文档"数据"分两个平面,查错平面就会拿到过时或错误的东西:

| 你想知道… | 去哪 | 为什么 |
|---|---|---|
| **当前进度 / 下一步 / 阻塞** | **FL** `work-in-progress` 槽（`fl export`） | 进度真源在 FL,**不是** plans 里的 session-handoff（那些是时间点快照,已过期,见 §4🗄️） |
| **已定的架构/方案决策** | **FL** `decisions.*` 槽 | 决策的权威态在 FL |
| **项目事实**（架构/技术栈/数据模型/约定/枚举） | **FL** 对应类别槽 | 事实真源在 FL；docs 只引用不复述 |
| **某能力有没有、在哪段代码** | **docs** `requirements-need-to-code.md` | need→code 溯源树 |
| **某功能为什么这么设计** | **docs** `plans/<日期>-*.md` | 设计理由与取舍 |
| **FL 是什么 / 怎么用** | **docs** `../README(_CN).md` | 用户向介绍 |

---

## 3. 文档清单（docs/ 里每份是什么、什么状态）

状态图例:✅ 已实现 · 🟡 部分实现 · 🔴 待实现 · 🔵 roadmap · 📄 spec 待审 · 🗄️ 历史快照

| 文件 | 是什么 | 状态 |
|---|---|---|
| [`requirements-need-to-code.md`](requirements-need-to-code.md) | 需求树 + 缺口登记表（能力索引,持续更新） | ✅ live |
| [`plans/2026-06-12-scan-phase1.md`](plans/2026-06-12-scan-phase1.md) | `fl scan` 配置抽取器方案 | ✅ 已落地 |
| [`plans/2026-07-05-query-model-and-export.md`](plans/2026-07-05-query-model-and-export.md) | 查询模型重构 + export 缺陷（FL-020/021） | 🟡 L1 done · L2/L3 未 |
| [`plans/2026-07-06-multi-agent-state-and-memory.md`](plans/2026-07-06-multi-agent-state-and-memory.md) | 多角色协作状态底座 + 角色记忆（FL-022/023/024, FL-021 L3） | 🔵 roadmap |
| [`plans/2026-07-13-fl-interface-gaps.md`](plans/2026-07-13-fl-interface-gaps.md) | 接口完整性缺口（FL-025/026） | 🟡 026 done · 025 未 |
| [`plans/2026-07-16-fl-completeness-gaps.md`](plans/2026-07-16-fl-completeness-gaps.md) | 内外完整性对账（FL-027） | 🔴 待实现 |
| [`plans/2026-07-17-bug-log-defect-knowledge.md`](plans/2026-07-17-bug-log-defect-knowledge.md) | bug-log 缺陷知识层（FL-028） | 📄 spec 待审 |
| [`plans/2026-07-17-session-log-and-handoff-view.md`](plans/2026-07-17-session-log-and-handoff-view.md) | session-log 兄弟结构 + handoff 投影视图（FL-024a） | 📄 spec 待审 |
| [`plans/2026-08-12-eval-effectiveness-measurement.md`](plans/2026-08-12-eval-effectiveness-measurement.md) | eval 有效性测量结果层（充实需求树 §5.3） | 🟡 框架已定 · T2 观测(S0+S1)已落 · T3a/T3-turn 未 |
| [`plans/2026-08-13-eval-l3-S0-S1-impl-spec.md`](plans/2026-08-13-eval-l3-S0-S1-impl-spec.md) | eval-L3 结果层 S0+S1(T2 观测) 实现 spec | 🟡 S0+S1 已实现 · S2/S3/S4 未 |
| [`plans/2026-08-13-eval-l3-S2-t3a-impl-spec.md`](plans/2026-08-13-eval-l3-S2-t3a-impl-spec.md) | eval-L3 结果层 S2(T3a 注入式演习) 实现 spec | 📄 spec 已写 · 待实现（入待办，暂缓） |
| [`plans/2026-07-14-session-handoff.md`](plans/2026-07-14-session-handoff.md) | session 交接稿(时间点) | 🗄️ 历史（进度真源已移至 FL `work-in-progress`） |
| [`plans/2026-07-17-session-handoff.md`](plans/2026-07-17-session-handoff.md) | session 交接稿(时间点,接续 07-14) | 🗄️ 历史（同上） |
| `architecture-philosophy.md` | 哲学（未跟踪、**待重写勿引**） | ⚠ 草稿,与代码有漂移,重写前勿作依据 |

---

## 4. FL-XXX 能力台账（编号 → 设计出处 → 状态）

一个编号可能横跨多份 plan / 多个子项。状态以此表为索引,细节以出处 plan + 需求树缺口表为准。

| 编号 | 主题 | 设计出处 | 状态 |
|---|---|---|---|
| FL-020 | export 缺陷（反复污染） | plans/2026-07-05 | ✅ delta 水位线 v1（commit 86de58c） |
| FL-021 L1 | `facts_search` 按内容发现事实 + export `--outline` | plans/2026-07-05 | ✅ commit b627f69 |
| FL-021 L2 | `facts_trace` 依赖+affected 双向推理链 | plans/2026-07-05 | 🔴 待实现 |
| FL-021 L3 | 精确 delta + export bootstrap + 文档式真源 | plans/2026-07-05/06 | 🔵 roadmap |
| FL-022 | 并发底座（per-slot revision / CAS / delta / 冲突浮现） | plans/2026-07-06 | 🔵 roadmap（P0 地基） |
| FL-023 | warden 审查角色（只标记不回退） | plans/2026-07-06 | 🔵 roadmap（P2） |
| FL-024 | 角色记忆系统（参考态,永不作真源） | plans/2026-07-06 | 🔵 roadmap（P1） |
| FL-024a | session-log 兄弟结构 + handoff 投影视图（024 的最小切片） | plans/2026-07-17-session-log | 📄 spec 待审 |
| FL-025 | 类别生命周期管理 | plans/2026-07-13 | 🟡 依赖边编辑（B-002）补了一半,类别 enable/add 仍缺 |
| FL-026 | MCP/CLI 建 slot 能力对等（`facts_add`） | plans/2026-07-13 | ✅ commit 3827683 |
| FL-027 | 内外完整性对账（缺失 + 失真统一） | plans/2026-07-16 | 🔴 待实现 |
| FL-028 | bug-log 缺陷知识层 | plans/2026-07-17-bug-log | 📄 spec 待审 |
| eval-L3 | eval 有效性测量结果层（T2 观测 + T3a/T3-turn 因果） | plans/2026-08-12 · S0/S1 spec 2026-08-13 · S2/T3a spec 2026-08-13 | 🟡 T2 观测(S0 `models/eval_results.py` + S1 `core/eval_t2.py`)已落 · T3a(S2) spec 已写待实现 · T3-turn(S3) 未 |

**B 类缺陷修复（TDD 落地）:**

| 编号 | 主题 | 状态 |
|---|---|---|
| B-001 | `fl check` 确定性检测真悬空依赖边 | ✅ commit 4e3f0d5 |
| B-002 | 依赖边编辑 `fl dep add/rm/list` + MCP | ✅ commit 4e3f0d5 |
| B-003 | `fl check` 检测分隔符/大小写变体重复 slot | ✅ commit 4e3f0d5 |
| eval 路由 | ingest 按 session cwd 路由 + `fl eval prune`（防跨项目 eval 污染） | ✅ 分支 fix/eval-ingest-cross-project-routing（未合并） |

---

## 5. 维护约定

- `plans/` 是**按日期 append-only** 的设计记录:新设计新开一份,**不改旧稿**;旧稿被取代时,在本文 §3/§4 更新其状态(🗄️/superseded),不删文件。
- **进度真源永远是 FL `work-in-progress` 槽**,不是任何 session-handoff 文档。写新交接稿时,同步更新 FL,别让 handoff 变成第二真源。
- 本文与需求树都**只索引/链接,不复述事实**;发现要"复述"时,应改为指向 FL 槽或 plan 章节。
- 新增 plan 或 FL 编号后,回到本文 §3/§4 补一行——这是让文档"组织在一起"的唯一维护动作。
