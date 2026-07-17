---
title: 调查图谱 — 数据模型
version: 0.2
date: 2026-07-16
---

# 数据模型

## 设计原则

**骨架给机器，身体给 LLM，信号是缓存的一次性判断。**

- 骨架字段：让节点/边在图结构中可被寻址、连接、按类型筛选。SQL 索引和 JOIN 的依赖。
- body 字段：TEXT Markdown。关于这个节点/边的**一切已知信息**。LLM 原生读写，无 schema，无约束。
- 信号字段：LLM 做出的判断（可信度、强度、异常标记、矛盾记录），缓存在字段中以节省后续轮次的重复 LLM 调用。graph_snapshot 的聚合和优先级排序的量化都依赖这些缓存。

每个字段的存在理由是一个问题：**"没有这个字段，LLM 每轮要多读多少东西？"**

---

## 表结构

### nodes

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | TEXT PK | ✓ | UUID v4 |
| type | TEXT | ✓ | 实体类型。自由字符串，不预定义枚举。由调查自行生长 |
| name | TEXT | ✓ | 主名称。node_search 做 LIKE 匹配，消歧做名称比对 |
| body | TEXT | ✓ | Markdown。关于此实体的全部已知信息。结构化事实、叙述性描述、推测、矛盾线索——全部在这里。默认空字符串 |
| exploration_status | TEXT | ✓ | unexplored / exploring / explored / partial / skipped / exhausted |
| confidence | TEXT | ✓ | high / medium / low。LLM 看过所有 source_chain 后的总体可信度判断 |
| anomaly_flags | TEXT | ✓ | JSON 数组。LLM 发现异常后打标缓存。默认 `[]` |
| first_seen | TEXT | ✓ | ISO 8601。实体首次入图时间 |
| last_updated | TEXT | ✓ | ISO 8601。最后修改时间。优先级排序的"时效性"维度依赖此字段 |

### edges

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | TEXT PK | ✓ | UUID v4 |
| source_id | TEXT FK | ✓ | 引用 nodes.id |
| target_id | TEXT FK | ✓ | 引用 nodes.id |
| type | TEXT | ✓ | 关系类型。自由字符串。edge_create 去重核心——同 source+target+type+direction 不重复建边 |
| direction | TEXT | ✓ | directed / undirected。去重逻辑的核心 |
| body | TEXT | ✓ | Markdown。关于此关系的全部已知信息。默认空字符串 |
| verification_status | TEXT | ✓ | unverified / verified / contradicted / retracted |
| confidence | TEXT | ✓ | high / medium / low。LLM 看过此边所有 source_chain 后的总体判断 |
| intensity | REAL | ✓ | 0.0 ~ 1.0。关系强度/重要性。LLM 判断。优先级排序和报告可视化使用 |
| contradicted_by | TEXT | ✓ | JSON 数组。`[{source_entry_id, description, field}]`。LLM 发现冲突来源后写入。优先级排序的矛盾维度（权重 0.30）直接读此字段 |
| anomaly_flags | TEXT | ✓ | JSON 数组。默认 `[]` |
| first_seen | TEXT | ✓ | ISO 8601 |
| last_updated | TEXT | ✓ | ISO 8601 |

### source_chains

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | TEXT PK | ✓ | UUID v4 |
| target_type | TEXT | ✓ | "node" 或 "edge" |
| target_id | TEXT | ✓ | 引用 nodes.id 或 edges.id |
| source_name | TEXT | ✓ | 来源名称 |
| source_type | TEXT | ✓ | 自由字符串。不预定义枚举 |
| source_reliability | TEXT | ✓ | A / B / C / D / E / X |
| info_credibility | TEXT | ✓ | 1 / 2 / 3 / 4 / 5 / 6 |
| discovery_time | TEXT | ✓ | ISO 8601 |
| discovery_agent | TEXT | | 哪个子 Agent 发现的 |
| discovery_context | TEXT | | 发现上下文 |
| raw_data | TEXT | ✓ | 子 Agent 返回的原始数据快照。LLM 做矛盾检测时的比对依据 |
| created_at | TEXT | ✓ | ISO 8601 |

### sessions

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | TEXT PK | ✓ | UUID v4。每库仅一行——数据库文件本身就是隔离边界 |
| goal | TEXT | ✓ | 自由文本。用户描述什么就存什么 |
| depth_limit | INTEGER | ✓ | 最大跳数，默认 3 |
| round_number | INTEGER | ✓ | 当前已完成的调查轮次 |
| status | TEXT | ✓ | active / paused / completed |
| seed_node_id | TEXT FK | | 种子节点 ID |
| created_at | TEXT | ✓ | ISO 8601 |
| updated_at | TEXT | ✓ | ISO 8601 |

### merge_history

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | TEXT PK | ✓ | |
| merged_node_id | TEXT FK | ✓ | 保留的节点 ID |
| absorbed_node_ids | TEXT | ✓ | JSON 数组。被吸收的节点 ID 列表 |
| identity_edge_id | TEXT | | 触发合并的 identity 边 ID |
| reason | TEXT | ✓ | |
| evidence_snapshot | TEXT | | 合并时的证据快照 |
| merged_at | TEXT | ✓ | ISO 8601 |

### identity_evidence

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | TEXT PK | ✓ | |
| identity_edge_id | TEXT FK | ✓ | 引用 edges.id（type="identity" 的边） |
| signal_name | TEXT | ✓ | phone_match / id_card_match / same_address / … |
| signal_value | TEXT | | |
| direction | TEXT | ✓ | supporting / opposing / neutral |
| weight | TEXT | ✓ | high / medium / low |
| source_entry_id | TEXT FK | | 引用 source_chains.id |
| recorded_at | TEXT | ✓ | ISO 8601 |

---

## 状态枚举

### exploration_status（节点探索状态）

```
unexplored  → 刚创建，从未被搜索
exploring   → 已被本轮任务申领，等待子 Agent 返回
partial     → 至少一个维度已搜，但仍有未覆盖的维度
explored    → 该实体的当前计划维度均已搜索（含"未找到结果"）
skipped     → 被主 Agent 主动跳过（孤悬节点、低优先级）
exhausted   → 所有已知可搜维度均已尝试，无更多信息源
```

状态流转：
```
unexplored → exploring → explored
                        → partial → exploring → explored / partial
             skipped → exploring（重新激活）
             exhausted（终态，不可逆）
```

### verification_status（边验证状态）

```
unverified  → 仅单个来源
verified    → 两个及以上独立来源相互印证（由主 Agent 判断，非自动）
contradicted → 不同来源之间存在矛盾，尚未解决
retracted   → identity 边已合并后标记撤回
```

### confidence（可信度）

```
high    → 多独立来源印证，信息自洽
medium  → 单一可靠来源，或轻微不一致（默认）
low     → 单一非权威来源，或显著不确定
```

---

## 双三角评级

每条信息（node.body 或 edge.body 中的断言）通过 source_chain_entry 追溯到来源，评定双三角。

### 来源可靠性（A→X）

| 评级 | 含义 |
|---|---|
| A | 完全可靠（官方数据库直接返回、司法文书原文） |
| B | 通常可靠（权威媒体、知名数据平台） |
| C | 相当可靠（一般正规媒体、行业数据库、官网自述） |
| D | 通常不可靠（自媒体、匿名帖子、个人博客） |
| E | 不可靠（已知虚假信息源） |
| X | 无法评估（默认） |

### 信息可信度（1→6）

| 评级 | 含义 |
|---|---|
| 1 | 被其他独立来源证实 |
| 2 | 很可能是真的（与已知信息一致） |
| 3 | 可能是真的（合理但单一来源） |
| 4 | 真实性存疑（与其他信息矛盾或来源有利益关联） |
| 5 | 很不可能（已被证伪） |
| 6 | 无法判断（默认） |

---

## 消歧规则

### 自动触发条件

新实体入库前，主 Agent 调 `node_search(name_pattern=name, type=type)`：

| 匹配结果 | 行为 |
|---|---|
| name 完全匹配 + type 相同 | 自动创建 identity 边（verification_status=unverified） |
| name 完全匹配 + type 不同 | 创建 identity 边，confidence=low |
| name 编辑距离 ≤ 2（中文）且 type 相同 | 创建 identity 边，标记需人工审核 |

### identity 边验证

主 Agent 读两边节点的 body，比较关键信息（身份证号片段、统一社会信用代码、电话号码重叠、地址重叠），判断是否同一实体。证据逐条写入 identity_evidence 表。

---

## 矛盾检测

**由主 Agent（LLM）在入库阶段执行**，非 MCP 层的机械比对。

主 Agent 在新增 source_chain_entry 后：
1. 读 target (node 或 edge) 的已有 body 和所有 source_chain.raw_data
2. 比较新来源的断言与已有来源的断言
3. 判断是否存在实质冲突
4. 如有冲突 → 更新 edge.contradicted_by 或 node.anomaly_flags
5. 如新来源独立印证已有信息 → 考虑升级 verification_status 为 verified

MCP 不参与矛盾判断。MCP 只做机械的去重计数（同 source+target+type+direction 的边不重复建）并向 source_chains 追加记录。

---

## 异常检测

### 结构异常（机械规则，MCP 或 SQL 执行）

| ID | 规则 | 检测方式 |
|---|---|---|
| S1 | 有向环 | BFS 检测同类型边形成的环。适用于任何边类型（ownership / control / funds_flow / …），不限于工商场景 |
| S2 | 同地址集群 | ≥ 3 个不同节点通过同类型边连接到同一目标节点。COUNT + GROUP BY |
| S3 | 一度多连 | 一个节点通过同类型边连接 ≥ N 个目标（N=5 默认，可由主 Agent 按领域调整） |
| S4 | 桥接节点低度 | betweenness_centrality > 0.5 且 degree < 3。graph_snapshot 实时计算 |

### 内容异常（LLM 判断，主 Agent 执行）

| ID | 规则 | 说明 |
|---|---|---|
| C1 | 多源冲突 | 同一个体/关系的不同来源的断言矛盾。由主 Agent 在矛盾检测时发现并打标 |
| C2 | identity 合并后冲突 | 两个 confirmed identity 的节点 body 中含不可调和的关键信息 |
| T1 | 时间线异常 | 事件发生于关联实体不存在时。主 Agent 从各节点/边的 body 中提取时间信息做比对 |
| T2 | 模式异常 | 主 Agent 跨多节点/边发现的非随机模式（如多家公司同年同月同日成立、同一代理注册） |

---

## 优先级排序

每轮调查循环的步骤 3，对每项待办打分：

```
Score = w1·矛盾 + w2·目标匹配 + w3·网络位置 + w4·信息杠杆 + w5·时效性
```

| 维度 | 权重 | 量化方式 |
|---|---|---|
| 矛盾信号 | 0.30 | node.anomaly_flags 非空或 edge.contradicted_by 非空 → 1.0，否则 0.0 |
| 目标匹配 | 0.25 | LLM 评估。"这个待办与用户调查目标的相关度？1-10"。归一化到 [0,1] |
| 网络位置 | 0.20 | degree_centrality 在 session 内的百分位（来自 graph_snapshot） |
| 信息杠杆 | 0.15 | 验证此边可连带验证的边数 / 总未验证边数 |
| 时效性 | 0.10 | 1.0 - (now - last_updated 天数) / 30，截断到 [0, 1] |

---

## 不存什么

- **不存完整报告文本**：报告是 Skill 即时生成
- **不存分析结论**：ACH 矩阵、情景评估等是 Skill 对话上下文内容
- **不存搜索缓存**：缓存属于子 Agent 层
- **不存用户偏好**：偏好属于对话上下文
- **不存预定义的实体类型/边类型枚举**：type 是自由字符串
- **不存领域预设的搜索维度映射**：主 Agent 根据调查目标动态决定搜什么
- **不存 network_metrics**：graph_snapshot 每次实时计算
- **不存 anchor_level / seed 标记**：距离种子几跳由图结构本身给出，session.seed_node_id 标定种子
