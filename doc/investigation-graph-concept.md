---
title: 调查图谱 — 概念设计
version: 0.1
date: 2026-07-16
---

# 调查图谱（Investigation Graph）

## 项目定位

一个以 Claude Code 为运行环境、以 MCP Server 为存储引擎、以 Skill 文件为控制逻辑的**通用情报分析引擎**。

输入一个种子实体（人、公司、地址、事件……任何东西），系统通过多源信息采集、实体关系图构建、结构化分析方法（SATs），逐步拼出目标的全景画像。

---

## 架构

### 三层结构

```
┌──────────────────────────────────────┐
│           Skill: investigation.md     │
│                                       │
│  阶段0: 启动（收种子、建图）          │
│  阶段1-N: 调查循环（读图→找缺口→     │
│            搜索→入库→分析→决策）      │
│  交付: 全景报告                       │
│                                       │
│  SATs 规则: ACH / 来源评级            │
│  子Agent调度 / 优先级 / 终止条件      │
└──────────────┬───────────────────────┘
               │ 调用
┌──────────────▼───────────────────────┐
│           MCP: 调查图谱               │
│                                       │
│  node CRUD   edge CRUD                │
│  图查询      消歧机制                  │
│  缺口识别    分析快照                  │
│  证据链      持久化（SQLite）          │
└──────────────┬───────────────────────┘
               │ 搭配
┌──────────────▼───────────────────────┐
│       外部工具（MCP / Agent）          │
│                                       │
│  WebSearch  WebFetch                  │
│  子 Agent（各信息源）                  │
│  agentdocx（报告输出）                 │
└──────────────────────────────────────┘
```

### 核心原则

**Claude Code 就是主 agent。** Skill 文件定义了主 agent 的行为逻辑——读图、判断缺口、排优先级、生成搜索任务、解读结果、决定追哪个方向。不需要自建调度引擎。

**调查图谱是主 agent 的唯一工作界面。** 一切状态在图中，一切决策基于图。

**MCP Server 只做存储和简单图查询。** 不做决策。提供原子操作，skill 决定怎么用。

**主 Agent 不直接搜集信息。** 主 Agent 负责读图、分析缺口、优先级排序、分派任务、入库结果、产出报告。所有对外信息搜集（WebSearch、WebFetch、API 调用）由子 Agent 完成。


## MCP 调查图谱 Server

### 定位

SQLite 上的一个薄层。负责实体和关系的持久化、基本图查询、缺口识别。不含决策逻辑。

### 工具列表

MCP Server 维护一个活跃数据库连接。所有工具操作当前活跃的案件 DB，无需 session_id 参数。案件隔离通过文件系统实现（一个案件 = 一个文件夹 = 一个 case.db）。

#### 会话操作

**session_create**
```
输入: workspace_path, name, goal?, depth_limit?
输出: case_path
行为: 在 workspace_path 下创建 "{timestamp}-{name}/" 目录 + case.db，切换活跃连接。
      返回案件目录路径。
```

**session_open**
```
输入: case_path
输出: 会话状态
行为: 关闭当前活跃连接，打开指定路径下的 case.db 作为新的活跃连接。
```

**session_get**
```
输入: (无参数)
输出: 会话状态（goal, depth_limit, round_number, status, seed_node_id, created_at）
```

#### 实体操作

**node_create**
```
输入: type, name, body?, confidence?, source_chain_entry?
输出: node_id
行为: 创建节点，自动设置 id / first_seen / last_updated / exploration_status=unexplored。
      若提供了 source_chain_entry，同时写入 source_chains 表。
      body 为 Markdown 文本，包含关于此实体的所有已知信息。
```

**node_update**
```
输入: node_id, body?, confidence?, exploration_status?, anomaly_flags?
输出: 更新后的节点
行为: 增量更新，body 为 Markdown 文本。
      body 非空时替换已有 body（LLM 负责融合新旧信息后写入）。
```

**node_get**
```
输入: node_id
输出: 节点的完整信息（body + 所有边 + 来源链）
```

**node_search**
```
输入: type?, name_pattern?, limit?
输出: 匹配的节点列表
行为: 按类型/名称搜索
```

**node_list_gaps**
```
输入: type?
输出: 状态为 unexplored/exploring/partial/skipped 的节点列表
行为: 调查循环步骤 2 的数据源——识别实体缺口
```

#### 关系操作

**edge_create**
```
输入: source_id, target_id, type, direction?, body?, intensity?, confidence?, source_chain_entry?
输出: { edge_id, created, deduplicated }
行为: 创建边。若已存在同 source+同 target+同 type+同 direction 的边，
      不创建新边，改为追加 source_chain_entry。
      若提供了 source_chain_entry，同时写入 source_chains 表。
      MCP Server 不做矛盾检测和交叉验证判断——这些由主 Agent（LLM）在入库阶段执行。
```

**edge_update**
```
输入: edge_id, body?, confidence?, verification_status?, intensity?, anomaly_flags?, contradicted_by?
输出: 更新后的边
```

**edge_get**
```
输入: edge_id
输出: 边的完整信息（body + 来源链 + 验证状态 + 矛盾记录）
```

**edges_from_node**
```
输入: node_id, edge_type?, direction?
输出: 该节点的所有关联边 + 邻居节点摘要（id, name, type）
```

#### 图分析

**graph_path**
```
输入: source_node_id, target_node_id, max_depth?
输出: 最短路径（节点序列 + 边序列）或空（无路径）
```

**graph_neighbors**
```
输入: node_id, depth? (default=1)
输出: 指定深度的邻居节点及路径
```

**graph_snapshot**
```
输入: (无参数)
输出: 全图摘要
  - 总节点数 / 边数
  - 各类型节点数量
  - 各类型边数量
  - 按 exploration_status 分布的节点数
  - 按 verification_status 分布的边数
  - 最高度中心性 top-k 节点（默认 k=10）
  - 种子节点列表
  - 异常节点数和异常边数
```

#### 消歧

**identity_edge_create**
```
输入: node_a_id, node_b_id
输出: identity_edge_id
行为: 在两个节点间建立身份等价边（type=identity），初始 verification_status=unverified，intensity=0.3
```

**identity_edge_update**
```
输入: identity_edge_id, evidence_entry?, intensity?, verification_status? (unverified/confirmed/retracted)
输出: 更新后的 identity 边
行为: 追加证据到 identity_evidence 表。当 verification_status=confirmed 时，返回 merge 建议
```

**node_merge**
```
输入: [node_ids]
输出: merged_node_id
行为: 合并多个已确认 identity 的节点。
  - 保留最早创建的 id
  - 合并 body（LLM 负责融合两个 body 的内容）
  - 合并 source_chains（所有 source_chain_entry 重指向合并节点）
  - 所有边重指向合并节点
  - 记录 merge_history
```

**node_unmerge**
```
输入: node_id, target_merge_event_index?
输出: 原始节点列表
行为: 从 merge_history 中找到合并前快照，拆回原节点。identity 边标记为 retracted
```

#### 报告

**report_summary**
```
输入: node_id
输出: 该节点为中心的结构化摘要
  - 基本信息（name, type, body, confidence）
  - 关系列表（所有关联边 + 邻居节点摘要）
  - 异常标记
  - 来源评级汇总（source_reliability × info_credibility 分布）
  - 缺口清单（该节点的缺失维度）
```
行为: 只读，不产生副作用。供 Skill 在生成全景报告时调用。

### 数据模型

详见 [data-model.md](data-model.md)。


## Skill: investigation.md

### 定位

Claude Code 主 agent 的控制逻辑文件。包含完整的调查工作流、决策规则、SATs 执行策略。

### 流程定义

#### 阶段 0：启动

**触发**：用户提供种子实体信息

**步骤**：
1. 收集必需信息
   - 种子实体名称（必填）
   - 实体类型（选填，自由文本，如 person / organization / malware_sample / ...）
   - 已知附加信息（选填，越多越好——任何有助于定位目标的线索）
   - 调查目标（选填，自由文本，用户说什么就存什么）
   - 深度上限（选填，默认 3 跳）

2. 创建调查会话
   - 调用 session_create(workspace_path, name, goal, depth_limit)
     → MCP Server 在工作区下创建 "{timestamp}-{name}/" 目录 + case.db
   - 调用 node_create 创建种子节点
   - 将用户提供的已知线索写入 body（Markdown 格式），source_chain_entry 标记为 user_provided

3. 向用户汇报
   - 确认种子信息
   - 报告初始调查策略（目标→探索方向）
   - 请求确认开始

#### 阶段 1-N：调查循环

**单轮步骤**：

**1. 读图** — 通过 `graph_snapshot` 和 `node_list_gaps` 获取当前图谱全貌。

**2. 识别待办项** — 从图谱中抽取三类待办：
- 实体缺口：exploration_status = unexplored / exploring / partial / skipped 的节点
- 验证缺口：verification_status = unverified / contradicted 的边
- 消歧缺口：identity 边中状态 = unverified 的条目

**3. 优先级排序** — 对每项待办打分。公式详见 data-model.md，维度概述：
- 矛盾信号（权重 0.30）：contradicted_by 非空或 anomaly_flags 非空 = 最高优先级
- 目标匹配（权重 0.25）：LLM 评估该待办与用户调查目标的相关度（1-10 分）
- 网络位置（权重 0.20）：高中心性的节点优先，桥接节点的未知属性优先
- 信息杠杆（权重 0.15）：验证此待办可连带加固多少条弱边
- 时效性（权重 0.10）：最近发现的、尚未被处理的优先
- （假设区分力 — Phase 4 加入，依赖 ACH 矩阵）

**4. 编译搜索任务** — 将 top-K 待办项翻译为可执行的搜索指令。每条指令包含：
- 目标实体（及其已知信息，从 node.body 中提取，用于消歧）
- 信息维度（主 Agent 根据实体类型和调查目标**动态决定**搜什么维度，不查静态映射表）
- 为什么查这个（任务背景，方便子 agent 理解上下文）
- 期望产出

**5. 分派子 agent** — 独立任务并行分派。这是主 Agent 获取外部信息的**唯一途径**——主 Agent 不直接调用 WebSearch 或 WebFetch。

通过 Claude Code 的 `Agent` 工具分派。子 agent 类型：

| 子 Agent | 职责 | 使用的工具 |
|---|---|---|
| Web 搜索 Agent | 通用网络搜索与网页抓取 | WebSearch, WebFetch |
| （后续扩展）工商查询 Agent | 企业信用信息查询 | 专用 API |
| （后续扩展）裁判文书 Agent | 司法文书检索 | 专用 API |
| （后续扩展）社交媒体 Agent | 社交媒体信息采集 | 专用 API |

MVP 阶段仅实现 Web 搜索 Agent，覆盖所有公开网络信息来源。后续阶段按需扩展专用 Agent。

每个子 agent 接收结构化任务描述，返回结构化 JSON：
```
{
  new_entities: [{type, name, body, source_chain_entry}],
  new_edges: [{source_type, source_name, target_type, target_name, edge_type, direction, body, source_chain_entry}],
  gaps_discovered: [{entity_name, missing_dimension}],
  errors: [{task, reason}]
}
```

**6. 结果入库** — 逐条处理子 agent 返回结果：
- **来源评级审核**：主 agent 审核子 agent 对每条数据打的双三角评级，对明显不合理的评级予以调整
- **消歧检查**：每个新实体的 name 与图中已有实体比对（name 完全相同 + type 相同 → 调用 identity_edge_create 建立 identity 边；编辑距离 ≤ 2 → 标记需审核）
- **实体入库**：调用 `node_create` 逐个创建实体。body 为 Markdown 格式，包含子 agent 提供的该实体的全部信息
- **关系入库**：调用 `edge_create`。MCP Server 处理机械去重（同 source+target+type+direction → 追加 source_chain 而非新建边）
- **矛盾检测**（LLM 执行）：主 agent 读已有边/节点的 body 和所有 source_chain.raw_data，与新来源比较。发现实质冲突 → 更新 contradicted_by 或 anomaly_flags。发现独立印证 → 考虑升级 verification_status
- **交叉验证**（LLM 执行）：主 agent 判断新来源是否独立印证已有信息，是则升级 verification_status 为 verified。不自动升级

**7. 刷新分析** — 本轮数据入库后，重新评估：
- **结构异常检测**（S1-S4，MCP/graph_snapshot 机械执行）：环形依赖、同地址集群、一度多连、桥接节点低度
- **内容异常检测**（C1-C2, T1-T2，LLM 执行）：多源冲突、合并后冲突、时间线异常、模式异常
- **网络指标**（每轮）：通过 graph_snapshot 获取各节点的度中心性
- **ACH 矩阵**（Phase 4）：新信息对每个假设的影响
- **情景评估**（Phase 4）：多情景生成

**8. 判断下一步**：
- 发现高价值异常 → 通知用户，询问方向
- 连续 N 轮无明显进展 → 通知用户，建议暂停或调整方向
- 未达深度上限且仍有高分待办 → 自动继续下一轮
- 达到深度上限 → 汇报进展，询问是否继续

#### 交付阶段：全景报告

**触发**：用户说"出报告"或调查自然终止

**报告结构**：
1. 调查概要（种子、目标、轮次、覆盖维度）
2. 核心实体全景画像（结构化信息 + 置信度 + 来源追溯）
3. 关键关系路径图（Mermaid 文本格式，可渲染）
4. 异常发现清单（每条异常 + 证据 + 评级）
5. 多情景分析（ACH 矩阵 + 各情景支撑证据 + 薄弱环节）
6. 时间序列（关键事件和关系变化的时间线）
7. 剩余缺口清单（还没查清的，标注优先级）
8. 证据链追溯（每条关键结论→原始来源→双三角评级）

**输出格式**：
- Markdown 报告（用户默认接收）
- DOCX 报告（可选，通过 agentdocx 生成，保留证据来源批注）


## 子 Agent 合约

### 输入

```
{
  task_id: uuid,
  target: { name, type, known_info },
  investigation_dimension: "由主 Agent 根据实体类型和调查目标动态指定",
  context: "为什么查这个，相关的已有图谱上下文（含相关节点的 body 摘要）",
  expected_output: "主 Agent 指定的期望信息维度"
}
```

### 输出

```
{
  task_id: uuid,
  new_entities: [
    {
      name: "实体名称",
      type: "实体类型（自由字符串）",
      body: "Markdown 文本。关于此实体的所有已知信息。结构化事实和叙述放在一起。",
      source_chain_entry: {
        source_name: "来源名称",
        source_type: "来源类型（自由字符串）",
        source_reliability: "A/B/C/D/E/X",
        info_credibility: "1/2/3/4/5/6"
      }
    }
  ],
  new_edges: [
    {
      source_name: "源实体名称", source_type: "源实体类型",
      target_name: "目标实体名称", target_type: "目标实体类型",
      edge_type: "关系类型（自由字符串）",
      direction: "directed/undirected",
      body: "Markdown 文本。关于此关系的所有已知信息。",
      source_chain_entry: { ... }
    }
  ],
  gaps_discovered: [
    { entity_name: "实体名称", missing_dimension: "缺失的信息维度" }
  ],
  errors: []
}
```

### 设计原则

- 子 agent 不直接写图。它没有图数据库的访问权限。所有结果返回给主 agent，由主 agent 完成消歧、评级、入库。
- 子 agent 接收的上下文足够让它在搜索时做消歧（比如"张三，北京，45岁，A建设公司法人——搜这个名字时用这些信息过滤掉明显不相关的结果"），但不参与最终合并决策。
- 输出是结构化的，不是自然语言报告。实体和关系的字段越完整越好。


## 开发路线

### Phase 1: MCP Server 最小可用

工具（9 个）：
- session_create, session_get
- node_create, node_get, node_update, node_search
- edge_create, edges_from_node
- graph_snapshot

底层：SQLite，5 张表（sessions, nodes, edges, source_chains, merge_history）。

MCP Server 内部逻辑：
- edge_create 的去重检查（同 source+target+type+direction → 追加 source_chain 而非新建边）
- graph_snapshot 的度中心性实时计算
- 不包含矛盾检测和交叉验证判断——这些由主 Agent（LLM）在入库阶段执行

目标：能通过 Claude Code 手工调 MCP 工具完成：创建会话 → 创建节点 → 创建边 → 查邻居 → 看图快照。

### Phase 2: Skill + Web 搜索 Agent

**Skill（investigation.md）**：
- 阶段 0：交互式种子收集，创建会话和种子节点
- 阶段 1（单轮）：读图 → 找缺口 → 排优先级 → 编译任务 → 分派 Web 搜索 Agent → 结果入库
- 交付：生成 Markdown 全景报告

**Web 搜索 Agent（web-search-agent.md）**：
- 接收结构化搜索任务（目标实体 + 信息维度 + 上下文）
- 使用 WebSearch + WebFetch 搜集信息
- 返回结构化 JSON（新实体 + 新边 + 缺口 + 每条数据的双三角评级）

目标：输入"张三，北京，建筑行业"，主 Agent 完成种子创建 → 编译搜索任务 → 分派 Web 搜索 Agent → 入库结果 → 生成初步全景报告。

### Phase 3: 完整循环

- 实现多轮循环（缺口驱动下一轮搜索）
- 消歧机制（identity 边 + identity_evidence 表）
- 异常检测（S1-S4 结构规则 + C1-C2/T1-T2 LLM 判断）
- 目标：能自主完成 3+ 轮搜索，产出初步全景报告

### Phase 4: 分析方法论

- ACH 矩阵逻辑（skill 中手写规则 + 判断）
- 情景生成
- 优先级排序的完整打分逻辑

### Phase 5: 体验优化

- 进度通知（每轮结束后的简洁汇报）
- 用户中途介入（"查另一个方向"）
- 缓存和去重
- 性能优化（大图下的图查询）
- 扩展专用子 Agent（工商查询、裁判文书等）


## 关键设计决策

### 为什么 MCP Server 不放图分析

MCP Server 只放原子操作（CRUD + 邻居查询 + 最短路径）。网络分析（中心性、聚类）如果在 server 里做了就跑偏了——那属于决策层。

但 `graph_snapshot` 是必要的——它是主 agent 读图的入口，减少重复的 node_get 调用。

### 为什么主 Agent 不直接搜索

主 Agent 不调用 WebSearch、WebFetch 或任何外部 API。所有对外信息搜集由子 Agent 完成。

原因：
- **职责分离**：主 Agent 的上下文用于图分析、缺口判断、优先级排序——这些需要全局视野。混入搜索结果的原始文本会污染上下文。
- **并行性**：多个子 Agent 可以并行搜索不同目标，主 Agent 保持轻量状态等结果汇总。
- **可扩展性**：新增信息源只需新增子 Agent，主 Agent 逻辑不变。

简言之：主 Agent = 大脑（思考、判断、调度），子 Agent = 触手（搜集、返回）。

### 为什么子 agent 不调 MCP

子 agent 没有图数据库访问权限。它不知道图谱里有什么。它只是一个信息采集器——接收查询指令，返回结构化的新信息。所有写入由主 agent 做。

这保证了：消歧逻辑只在一处（主 agent），不会出现"子 agent A 合并了两个张三、子 agent B 没合并"的混乱。

### 为什么用 SQLite 起步

- 零配置、零运维
- 单文件存储，案件隔离简单（一个案件一个 DB 或一个表前缀）
- 在调查规模下（几百到几千个节点）完全够用
- 未来换 Neo4j 时，MCP Server 的工具接口不变

### 为什么报告写两份

Markdown 是默认格式（轻量、聊天直接发送）。DOCX 是通过 agentdocx 生成的（适用于正式的尽调报告场景，需要批注和修订标记）。用户自己选。
