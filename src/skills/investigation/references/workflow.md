# 调查工作流

## 阶段 0：启动

**触发**：用户表达调查意图（"调查XXX"、"查一下XXX"等）。

### 步骤

1. **收集种子信息**。若用户信息不足，追问以下内容（能推断的跳过）：
   - 种子实体名称（必填）
   - 实体类型 — 自由文本（选填，可从名称推断）
   - 已知附加信息 — 任何有助于定位的线索（选填，越多越好）
   - 调查目标 — 自由文本（选填，默认"全景画像"）
   - 深度上限（选填，默认 3 跳）

2. **创建会话和种子节点**：

```
session_create(workspace_path=<当前工作目录>, name="调查<种子名称>", goal=<调查目标>, depth_limit=<深度上限>)

node_create(
    type=<实体类型>,
    name=<种子名称>,
    body=<已知信息Markdown>,
    source_chain_entry={
        source_name: "用户提供",
        source_type: "user_provided",
        source_reliability: "A",
        info_credibility: "3"
    }
)
```

3. **确认并开始**。向用户汇报：种子名称/类型、调查目标、深度限制、案件路径。请求确认后开始调查循环。

---

## 阶段 1-N：调查循环

**核心原则**：搜索与分析串行执行。每轮搜索任务来自上一轮 analysis-agent 的 `next_round_hints`（Round 1 除外，Round 1 来自种子信息和调查目标）。

**主 Agent 职责边界**：主 Agent 只做调度（编译任务、分派子 Agent）和机械执行（按 `integration_instructions` 写库）。信息解读、消歧判断、矛盾检测、方向决策全部由 analysis-agent 完成。

### Round 1 特殊说明

Round 1 没有上一轮分析可参考，搜索方向完全由种子信息和调查目标决定。结构与后续轮完全一致：搜索 → 分析 → 执行入库指令。

### 每轮执行步骤

#### 步骤 1：读图

```
snapshot = graph_snapshot()
```

获取全图状态——节点/边数量、类型分布、度中心性排名。此步骤只为向用户汇报和追踪进展，不为编译搜索任务。

#### 步骤 2：识别并编译搜索任务

**Round 1**：

- 目标：种子节点。
- 信息维度：由调查目标和种子实体类型推断（如公司查工商/股东/涉诉，人员查任职/关联公司/舆情）。
- 直接编译为一个或多个 `web-search-agent` 搜索 prompt。

**Round N（N > 1）**：

- 读取 `analysis/round-(N-1).json` 中的 `next_round_hints`。
- 对每个 hint 直接编译为 `web-search-agent` prompt：
  1. 将 `suggested_dimensions` 和 `notes` 组合成 `web-search-agent` 输入合约。
  2. 生成完整 prompt。

任务优先级直接使用 hint 中的 `priority`；主 Agent 不再重新打分。每轮任务数量上限由 analysis-agent 控制（建议最多 5 个）。

#### 步骤 3：分派 web-search-agent

使用 `Agent` 工具分派 `web-search-agent`。每个任务的 prompt 中：

- 指定使用 `web-search-agent` agent 定义
- 指定 `output_file_path` 为 `<案件目录>/search-results/round-<N>-<task-id>.json`，要求 agent 将结果 JSON 写入该文件

**重要：不要传入 `isolation: "worktree"` 参数。** 子 Agent 在当前工作区进程内执行，不需要 git worktree 隔离。工作区不一定是 git 仓库。

独立任务可并行分派。等待所有子 Agent 返回后进入步骤 4。

#### 步骤 4：分派 analysis-agent

分派 `analysis-agent`，输入包包含：

1. **调查全局信息**：调查目标 + 种子节点 body
2. **上一轮分析结论**：`analysis/round-(N-1).json` 全文（首轮写"首轮"）
3. **当前图谱摘要**：调用 `graph_snapshot()` 和 `edges_from_node`（或紧凑的节点/边列表）整理为：
   - 现有节点: `[{node_id, name, type, exploration_status}, ...]`
   - 现有边: `[{edge_id, source_name, target_name, type, verification_status}, ...]`
4. **本轮搜索结果文件路径**：`<案件目录>/search-results/round-<N>-*.json` 全部列出，analysis-agent 会自行用 Read 读取

**必须等待 analysis-agent 返回后才能进入步骤 5。**

#### 步骤 5：机械执行入库指令

读取 `<案件目录>/analysis/round-<N>.json` 中的 `integration_instructions` 数组，按顺序逐条执行。**不修改指令内容，只做引用解析和 MCP 调用。**

执行规则：

| action | 执行方式 |
|---|---|
| `node_create` | 先 `node_search(name_pattern=name, type=type)` 消歧。命中现有节点 → 改为 `identity_edge_create` + 跳过创建；未命中 → `node_create`。 |
| `node_update` | 直接 `node_update(node_id, ...)`。若指令用 `{name, type}` 引用，先 `node_search` 解析 node_id。 |
| `edge_create` | 用 `node_search` 解析 source/target 的 node_id（指令中是 `{name, type}`），找不到时先创建该节点。然后 `edge_create`。 |
| `edge_update` | 直接 `edge_update(edge_id, ...)`。 |
| `identity_edge_create` | 解析两端 node_id 后 `identity_edge_create`。 |

执行过程中记录每条指令的结果（成功/失败/去重），失败时跳过并记录，不中断后续指令。

同时，查看 `<案件目录>/证据日志.md` 中本轮标注的"值得下载的文件"：
- 对每个建议下载的文件，用 WebFetch 抓取后 Write 到 `<案件目录>/evidence/`
- 将文件路径和内容摘要追加到关联节点的 body 末尾（`node_update`）

#### 步骤 6：判断是否继续

基于本轮 `analysis/round-<N>.json` 的 `next_round_hints` + 当前图谱状态，判断：
- `next_round_hints` 非空 + 未达 `depth_limit` → 向用户汇报本轮摘要，继续下一轮
- 连续 2 轮无明显进展 → 告知用户，建议暂停、调整方向或出报告
- 达到 `depth_limit` → 汇报进展，询问是否继续或出报告

**进展判定标准**：满足以下任一条件即视为有进展：
1. 本轮成功执行的 `integration_instructions` 中有 `node_create` 或 `edge_create`
2. 本轮 `analysis-agent` 的 `key_findings` 非空且至少有一条 rank <= 2
3. 本轮有节点的 `exploration_status` 从 `partial` / `exploring` 变为 `explored`
4. 本轮 `quality_flags` 或 `anomaly_signals` 非空（发现新问题也视为进展）

否则视为无进展，`consecutive_no_progress` 加 1。

---

## 状态追踪

对话上下文中维护以下追踪变量：
- 当前轮次
- 最新 analysis 文件路径
- 连续无进展轮数
- 上次 snapshot 摘要（用于比较两轮之间的进展）

若对话上下文被压缩，可通过 `session_get()` 和 `graph_snapshot()` 完全重建状态。最新 analysis 文件路径可从案件目录下的 `analysis/round-<N>.json` 重新发现。

---

## 交付阶段：全景报告

**触发**：用户说"出报告"或调查自然终止。

### 步骤

1. **收集材料**：调用 `graph_snapshot()` 获取全图统计，对种子节点和度中心性 top-5 节点调用 `report_summary(node_id)`，再对各轮 analysis/round-*.json 和证据日志.md 打包
2. **分派报告 Agent**：通过 `Agent` 工具分派 `report-agent`（定义在 `agents/report-agent.md`），将打包材料发送过去
3. **呈现**：在对话中展示报告 Agent 返回的全景报告.md 内容
