# fact-layer

[English](README.md)

**为 AI 编程 Agent 提供结构化、一致性校验的项目事实层。**

> 在源头通过结构化手段预防不一致，而非在下游检测修复。

fact-layer 为 AI 编程 Agent（Claude Code、Codex、Cursor、Aider 等）提供关于项目的**唯一可信源** —— 具备 schema 约束、依赖追踪和自动化一致性校验。

## 问题背景

CLAUDE.md、AGENTS.md、`.cursorrules` 都是纯文本 —— 无结构、无版本、无依赖追踪。当项目事实相互矛盾或过期时，AI Agent 会在不可靠的上下文上静默做出决策。

业界的主流路线是**反应式**的：自由输入 → embedding 去重 → LLM 治理。fact-layer 走了相反的路线 —— **预防式**：schema 约束 → 唯一索引 → 依赖图检查 → LLM 审计。从源头控制质量，而非在下游补救。

## 工作原理

```
.facts/
├── framework.yaml          # 类别配置、层级阈值
├── dependencies.yaml       # 槽位间的显式依赖图
├── canonical/              # 项目事实（结构化 YAML）
│   ├── project-overview.yaml
│   ├── tech-stack.yaml
│   ├── architecture.yaml
│   ├── conventions.yaml
│   ├── work-in-progress.yaml
│   ├── decisions.yaml
│   └── ...                 # data-model, api-contracts, testing 等
└── snapshot.md             # 导出的 Markdown 快照，供 Agent 消费
```

每个事实是一个带结构化元数据的**槽位（slot）**：

```yaml
database:
  value: "PostgreSQL 16"
  meta:
    source: human              # human | agent-analysis | code-extracted
    confidence: high           # high | medium | low
    status: active             # active | uncertain | stale | superseded
    updated: "2026-06-09"
    verified: "2026-06-09"
    reason: "需要 JSONB 支持和 CTE 性能"
```

## 三层一致性模型

```
第 0 层 — 结构预防
  Schema + 唯一索引 (category, slot, scope)
  在源头消除 80% 的唯一性问题，零 AI 成本。

第 1 层 — 依赖驱动检查 (fl check)
  通过依赖图捕获跨槽位不一致。
  LLM 范围受图的边约束 — O(edges)，而非 O(slots²)。

第 2 层 — LLM 语义审计 (fl audit)
  累积漂移的安全网。
  发现结构检查无法捕获的矛盾和缺口。
```

## 安装

```bash
pipx install fact-layer
```

或开发模式：

```bash
git clone https://github.com/Kismet777/Fact-Layer.git
cd fact-layer
pip install -e ".[dev]"
```

## 快速开始

### 1. 初始化

```bash
cd my-project
fl init
```

交互式引导你完成项目名、语言和扩展类别的选择。

### 2. 填写事实

编辑 `.facts/canonical/*.yaml` —— 每个槽位都有注释说明用途和示例值。

### 3. 校验一致性

```bash
fl check
```

运行四类检查：结构完整性、过期检测、依赖一致性、决策追踪。

```
Checking facts consistency...

  Structural:
  x testing — category enabled but empty

  Dependencies:
  x tech-stack.database updated 2026-06-09
     but build-deploy.docker last updated 2026-05-01
     derives-from: downstream must be updated

  Summary: 2 errors, 0 warnings
```

### 4. 变更前查看影响

```bash
fl impact tech-stack.database
```

```
Impact analysis for tech-stack.database

  Direct dependencies:
  ├── data-model.database-type     derives-from       (MUST update)
  ├── build-deploy.docker          constrains         (should check)
  └── testing.commands             constrains         (should check)

  From decisions:
  └── DEC-001 "Choose PostgreSQL"    affects this slot
```

### 5. 查看事实健康度

```bash
fl status
```

```
Facts Status

  Stable Layer
  v project-overview    5/5 slots    verified today
  v tech-stack          5/6 slots    verified today
  v architecture        3/3 slots    verified today

  Dynamic Layer
  v data-model          3/4 slots    verified today
  ! api-contracts       2/4 slots    1 stale

  Working Layer
  v work-in-progress    2/5 slots    verified today
  v decisions           1 active decisions

  Overall: 24/35 slots filled · 1 stale · 0 category empty
```

### 6. 导出供 Agent 消费

```bash
fl export              # 写入 .facts/snapshot.md
fl export --stdout     # 输出到标准输出
fl export -o ctx.md    # 自定义输出路径
```

生成干净的 Markdown 快照 —— 只包含活跃槽位，无噪音。可直接粘贴到 CLAUDE.md 或喂给任何编程 Agent。

### 7. LLM 语义审计

```bash
fl audit
```

调用 Claude 分析所有事实，发现结构检查无法捕获的语义矛盾、过期信号和缺失关联。

```
Running LLM-powered consistency audit...
  Input: ~1200 tokens, model: claude-sonnet-4-6

  ! Potential contradiction:
     Slots: project-overview.purpose, api-contracts.style
     purpose says "REST API service" but api style is "gRPC"
     -> Confirm if migration happened, then update purpose

  * Suggestion:
     Slots: tech-stack.external-services
     architecture mentions "LLM Gateway" but external-services is empty
     -> Consider filling external-services for completeness

  2 warnings, 1 suggestion
```

## 依赖图

依赖图（`dependencies.yaml`）定义了五种关系类型：

| 关系 | 含义 | 源变更时 |
|------|------|----------|
| `derives-from` | B 的值由 A 决定 | B **必须**更新 |
| `references` | B 引用了 A 中的实体 | B 可能**失效** |
| `constrains` | A 约束 B 的取值范围 | B **应该**检查 |
| `implies` | A 为真意味着 B 应该存在 | 检查 B 是否存在 |
| `conflicts-with` | A 和 B 不能同时持有某些值 | 检查 B 兼容性 |

`fl check` 利用依赖图捕获"改了一个事实但忘了更新关联事实"—— 这是 AI Agent 上下文过期的最常见原因。

## 事实框架

事实按变更频率分为三个层级：

| 层级 | 类别 | 过期阈值 |
|------|------|----------|
| **Stable（稳定层）** | project-overview, tech-stack, architecture, conventions | 90 天 |
| **Dynamic（动态层）** | data-model, api-contracts, testing, build-deploy, security | 30 天 |
| **Working（工作层）** | work-in-progress, decisions | 7 天 |

核心类别（稳定层）始终启用。扩展和可选类别在 `fl init` 时按需开启。

## 配置

`framework.yaml` 控制项目配置：

```yaml
project_name: my-project
tiers:
  stable:
    description: Foundational facts that rarely change
    stale_threshold_days: 90
  dynamic:
    description: Facts that change with development
    stale_threshold_days: 30
  working:
    description: Frequently changing operational facts
    stale_threshold_days: 7

extensions:
  enabled: [data-model, testing, build-deploy]
optional:
  enabled: [decisions]
```

## 开发

```bash
git clone https://github.com/Kismet777/Fact-Layer.git
cd fact-layer
pip install -e ".[dev]"
pytest                  # 95 tests
```

## 技术栈

- **Python 3.12+**
- [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) — CLI 框架
- [Pydantic v2](https://docs.pydantic.dev/) — Schema 校验
- [ruamel.yaml](https://yaml.readthedocs.io/) — YAML 读写（保留注释）
- [Anthropic SDK](https://docs.anthropic.com/) — LLM 审计
- [Jinja2](https://jinja.palletsprojects.com/) — 导出模板渲染

## 许可证

MIT
