# MCP 工具命令参考

全部工具通过 `mcp__investigation-graph__<tool_name>` 调用。MCP Server 维护一个活跃数据库路径（`active_db_path`），所有工具无需 `session_id` 参数。数据库隔离通过文件系统实现——每个案件一个 `case.db`。

---

## 会话操作

### session_create

```
mcp__investigation-graph__session_create(
    workspace_path: str,   # 工作区绝对路径
    name: str,             # 案件名称
    goal: str = "",        # 调查目标（自由文本）
    depth_limit: int = 3   # 最大跳数
) -> { case_path, case_id, goal, depth_limit, created_at }
```

行为：在 workspace_path 下创建 `{timestamp}-{name}/` 目录 + `case.db`，切换活跃连接。

### session_open

```
mcp__investigation-graph__session_open(
    case_path: str   # 案件目录绝对路径
) -> { case_path, goal, depth_limit, round_number, status, seed_node_id, ... }
```

行为：关闭当前连接，打开指定路径下的 `case.db`。

### session_get

```
mcp__investigation-graph__session_get()
-> { case_path, goal, depth_limit, round_number, status, seed_node_id, ... }
```

---

## 实体操作

### node_create

```
mcp__investigation-graph__node_create(
    type: str,                              # 实体类型（自由字符串）
    name: str,                              # 实体名称
    body: str = "",                         # Markdown 文本
    confidence: str = "medium",             # high / medium / low
    source_chain_entry: dict | None = None  # 来源信息
) -> { node_id, type, name, body, confidence, exploration_status, ... }
```

### node_get

```
mcp__investigation-graph__node_get(node_id: str)
-> 节点完整信息（body + 所有关联边列表 + source_chains 列表）
```

### node_update

```
mcp__investigation-graph__node_update(
    node_id: str,
    body: str | None = None,                     # 新的 body（完全替换）
    confidence: str | None = None,
    exploration_status: str | None = None,       # unexplored/exploring/explored/partial/skipped/exhausted
    anomaly_flags: list[str] | None = None
) -> 更新后的节点
```

### node_search

```
mcp__investigation-graph__node_search(
    type: str | None = None,         # 类型过滤
    name_pattern: str | None = None, # 名称 LIKE '%pattern%'
    limit: int = 50
) -> [{ id, name, type, exploration_status, ... }]
```

用途：消歧检查——入库前搜同名实体，判断是否已存在。

### node_list_gaps

```
mcp__investigation-graph__node_list_gaps(
    type: str | None = None
) -> [{ id, name, type, exploration_status, ... }]
```

返回 exploration_status 为 `unexplored/exploring/partial/skipped` 的节点。

---

## 关系操作

### edge_create

```
mcp__investigation-graph__edge_create(
    source_id: str,
    target_id: str,
    type: str,                              # 关系类型（自由字符串）
    direction: str = "directed",
    body: str = "",
    intensity: float = 0.5,
    confidence: str = "medium",
    source_chain_entry: dict | None = None
) -> { edge_id, created: bool, deduplicated: bool }
```

**去重机制**：同 source_id + target_id + type + direction 的边不重复创建。若已存在，追加 source_chain_entry 并返回 `{created: false, deduplicated: true}`。

**注意**：MCP Server 不做矛盾检测和交叉验证——这些由主 Agent（LLM）在入库阶段执行。

### edge_get

```
mcp__investigation-graph__edge_get(edge_id: str)
-> 边完整信息（body + source_chains + contradicted_by）
```

### edge_update

```
mcp__investigation-graph__edge_update(
    edge_id: str,
    body: str | None = None,
    confidence: str | None = None,
    verification_status: str | None = None,  # unverified/verified/contradicted/retracted
    intensity: float | None = None,
    anomaly_flags: list[str] | None = None,
    contradicted_by: list[str] | None = None
) -> 更新后的边
```

### edges_from_node

```
mcp__investigation-graph__edges_from_node(
    node_id: str,
    edge_type: str | None = None,
    direction: str | None = None
) -> [{ id, type, direction, body, source_name, source_type, target_name, target_type, ... }]
```

返回该节点的所有关联边 + 邻居节点摘要。

---

## 消歧与合并

### identity_edge_create

```
mcp__investigation-graph__identity_edge_create(
    node_a_id: str,
    node_b_id: str,
    match_basis: str = "name_match"
) -> { edge_id, created: bool }
```

创建 type="identity" 的边，表示两个节点可能为同一实体。verification_status="unverified"，intensity=0.3。若已存在 identity 边则返回已有 edge_id。

### identity_edge_update

```
mcp__investigation-graph__identity_edge_update(
    identity_edge_id: str,
    evidence_entry: dict | None = None,
    intensity: float | None = None,
    verification_status: str | None = None
) -> 更新后的 identity 边
```

更新 identity 边；若提供 evidence_entry，写入 identity_evidence 表。

evidence_entry 格式：
```json
{
  "signal_name": "信号名称",
  "signal_value": "信号值",
  "direction": "supporting / opposing / neutral",
  "weight": "high / medium / low",
  "source_entry_id": "关联 source_chain id 或 null"
}
```

### node_merge

```
mcp__investigation-graph__node_merge(
    node_ids: list[str],
    reason: str = ""
) -> { merged_node_id, absorbed_node_ids, merge_history_id }
```

合并多个节点为一个。保留第一个 node_id 作为主节点，迁移关系，记录 merge_history。

### node_unmerge

```
mcp__investigation-graph__node_unmerge(
    node_id: str,
    merge_event_index: int | None = None
) -> { merged_node_id, restored_node_ids, note }
```

拆分已合并节点。当前为简化实现，仅恢复被吸收节点 ID，原 body 和关系不完全恢复。

---

## 图分析

### graph_snapshot

```
mcp__investigation-graph__graph_snapshot()
-> {
    summary: { total_nodes, total_edges, session_round },
    nodes_by_type: [{ type, cnt }],
    edges_by_type: [{ type, cnt }],
    nodes_by_status: [{ exploration_status, cnt }],
    edges_by_vstatus: [{ verification_status, cnt }],
    top_central_nodes: [{ id, name, type, degree }],
    seed_nodes: [{ id, name, type }],
    anomaly_counts: { nodes_with_anomalies, edges_with_anomalies }
}
```

每轮调查的第一步调用此工具，获取全图状态。

### graph_path

```
mcp__investigation-graph__graph_path(
    source_node_id: str,
    target_node_id: str,
    max_depth: int = 5
) -> { path: [{ node_id, name, type }, ...], edges: [{ edge_key, type }, ...] } | { path: null, edges: null }
```

返回两节点间最短路径（BFS）。若不存在路径，返回 `{ path: null, edges: null }`。

### graph_neighbors

```
mcp__investigation-graph__graph_neighbors(
    node_id: str,
    depth: int = 1
) -> { source_node_id, depth, nodes: [...], edges: [...] }
```

返回指定深度内的邻居节点和路径边。

---

## 报告

### report_summary

```
mcp__investigation-graph__report_summary(node_id: str)
-> {
    node: { ... },
    edges: [...],
    source_summary: { A1_count, B2_count, ... },
    verification_summary: { unverified: n, verified: n, contradicted: n, retracted: n },
    anomaly_flags: [...],
    gaps: [{ node_id, name, missing }]
}
```

以节点为中心的结构化摘要，聚合关系、来源质量、验证状态和缺口。

---

## source_chain_entry 格式

```json
{
  "source_name": "来源名称（必填）",
  "source_type": "来源类型（必填，自由字符串）",
  "source_reliability": "X",     // 选填，默认 X。A/B/C/D/E/X
  "info_credibility": "6",       // 选填，默认 6。1/2/3/4/5/6
  "discovery_time": "ISO8601",   // 选填，默认当前时间
  "discovery_agent": null,       // 选填
  "discovery_context": null,     // 选填
  "raw_data": "{}"               // 选填，默认 "{}"
}
```

## 错误码

所有工具在失败时返回 `{ error: "<code>", detail: "<描述>" }`：

| 错误码 | 含义 |
|---|---|
| `not_found` | node/edge 不存在 |
| `invalid_reference` | edge_create 的 source_id 或 target_id 不存在 |
| `case_not_found` | session_open 路径无效 |
| `already_exists` | session_create 目录已存在 |
| `no_active_db` | 未创建或打开任何案件 |
| `invalid_input` | 入参校验失败（如 confidence 不是 high/medium/low） |
| `invalid_type` | 对非 identity 边调用 identity 操作 |
| `no_merge_history` | node_unmerge 目标无合并历史 |
| `invalid_index` | merge_event_index 越界 |
