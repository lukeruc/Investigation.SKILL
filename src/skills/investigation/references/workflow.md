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

### Round 1 特殊说明

Round 1 没有上一轮分析可参考，搜索方向完全由种子信息和调查目标决定。结构与后续轮完全一致：搜索 → 入库 → 分析。

### 每轮执行步骤

#### 步骤 1：读图

```
snapshot = graph_snapshot()
gaps = node_list_gaps()
```

获取全图状态——节点/边数量、类型分布、度中心性排名、缺口清单。

#### 步骤 2：识别并编译搜索任务

**Round 1**：

- 目标：种子节点。
- 信息维度：由调查目标和种子实体类型推断（如公司查工商/股东/涉诉，人员查任职/关联公司/舆情）。
- 直接编译为一个或多个 `web-search-agent` 搜索 prompt。

**Round N（N > 1）**：

- 读取 `analysis/round-(N-1).json` 中的 `next_round_hints`。
- 每个 hint 必须能直接翻译为一个 `web-search-agent` prompt。
- 对每个 hint：
  1. 若 `target_entity.node_id` 为 null，调用 `node_search(name_pattern=..., type=...)` 查找；若仍未命中，按新实体搜索。
  2. 将 `suggested_dimensions` 和 `notes` 组合成 `web-search-agent` 输入合约。
  3. 生成完整 prompt。

任务优先级直接使用 hint 中的 `priority`；主 Agent 不再重新打分。每轮任务数量上限由 analysis-agent 控制（建议最多 5 个）。

#### 步骤 3：分派子 Agent

使用 `Agent` 工具分派 `web-search-agent`。在 prompt 中指定使用 `web-search-agent` agent 定义。

**重要：不要传入 `isolation: "worktree"` 参数。** 子 Agent 在当前工作区进程内执行，不需要 git worktree 隔离。工作区不一定是 git 仓库。

独立任务可并行分派。等待所有子 Agent 返回后进入步骤 4。

#### 步骤 4：结果入库

**实体入库**：
1. 对每个 new_entity 调 `node_search(name_pattern=name, type=type)` 消歧
2. 发现同名候选 → 创建 `identity_edge_create`（Phase 3 已实现）标记为待验证；不要直接合并
3. 是新实体 → `node_create(type, name, body, source_chain_entry)`
4. 将实体状态改为 `exploring`（防止下一轮重复搜索）

**关系入库**：
1. 解析 source_name/target_name → 查 node_search 获取 node_id
2. 若找不到对应节点，先 node_create 再 edge_create
3. `edge_create(source_id, target_id, type, direction, body, source_chain_entry)`
4. MCP Server 自动处理去重

**矛盾检测**（LLM 执行）：
1. 读已有边的 body 和所有 source_chain
2. 与新来源比较——是否存在实质冲突？
3. 冲突 → 调用 `edge_update(verification_status="contradicted", contradicted_by=[...])`（Phase 3 已实现）
4. 独立印证 → 调用 `edge_update(verification_status="verified")`

#### 步骤 5：分派分析 Agent

打包本轮变更数据（新增/更新的节点 body、边 body、source_chain），加上种子 body 和上一轮分析结论，发送给 `analysis-agent`。

Agent 产出两份文件：
- `analysis/round-<N>.json`（结构化结论）
- 追加到 `证据日志.md`（信息来源时间线）

**必须等待 analysis-agent 返回后才能进入下一轮。**

#### 步骤 6：应用分析结论

读取 `<案件目录>/analysis/round-<N>.json`，将分析结论落实到图中：

- `body_merges` → `node_update(body=...)`
- `anomaly_signals` → `node_update(anomaly_flags=[...])`
- `quality_flags` 中标记的矛盾 → 若 target 为 edge，调用 `edge_update`；若 target 为 node，调用 `node_update`
- `quality_flags` 中建议升级验证状态 → 调用 `edge_update(verification_status="verified")`
- `seed_profile` → 更新种子节点 body 的判断层段落
- 对已完成本轮搜索的节点更新 exploration_status：
  - 还有维度未搜 → `partial`
  - 全部维度已搜 → `explored`
  - 重复搜索无结果 → `exhausted`

同时，查看 `证据日志.md` 中本轮标注的"值得下载的文件"：
- 对每个建议下载的文件，用 WebFetch 抓取后 Write 到 `<案件目录>/evidence/`
- 将文件路径和内容摘要更新到关联节点的 body 末尾

#### 步骤 7：判断是否继续

基于本轮分析结论 + `next_round_hints` + 当前图谱状态，判断：
- `next_round_hints` 非空 + 未达 `depth_limit` → 向用户汇报本轮摘要，继续下一轮
- 连续 2 轮无明显进展 → 告知用户，建议暂停、调整方向或出报告
- 达到 `depth_limit` → 汇报进展，询问是否继续或出报告

**进展判定标准**：满足以下任一条件即视为有进展：
1. 本轮新增节点数 > 0 或新增边数 > 0
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
