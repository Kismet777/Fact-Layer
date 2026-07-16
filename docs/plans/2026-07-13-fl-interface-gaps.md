# FL 接口完整性缺口（dogfood handoff 暴露）

- 日期：2026-07-13
- 状态：设计讨论 → 待实现
- 涉及：`FL-025`（类别生命周期管理）、`FL-026`（MCP/CLI 建 slot 能力对等）
- 触发：贷后催收项目 2026-07-09 治理交接稿执行时，一个 FL 维护 agent 尝试"建 enums 类别 + 建新 slot"，撞到两堵接口墙。二者都指向同一个主题——**FL 的写接口不完整**。

---

## 背景

执行交接稿（建 `enums`/`contracts` 类别、批量写 D1–D6 事实）时，发现：

1. 无法通过任何 FL 接口新建/启用一个类别。
2. MCP `facts_set` 只能更新、不能新建 slot；建 slot 只能用 CLI `fl add`。

第 2 点还被确证为一桩历史误判的根因：此前一个 agent 用 `facts_set` 建 `dec-007`、得到 `"slot not found"`，于是误以为"不能新建决策 slot"，转而**原地覆盖了 `dec-006`**（其 reason 里留有 "不能新建 dec-007，故将 DEC-006 直接改" 的记录）。即：一个接口缺口，导致了一次事实写入的降级与污染。

---

## FL-025：类别生命周期管理（无接口）

### 现象
`enums` 这类新类别、或 `api-contracts` 这类 available-but-not-enabled 类别，**没有任何 FL 接口能创建或启用**：

- CLI 无 `category` 命令；`fl add` 明确是"加 slot 到**已有**类别"。
- `editor.set_slot` / `add_slot` 都先 `_validate_category_enabled`，非启用类别直接拒绝。
- `init_cmd` 只能初始化一个**全新**的 `.facts/`，不能对既有 `.facts/` 增/启用类别。
- MCP 工具集里没有类别管理工具。

唯一路径是手改 `framework.yaml` 的 `enabled` 列表 + 手建 `canonical/<cat>.yaml`——而 dogfood 项目的铁律禁止直接编辑 `.facts/`。于是该项目被迫把枚举/schema/契约全部塞进已启用的 `data-model`，用 `enum-*`/`table-*`/`api-*` 命名约定近似分区。可用，但不是本应有的结构。

### 修复方向
- 新增 `fl category enable <name>`（启用一个有模板的 available 扩展类别，如 `api-contracts`）与 `fl category add <name> --tier <t>`（创建自定义类别，无模板时生成空 canonical 文件 + 注册进 framework）。
- 对应 MCP 工具 `facts_category_enable` / `facts_category_add`。
- 二者都经 FL 接口改写 `framework.yaml` + 建 canonical 文件，使"不得直接编辑 .facts/"的铁律与"能扩展类别"不再冲突。

### 与四属性的关系
服务**完整**：本应作为一等类别存在的事实（如受治理枚举）目前只能降级塞进别的类别，是完整性的结构性缺口。通过身份测试（不引入文档内容存储、不引入推理）。

---

## FL-026：MCP/CLI 建 slot 能力不对等

### 现象
- `fl add`（CLI）能新建 slot。
- `facts_set`（MCP）只更新既有 slot，对不存在的 slot 报 `"slot not found"`；`facts_set_batch` 同理。
- MCP 接口**没有任何"新建 slot"工具**。

对纯 MCP 环境（如某些 agent 只经 MCP 调用）的 agent 而言，这等于**无法新建事实**——只能改，不能加。这直接制造了 FL-025 背景里那次误判与 dec-006 污染。

### 修复方向
- 新增 MCP 工具 `facts_add`（对齐 CLI `fl add` 语义：新建 slot 到已有类别）。
- 或让 `facts_set` 支持 upsert 语义（带一个显式 `create=true` 开关，避免拼写错 slot 名时静默建错 slot）。倾向前者：新建与更新分开，语义清晰、防误建，与 CLI `add`/`set` 的既有分工一致。

### 与四属性的关系
服务**完整**：一个不能写入新事实的接口，无法让地面覆盖到需要的事实。通过身份测试。

---

## 待办（roadmap）

- [ ] **FL-026（先做，成本低、解真痛）**：MCP `facts_add` 工具，语义对齐 CLI `fl add` + 测试。消除"纯 MCP 环境无法建 slot"这一每天都可能复发的坑。
- [ ] **FL-025**：`fl category enable/add` + 对应 MCP 工具，经接口安全改写 framework + 建 canonical，守住"不直接编辑 .facts/"铁律。

## 备注（非本文档范围，但同批暴露）
- FL 的 LLM audit 后端在该环境配置错位：batch 自动 audit 报 `The supported API model names are deepseek-v4-pro/flash, but you passed claude-haiku-4-5-...`。属后端配置问题（OpenAI 兼容端点指向 deepseek 却传了 claude 模型名），不影响数据写入，但 audit 路径当前不可用，需校正 `core.config` 的模型/后端匹配。
