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

分派 web-search-agent 执行搜索任务。**子 Agent 通过"读取定义 + general-purpose 分派"创建，不使用命名的 subagent_type**：

1. 用 `Read` 读取 `agents/web-search-agent.md` 的完整内容
2. 对每个搜索任务，用 `Agent` 工具以 `subagent_type="general-purpose"` 分派，prompt 结构为：

```
<agents/web-search-agent.md 的完整定义内容>

---

## 本次搜索任务

**任务 ID**: <task-id>
**目标实体**: <名称>（类型: <类型>）
**已知信息**: <从 node body 或 hint 提取的关键信息>
**信息维度**: <要搜索的维度>
**任务背景**: <为什么查这个，图谱上下文摘要>
**期望产出**: <结构化 JSON>
**output_file_path**: <案件目录>/search-results/round-<N>-<task-id>.json
```

**重要：不要传入 `isolation: "worktree"` 参数。** 子 Agent 在当前工作区进程内执行，不需要 git worktree 隔离。工作区不一定是 git 仓库。

独立任务可并行分派。等待所有子 Agent 返回后进入步骤 4。

#### 步骤 4：分派 analysis-agent

同样通过"读取定义 + general-purpose 分派"创建：

1. 用 `Read` 读取 `agents/analysis-agent.md` 的完整内容
2. 用 `Agent` 工具以 `subagent_type="general-purpose"` 分派，prompt 结构为：

```
<agents/analysis-agent.md 的完整定义内容>

---

## 本调查全局信息
- 调查目标: <goal>
- 种子节点 body: <完整 Markdown>

## 上一轮分析结论（如无则写"首轮"）
<analysis/round-(N-1).json 全文>

## 当前图谱摘要
- 现有节点: [{node_id, name, type, exploration_status}, ...]
- 现有边: [{edge_id, source_name, target_name, type, verification_status}, ...]

## 本轮搜索结果文件（用 Read 工具逐个读取）
- <案件目录>/search-results/round-<N>-<task-id-1>.json
- <案件目录>/search-results/round-<N>-<task-id-2>.json
```

图谱摘要通过 `graph_snapshot()` + 必要的节点/边查询整理，保持紧凑——目标是让 analysis-agent 知道"图中已有什么"，不需要完整 body。

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
2. **分派报告 Agent**：用 `Read` 读取 `agents/report-agent.md` 完整定义，以 `subagent_type="general-purpose"` 分派，prompt 为「agent 定义全文 + 打包材料」。不要传入 `isolation` 参数。
3. **呈现**：在对话中展示报告 Agent 返回的全景报告.md 内容
