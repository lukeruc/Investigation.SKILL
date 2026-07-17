---
title: 调查图谱 — 设计文档
version: 1.0
date: 2026-07-16
depends: investigation-graph-concept.md, data-model.md
status: 待实现
---

# 设计文档

本文档是调查图谱项目的权威实现规格。基于概念文档和数据模型，给出具体的技术方案、接口定义、文件结构和实现计划。

---

## 1. 交互模式与工作区

### 1.1 工作区模型

```
~/investigations/                    ← 工作区（用户在此打开 Claude Code）
├── 2026-07-16-143052-调查张三/      ← 案件目录（时间戳 + 名称）
│   ├── case.db                      ← SQLite 数据库
│   ├── reports/                     ← 生成的报告
│   └── evidence/                    ← 下载的附件、截图
├── 2026-07-17-090000-调查李四/
│   └── case.db
└── ...
```

- 用户在某个路径下打开 Claude Code → 该路径即为**工作区**
- 调用 investigation Skill，发起调查 → 在工作区下新建 `{时间戳}-{名称}/` 文件夹作为**案件目录**
- 案件目录内创建 `case.db`，包含该调查的全部数据
- 隔离方式：**一个案件 = 一个文件夹 = 一个 SQLite 文件**。MCP Server 同时只维护一个活跃数据库连接

### 1.2 架构总览

```
┌──────────────────────────────────────────────────┐
│               Claude Code 对话会话                 │
│                                                    │
│  工作区: ~/investigations/                         │
│  当前案件: 2026-07-16-143052-调查张三/case.db       │
│                                                    │
│  ┌─────────────────────┐  ┌───────────────────┐   │
│  │  investigation.md    │  │ web-search-agent  │   │
│  │  (主 Agent Skill)    │  │ (子 Agent Skill)  │   │
│  │                     │  │                   │   │
│  │  读图→判断→调度     │  │  WebSearch        │   │
│  │  →入库→分析→报告    │  │  + WebFetch       │   │
│  └──────┬──────────────┘  └───────────────────┘   │
│         │ 调用                     ↑ 分派           │
│         ↓                         │                │
│  ┌──────────────────────────────────────┐         │
│  │   MCP Server (Python / FastMCP)       │         │
│  │   活跃 DB: 当前案件的 case.db          │         │
│  │   工具: 无 session_id 参数             │         │
│  └──────────────────────────────────────┘         │
└──────────────────────────────────────────────────┘
```

**数据流向**：
1. 用户触发 investigation Skill → 阶段 0：收集种子 → `session_create(workspace, name)` 创建案件目录 + case.db → MCP Server 切换活跃连接到此 DB
2. 阶段 1-N 每轮循环：读 `graph_snapshot` + `node_list_gaps` → 识别待办 → 打分排序 → 编译搜索任务 → 分派 web-search-agent → 子 Agent 返回 JSON → 主 Agent 消歧 → `node_create` / `edge_create` 入库 → 读 `graph_snapshot` 确认状态 → 判断是否继续
3. 交付阶段：`graph_snapshot` + `edges_from_node` + `report_summary` → 组织 Markdown 报告 → 写入案件目录 `reports/`

**关键约束**：
- 主 Agent 不直接调用 WebSearch、WebFetch 或任何外部 API
- 子 Agent 不调用 MCP 工具（无图数据库访问权限）
- MCP Server 不包含决策逻辑
- 所有工具操作当前活跃的案件数据库（无 session_id 参数）

---

## 2. 文件结构

```
intelligence-graph/
├── investigation-graph-concept.md    # 概念文档
├── data-model.md                     # 数据模型
├── design-doc.md                     # 本文件
│
├── mcp-server/                       # MCP Server（Python）
│   ├── pyproject.toml
│   ├── server.py                     # 入口，FastMCP 实例
│   ├── database.py                   # SQLite 连接管理 & schema 初始化
│   ├── models.py                     # 数据校验 & 类型定义
│   └── tools/
│       ├── __init__.py
│       ├── sessions.py               # session_create, session_open, session_get
│       ├── nodes.py                  # node_create, node_get, node_update,
│       │                               node_search, node_list_gaps
│       ├── edges.py                  # edge_create, edge_get, edge_update,
│       │                               edges_from_node
│       ├── graph.py                  # graph_path, graph_neighbors, graph_snapshot
│       ├── identity.py               # identity_edge_create, identity_edge_update,
│       │                               node_merge, node_unmerge
│       └── reports.py                # report_summary
│
├── skills/                           # Claude Code Skills
│   ├── investigation.md              # 主 Agent Skill
│   └── web-search-agent.md           # Web 搜索子 Agent Skill
│
└── tests/                            # 测试
    └── ...
```

---

## 3. MCP Server 规格

### 3.1 技术栈

- **语言**：Python 3.11+
- **框架**：FastMCP（`mcp` 包）
- **数据库**：SQLite（`sqlite3` 标准库）。一个案件一个 `case.db`，MCP Server 维护一个活跃连接（`active_db` 模块变量）
- **传输**：stdio（Claude Code 标准 MCP 协议）
- **案件隔离**：文件系统。`session_create` 创建目录 + DB 并切换连接；`session_open` 切换到已有案件

### 3.2 数据库 Schema（DDL）

每个案件目录下的 `case.db` 包含以下表。无需 `session_id` 列——数据库文件本身就是隔离边界。

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL DEFAULT '',
    depth_limit INTEGER NOT NULL DEFAULT 3,
    round_number INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    seed_node_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (seed_node_id) REFERENCES nodes(id)
);

CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    exploration_status TEXT NOT NULL DEFAULT 'unexplored',
    confidence TEXT NOT NULL DEFAULT 'medium',
    anomaly_flags TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL
);

CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'directed',
    body TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    confidence TEXT NOT NULL DEFAULT 'medium',
    intensity REAL NOT NULL DEFAULT 0.5,
    contradicted_by TEXT NOT NULL DEFAULT '[]',
    anomaly_flags TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

CREATE TABLE source_chains (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'web_search',
    source_reliability TEXT NOT NULL DEFAULT 'X',
    info_credibility TEXT NOT NULL DEFAULT '6',
    discovery_time TEXT NOT NULL,
    discovery_agent TEXT,
    discovery_context TEXT,
    raw_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE merge_history (
    id TEXT PRIMARY KEY,
    merged_node_id TEXT NOT NULL,
    absorbed_node_ids TEXT NOT NULL,
    identity_edge_id TEXT,
    reason TEXT NOT NULL,
    evidence_snapshot TEXT,
    merged_at TEXT NOT NULL
);

CREATE TABLE identity_evidence (
    id TEXT PRIMARY KEY,
    identity_edge_id TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    signal_value TEXT,
    direction TEXT NOT NULL,
    weight TEXT NOT NULL DEFAULT 'medium',
    source_entry_id TEXT,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (identity_edge_id) REFERENCES edges(id),
    FOREIGN KEY (source_entry_id) REFERENCES source_chains(id)
);

-- 索引
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_nodes_status ON nodes(exploration_status);
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_type ON edges(type);
CREATE INDEX idx_edges_vstatus ON edges(verification_status);
CREATE INDEX idx_source_chains_target ON source_chains(target_type, target_id);
CREATE INDEX idx_merge_history_node ON merge_history(merged_node_id);
CREATE INDEX idx_identity_evidence_edge ON identity_evidence(identity_edge_id);
```

### 3.3 工具清单

MCP Server 维护一个活跃数据库连接（`active_db_path` 模块变量）。所有工具操作当前活跃数据库，无需 `session_id` 参数。返回值为 dict。错误通过抛出异常返回。

#### 3.3.1 会话操作

```
session_create(workspace_path: str, name: str, goal: str = "", depth_limit: int = 3) -> dict
    返回: { case_path, case_id, goal, depth_limit, created_at }
    行为:
      1. 在 workspace_path 下创建 "{timestamp}-{name}/" 目录
      2. 在该目录中创建 case.db，运行 schema DDL
      3. 将 MCP Server 活跃连接切换到此 case.db
      4. INSERT INTO sessions，返回案件信息

session_open(case_path: str) -> dict
    返回: { case_path, goal, depth_limit, round_number, status, ... }
    行为: 关闭当前活跃连接，打开 case_path/case.db 作为新的活跃连接

session_get() -> dict
    返回: { goal, depth_limit, round_number, status, seed_node_id, created_at, updated_at }
    行为: SELECT from sessions（当前活跃 DB 只有一行）
```

#### 3.3.2 实体操作

```
node_create(
    type: str,
    name: str,
    body: str = "",
    confidence: str = "medium",
    source_chain_entry: dict | None = None
) -> dict
    返回: { node_id, type, name, ... }
    行为: 生成 UUID，INSERT INTO nodes（当前活跃 DB）。若提供了 source_chain_entry，同时写入 source_chains

node_get(node_id: str) -> dict
    返回: 节点完整信息（body + 所有关联边列表 + source_chains 列表）

node_update(
    node_id: str,
    body: str | None = None,
    confidence: str | None = None,
    exploration_status: str | None = None,
    anomaly_flags: list[str] | None = None
) -> dict
    返回: 更新后的节点
    行为: 增量更新。body 非空时完全替换。自动更新 last_updated

node_search(
    type: str | None = None,
    name_pattern: str | None = None,
    limit: int = 50
) -> list[dict]
    返回: 匹配的节点列表（id, name, type, exploration_status）
    行为: name_pattern 做 LIKE '%pattern%'

node_list_gaps(type: str | None = None) -> list[dict]
    返回: exploration_status 为 unexplored/exploring/partial/skipped 的节点列表
```

#### 3.3.3 关系操作

```
edge_create(
    source_id: str,
    target_id: str,
    type: str,
    direction: str = "directed",
    body: str = "",
    intensity: float = 0.5,
    confidence: str = "medium",
    source_chain_entry: dict | None = None
) -> dict
    返回: { edge_id, created: bool, deduplicated: bool }
    行为:
      1. 检查是否已存在同 source_id+target_id+type+direction 的边
      2. 若存在 → 追加 source_chain_entry（如有），返回已有 edge_id
      3. 若不存在 → 创建新边。若提供了 source_chain_entry，写入 source_chains
      MCP Server 不做矛盾检测和交叉验证——由主 Agent（LLM）执行

edge_get(edge_id: str) -> dict
    返回: 边完整信息（body + source_chains 列表 + contradicted_by）

edge_update(
    edge_id: str,
    body: str | None = None,
    confidence: str | None = None,
    verification_status: str | None = None,
    intensity: float | None = None,
    anomaly_flags: list[str] | None = None,
    contradicted_by: list[dict] | None = None
) -> dict
    返回: 更新后的边

edges_from_node(
    node_id: str,
    edge_type: str | None = None,
    direction: str | None = None
) -> list[dict]
    返回: 该节点的所有关联边 + 邻居节点摘要（id, name, type）
```

#### 3.3.4 图分析

```
graph_path(
    source_node_id: str,
    target_node_id: str,
    max_depth: int = 5
) -> dict | None
    返回: { path: [{node_id, name, type}, ...], edges: [{edge_id, type}, ...] } 或 null
    行为: BFS 最短路径。max_depth 用于防止无限搜索

graph_neighbors(
    node_id: str,
    depth: int = 1
) -> list[dict]
    返回: 指定深度的邻居节点列表 + 路径边
    行为: 递归 BFS，depth=1 为直连邻居

graph_snapshot() -> dict
    返回: 全图摘要。结构见 §3.5
    行为: 执行多条聚合 SQL 查询，组装为单个响应
```

#### 3.3.5 消歧

```
identity_edge_create(
    node_a_id: str,
    node_b_id: str,
    match_basis: str = "name_match"
) -> dict
    返回: { identity_edge_id }
    行为: 创建 type="identity" 的边，verification_status="unverified"，intensity=0.3

identity_edge_update(
    identity_edge_id: str,
    evidence_entry: dict | None = None,
    intensity: float | None = None,
    verification_status: str | None = None
) -> dict
    返回: 更新后的 identity 边
    行为: 若提供了 evidence_entry，同时 INSERT INTO identity_evidence。
          若 verification_status 变为 "confirmed"，返回 merge 建议

node_merge(node_ids: list[str]) -> dict
    返回: { merged_node_id }
    行为: 合并节点。详见 data-model.md 消歧章节

node_unmerge(node_id: str, merge_event_index: int | None = None) -> list[dict]
    返回: 拆分后的原始节点列表
    行为: 从 merge_history 恢复
```

#### 3.3.6 报告

```
report_summary(node_id: str) -> dict
    返回: {
        node: {...},
        edges: [...],
        source_summary: { A1_count, B2_count, ... },
        anomaly_flags: [...],
        gaps: [...]
    }
    行为: 聚合查询，纯读取，不产生副作用
```

### 3.4 edge_create 内部逻辑（伪代码）

```python
def edge_create(source_id, target_id, type, direction, ...):
    # 1. 检查重复（机械匹配，不涉及语义判断）
    existing = db.query(
        "SELECT id FROM edges "
        "WHERE source_id=? AND target_id=? "
        "AND type=? AND direction=?",
        source_id, target_id, type, direction
    )

    if existing:
        edge_id = existing["id"]
        # 2. 追加 source_chain_entry
        if source_chain_entry:
            db.insert("source_chains", {
                target_type="edge", target_id=edge_id,
                **source_chain_entry
            })
        return {"edge_id": edge_id, "created": False, "deduplicated": True}

    # 3. 创建新边
    edge_id = new_uuid()
    db.insert("edges", {id=edge_id, source_id, target_id,
                        type, direction, ...})
    # 4. 写入来源链
    if source_chain_entry:
        db.insert("source_chains", {
            target_type="edge", target_id=edge_id,
            **source_chain_entry
        })
    return {"edge_id": edge_id, "created": True, "deduplicated": False}
```

注：矛盾检测和交叉验证不在 MCP Server 中执行。主 Agent（LLM）在入库阶段读已有边的 body 和所有 source_chain，判断是否存在矛盾或独立印证，然后通过 edge_update 更新 verification_status 和 contradicted_by。

### 3.5 graph_snapshot 实现

```python
def graph_snapshot() -> dict:
    return {
        "summary": {
            "total_nodes": db.count("nodes"),
            "total_edges": db.count("edges"),
            "session_round": db.scalar("SELECT round_number FROM sessions LIMIT 1")
        },
        "nodes_by_type": db.query_all(
            "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type"
        ),
        "edges_by_type": db.query_all(
            "SELECT type, COUNT(*) as cnt FROM edges GROUP BY type"
        ),
        "nodes_by_status": db.query_all(
            "SELECT exploration_status, COUNT(*) as cnt FROM nodes GROUP BY exploration_status"
        ),
        "edges_by_vstatus": db.query_all(
            "SELECT verification_status, COUNT(*) as cnt FROM edges GROUP BY verification_status"
        ),
        "top_central_nodes": db.query_all(
            "SELECT n.id, n.name, n.type, "
            " (SELECT COUNT(*) FROM edges WHERE source_id=n.id) + "
            " (SELECT COUNT(*) FROM edges WHERE target_id=n.id) as degree "
            "FROM nodes n ORDER BY degree DESC LIMIT 10"
        ),
        "seed_nodes": db.query_all(
            "SELECT n.id, n.name, n.type FROM nodes n "
            "JOIN sessions s ON s.seed_node_id = n.id"
        ),
        "anomaly_counts": {
            "nodes_with_anomalies": db.count(
                "nodes", "anomaly_flags != '[]'"
            ),
            "edges_with_anomalies": db.count(
                "edges", "anomaly_flags != '[]'"
            )
        }
    }
```

### 3.6 source_chain_entry 规格

`node_create` 和 `edge_create` 接受的可选参数。定义如下：

```python
{
    "source_name": str,           # 必填。来源名称
    "source_type": str,           # 必填。来源类型（自由字符串）
    "source_reliability": str,    # 选填，默认 "X"。A/B/C/D/E/X
    "info_credibility": str,      # 选填，默认 "6"。1/2/3/4/5/6
    "discovery_time": str,        # 选填，默认当前 ISO 8601 时间
    "discovery_agent": str,       # 选填
    "discovery_context": str,     # 选填。发现上下文描述
    "raw_data": str               # 选填，默认 "{}"。原始返回数据快照
}
```

MCP Server 在写入 `source_chains` 表时自动补全默认值。`source_reliability` 和 `info_credibility` 默认为最低评级，鼓励调用者显式赋值。

### 3.7 错误处理约定

所有工具在失败时返回 `{"error": "<code>", "detail": "<描述>"}`。MCP 协议不抛异常（异常会导致连接断开），所有错误通过返回值报告。

| 错误码 | 触发条件 | 示例 |
|---|---|---|
| `not_found` | node_get/edge_get/node_update/edge_update 传入不存在的 id | `{"error": "not_found", "detail": "node abc123 not found"}` |
| `invalid_reference` | edge_create 的 source_id 或 target_id 在 nodes 表中不存在 | `{"error": "invalid_reference", "detail": "source_id xyz not found"}` |
| `case_not_found` | session_open 传入的路径不存在或路径下无 case.db | `{"error": "case_not_found", "detail": "path /tmp/xxx does not contain case.db"}` |
| `already_exists` | session_create 的目标目录已存在且包含 case.db | `{"error": "already_exists", "detail": "case already exists at /tmp/xxx"}` |
| `no_active_db` | 在未调用 session_create 或 session_open 前调用了其他工具 | `{"error": "no_active_db", "detail": "no active case. call session_create or session_open first"}` |

对于非预期的异常（磁盘满、SQLite 损坏、权限不足），直接抛出 Python 异常——MCP 协议自动捕获并转为错误响应，无需手动包装。

### 3.8 MCP Server 配置

`pyproject.toml`：

```toml
[project]
name = "investigation-graph-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["mcp>=1.0.0"]

[project.scripts]
investigation-graph = "server:main"
```

Claude Code 的 MCP 配置（在 `settings.json` 中）：

```json
{
  "mcpServers": {
    "investigation-graph": {
      "command": "python",
      "args": ["-m", "server"],
      "cwd": "${workspace}/mcp-server"
    }
  }
}
```

---

## 4. Web 搜索 Agent 规格

### 4.1 定位

Web 搜索 Agent 是 MVP 阶段的唯一子 Agent。它接收搜索任务，使用 WebSearch + WebFetch 搜集信息，返回结构化结果。

它是一个 Claude Code Skill（`web-search-agent.md`），由主 Agent 通过 `Agent` 工具分派。

### 4.2 输入合约

主 Agent 发送给 Web 搜索 Agent 的 prompt 格式：

```markdown
## 搜索任务

**任务 ID**: {{task_id}}
**目标实体**: {{entity_name}}（类型: {{entity_type}}）
**已知信息**: {{known_info}}
**信息维度**: {{dimension}}  （如：工商任职、涉诉记录、网络舆情、联系方式）
**任务背景**: {{context}}
**期望产出**: {{expected_output}}

## 输出格式要求

请严格按照以下 JSON 格式返回结果，不要包含任何其他文字：

{
  "task_id": "uuid",
  "new_entities": [
    {
      "name": "实体名称",
      "type": "实体类型（自由字符串）",
      "body": "Markdown 文本。关于此实体的所有已知信息。结构化事实和叙述放在一起。",
      "source_chain_entry": {
        "source_name": "来源名称",
        "source_type": "来源类型（自由字符串）",
        "source_reliability": "A/B/C/D/E/X",
        "info_credibility": "1/2/3/4/5/6"
      }
    }
  ],
  "new_edges": [
    {
      "source_name": "源实体名称",
      "source_type": "源实体类型",
      "target_name": "目标实体名称",
      "target_type": "目标实体类型",
      "edge_type": "关系类型（自由字符串）",
      "direction": "directed/undirected",
      "body": "Markdown 文本。关于此关系的所有已知信息。",
      "source_chain_entry": { ... }
    }
  ],
  "gaps_discovered": [
    { "entity_name": "实体名称", "missing_dimension": "缺失的信息维度" }
  ],
  "errors": []
}
```

### 4.3 输出合约

与输入中的 JSON schema 一致。主 Agent 解析 JSON 后执行入库。

### 4.4 双三角评级指南

Web 搜索 Agent 在 `source_chain_entry` 中对每条信息评级：

**来源可靠性**：
- A: 官方数据库、政府网站、司法文书直接返回
- B: 权威数据平台、知名媒体
- C: 一般正规媒体、官方网站、行业数据库
- D: 自媒体、个人博客、匿名帖子
- E: 已知虚假信息源
- X: 无法评估（默认）

**信息可信度**：
- 1: 多源一致确认
- 2: 与已知信息自洽
- 3: 合理但单一来源
- 4: 与其他信息矛盾
- 5: 很可能虚假
- 6: 无法判断（默认）

### 4.5 Web 搜索 Agent Skill 文件结构

```
---
name: web-search-agent
description: 执行网络搜索任务，返回结构化实体和关系信息
tools: WebSearch, WebFetch
---

# Web 搜索 Agent

你是一个信息搜集 agent。你的任务是接收搜索指令，从公开网络
来源搜集信息，并以结构化 JSON 格式返回结果。

## 工作步骤

1. 解析搜索任务中的目标实体、信息维度、已知属性
2. 使用 WebSearch 搜索（中文优先，必要时使用英文）
3. 对关键结果使用 WebFetch 获取详细内容
4. 从网页内容中提取：
   - 新实体及其 body（Markdown 格式，包含所有已知信息）
   - 关系及其 body（Markdown 格式）
   - 缺口（发现了新名字但信息不完整）
5. 为每条信息评定双三角评级
6. 严格按 JSON schema 输出，不要包含任何其他文字
```

---

## 5. 主 Agent Skill 规格

### 5.1 文件结构

```
---
name: investigation
description: 调查图谱主控制逻辑。输入种子实体，多轮搜索构建全景画像
dependencies:
  mcp: [investigation-graph]
  skills: [web-search-agent]
---

# 调查图谱

...（详细流程）
```

### 5.2 阶段 0：启动

**触发**：用户说"调查 XXX"或类似意图

**步骤**：

```
0.1 收集种子信息
    - 若用户只给了名称 → 追问：entity_type? 已知线索? 调查目标? 深度?
    - 若用户给了完整信息 → 直接确认

0.2 调用 session_create(workspace_path, name, goal, depth_limit)
    → MCP Server 创建 "{timestamp}-{name}/" 目录 + case.db
    → 返回 case_path

0.3 调用 node_create(
        type=entity_type,
        name=seed_name,
        body=user_provided_info_markdown,
        source_chain_entry={
            source_name: "用户提供",
            source_type: "user_provided",
            source_reliability: "A",
            info_credibility: "3"
        }
    )

0.4 向用户汇报确认信息
    - 种子: {name} ({type})
    - 目标: {goal}
    - 深度上限: {depth_limit} 跳
    - 开始调查？(用户确认)
```

### 5.3 阶段 1-N：调查循环

**单轮执行流程**：

```
Round N:

1. 读图
   snapshot = graph_snapshot()
   gaps = node_list_gaps()
   → 理解当前图谱全貌

2. 识别待办
   - 实体缺口: gaps 中 exploration_status∈{unexplored,exploring,partial,skipped} 的节点
   - 验证缺口: snapshot 中 verification_status∈{unverified,contradicted} 的边
   - 消歧缺口: type="identity" 且 verification_status="unverified" 的边
   → 编译为待办列表

3. 优先级排序
   - 对每项待办按 data-model.md 中的公式打分
   - 矛盾信号 > 目标匹配 > 网络位置 > 信息杠杆 > 时效性
   → 取 top-K（K = 3~5，取决于节点数量）

4. 编译搜索任务
   - 将每项待办翻译为搜索指令
   - 包含：目标实体 + 从 node.body 提取的已知信息 + 信息维度 + 上下文 + 期望产出
   → 每项待办生成一个子 Agent prompt

5. 分派子 Agent（并行）
   - 使用 Agent 工具分派 web-search-agent
   - 等待所有子 Agent 返回
   → 收集所有结构化 JSON 结果

6. 结果入库
   - 对每个返回的 new_entities:
     a. 消歧检查：node_search(name_pattern=name, type=type)
        → 发现同名候选 → identity_edge_create → 标记待后续验证
     b. 审核双三角评级（不合理则调整）
     c. node_create(type, name, body, source_chain_entry=...)
     d. 将该实体状态改为 exploring（防止下一轮重复搜索）
   - 对每个返回的 new_edges:
     a. 解析 source_name/target_name → 查找对应 node_id
     b. edge_create(source_id, target_id, type, direction, body, source_chain_entry=...)
        → MCP Server 处理机械去重
     c. LLM 执行矛盾检测：读已有边 body + 所有 source_chain.raw_data，比较新来源。
        发现冲突 → edge_update(contradicted_by=[...])
        发现独立印证 → edge_update(verification_status="verified")
   - 将完成探索的节点的 exploration_status 改为 explored 或 partial

7. 刷新分析
   - 重新读 graph_snapshot()
   - 检查异常节点和异常边
   - 发现异常 → 在对话中标注，询问用户是否需要深入

8. 判断下一步
   - 达到 depth_limit → 报告进展，询问是否继续
   - 仍有高分待办 → 自动进入下一轮（向用户报告本轮摘要后继续）
   - 无明显进展连续 2 轮 → 告知用户，建议调整方向或出报告

9. 更新 round_number
   - MCP Server 层面更新 sessions.round_number += 1
```

### 5.4 交付阶段：全景报告

**触发**：用户说"出报告"或调查自然终止

**生成步骤**：

```
1. 汇总数据
   snapshot = graph_snapshot()
   对每个重要节点调 report_summary(node_id)

2. 生成报告（8 节，Markdown）
   1. 调查概要 — 种子、目标、轮次、覆盖维度
   2. 核心实体全景 — 结构化信息 + 置信度
   3. 关键关系路径 — Mermaid graph TD 格式
   4. 异常发现清单 — 每条异常 + 证据描述
   5. 多情景分析 — （Phase 4）ACH 矩阵
   6. 时间序列 — 关键事件时间线
   7. 剩余缺口清单 — 未完成探索的节点 + 优先级
   8. 证据链追溯 — 关键结论 → 原始来源 → 双三角评级

3. 输出
   - 默认：在对话中直接输出 Markdown
   - 可选：通过 agentdocx 生成 DOCX
```

### 5.5 状态追踪

主 Agent 在对话上下文中维护以下追踪变量（不持久化到 MCP）：

- `current_round`: 当前轮次（同时存储在 sessions.round_number）
- `last_snapshot_summary`: 上次 graph_snapshot 的摘要（用于比较进展）
- `consecutive_no_progress`: 连续无明显进展的轮数

若对话上下文被压缩，可通过 `session_get()` 和 `graph_snapshot()` 完全重建状态。

---

## 6. 数据流示例

以"调查张三，北京，建筑行业"为例，走一遍完整的 Round 1：

### 阶段 0

```
用户: 调查张三，person 类型，建筑行业，目标是全景画像，深度 3 跳

主 Agent:
  session_create(workspace_path="~/investigations", name="调查张三",
                 goal="了解张三的商业关联全景", depth_limit=3)
  → case_path = "~/investigations/2026-07-16-143052-调查张三/"
  → MCP Server 活跃连接已切换到该案件 DB

  node_create(
    type="person",
    name="张三",
    body="## 已知信息\n- 行业: 建筑行业\n- 所在地: 北京",
    source_chain_entry={source_name:"用户提供", source_type:"user_provided",
                        source_reliability:"A", info_credibility:"3"}
  )
  → node_id = "node-001"

主 Agent 向用户确认后开始 Round 1
```

### Round 1

```
步骤 1: graph_snapshot()
→ { total_nodes: 1, total_edges: 0, seed_nodes: ["node-001/张三/person"], ... }

步骤 2: node_list_gaps()
→ [{ id: "node-001", name: "张三", type: "person", exploration_status: "unexplored" }]

步骤 3: 唯一的待办 = 探索"张三"这个节点。得分 = 1.0（种子节点）

步骤 4: 编译搜索任务 prompt（发送给 Web 搜索 Agent）

步骤 5: 分派 Web 搜索 Agent

步骤 6: Web 搜索 Agent 返回（示意）:
{
  task_id: "task-001",
  new_entities: [
    {
      name: "A建设有限公司",
      type: "organization",
      body: "## 工商登记\n- 统一社会信用代码: 91110...\n- 经营状态: 存续",
      source_chain_entry: { source_name: "天眼查", source_type: "data_platform",
                            source_reliability: "B", info_credibility: "2" }
    },
    ...
  ],
  new_edges: [
    {
      source_name: "张三", source_type: "person",
      target_name: "A建设有限公司", target_type: "organization",
      edge_type: "employment", direction: "directed",
      body: "## 任职\n- 职位: 执行董事",
      source_chain_entry: { source_name: "天眼查", source_type: "data_platform",
                            source_reliability: "B", info_credibility: "2" }
    },
    ...
  ],
  gaps_discovered: [...],
  errors: []
}

步骤 6 (续): 入库
  - 对每个 new_entity: node_search(name_pattern=name, type=type)
    → 都是新实体，无撞名
  - node_create("organization", "A建设有限公司", body=...)
    → node-002
  - node_create("organization", "B房地产开发公司", body=...)
    → node-003
  - node_create("phone", "138xxxx1234", body=...)
    → node-004
  - 对每个 new_edge: edge_create(...)
    → edge-001, edge-002, edge-003
  - LLM 读各边 body + source_chain，判断无矛盾，两来源印证 → 升级 verification_status
  - 将 node-001 的 exploration_status 更新为 partial

步骤 7: graph_snapshot()
→ { total_nodes: 4, total_edges: 3, ... }
  无异常

步骤 8: 判断
  - 未达 depth_limit (3)，有 unexplored/partial 节点
  → 自动进入 Round 2

步骤 9: sessions.round_number = 2
```

---

## 7. 实现计划

### Phase 1: MCP Server 最小可用

**目标**：MCP Server 可运行，9 个核心工具可通过 Claude Code 手工调用。

**交付物**：
```
mcp-server/
├── pyproject.toml
├── server.py
├── database.py
├── models.py
└── tools/
    ├── __init__.py
    ├── sessions.py
    ├── nodes.py
    ├── edges.py
    ├── graph.py
    └── reports.py
```

**工具范围**（11 个）：session_create, session_open, session_get, node_create, node_get, node_update, node_search, node_list_gaps, edge_create, edges_from_node, graph_snapshot

**不包含**（Phase 3）：graph_path, graph_neighbors, 消歧 4 工具（identity_edge_create, identity_edge_update, node_merge, node_unmerge）, report_summary, edge_get, edge_update

**状态**：Phase 3 工具已在实现中，详见 `doc/phase3-execution-plan.md`。

**核心实现要点**：
- `database.py`：活跃连接管理（`active_db` 变量）、schema 自动初始化（CREATE TABLE IF NOT EXISTS）、DB 切换（`switch_db(path)`）。MCP Server 重启后连接丢失，用户需 `session_open` 重建（无状态设计，不自动恢复）
- `edge_create`：去重逻辑（同 source+target+type+direction → 追加 source_chain 而非新建边）
- `graph_snapshot`：§3.5 的 SQL 实现（度中心性实时计算）
- body 字段为纯文本，MCP 不做内容解析

**测试标准**：Phase 1 手工测试，Phase 2+ 引入自动化。手工测试套件 ——
```
1. session_create(workspace="/tmp/test", name="测试调查") → 创建目录 + case.db，返回 case_path
2. node_create("person", "张三", body="行业: 建筑") → 拿到 node_id
3. node_get(node_id) → 返回完整信息（含 body）
4. node_create("organization", "A公司") → 第二个节点
5. edge_create(张三_id, A公司_id, "employment", body="职位: 总经理") → 边创建
6. edges_from_node(张三_id) → 返回边 + A公司摘要
7. edge_create(张三_id, A公司_id, "employment",
               source_chain_entry={source_name:"天眼查", source_type:"data_platform"})
   → 应返回 deduplicated=true
8. graph_snapshot() → { total_nodes: 2, total_edges: 1, ... }
9. node_list_gaps() → 列出 exploration_status=unexplored 的节点
10. node_update(node_id, exploration_status="explored") → 状态变更
11. session_open("/tmp/test/2026-07-16-xxxxxx-测试调查/") → 切换到已有案件
```

**预估工作量**：1-2 天

### Phase 2: Skill + Web 搜索 Agent

**目标**：端到端跑通一个单轮调查——输入种子，自动搜索，入库，出报告。

**交付物**：
```
skills/
├── investigation.md
└── web-search-agent.md
```

**实现要点**：
- `investigation.md` 实现阶段 0（交互式收集）→ 阶段 1（单轮搜索+入库）→ 交付（Markdown 报告）
- `web-search-agent.md` 实现搜索→解析→结构化输出
- 主 Agent 通过 `Agent` 工具分派 Web 搜索 Agent
- 主 Agent 解析子 Agent 返回的 JSON，调 MCP 工具入库
- 报告生成：调用 graph_snapshot + edges_from_node，组织为 Markdown

**测试标准**：
```
输入: "调查张三，person，北京建筑行业"
预期:
  1. 主 Agent 收集信息、确认、创建 session + 种子节点
  2. 编译搜索任务、分派 Web 搜索 Agent
  3. Web 搜索 Agent 返回结构化结果
  4. 主 Agent 入库（节点 + 边）
  5. 生成 Markdown 全景报告（含 Mermaid 关系图）
```

**预估工作量**：2-3 天

### Phase 3: 完整循环

**目标**：多轮搜索、消歧、异常检测、3+ 轮自动调查。

**状态**：正在进行中，执行方案见 `doc/phase3-execution-plan.md`。当前已完成工作项：
- 工作流改为完全串行：搜索与分析串行执行，下一轮搜索方向由 `analysis-agent` 的 `next_round_hints` 决定。
- 实现 `edge_get` / `edge_update` / `graph_path` / `graph_neighbors` / `identity_edge_create` / `identity_edge_update` / `node_merge` / `node_unmerge` / `report_summary`。
- `analysis-agent` 的 `next_round_hints` 扩展为可直接翻译为搜索任务的结构。
- 异常检测规则 S1-S4 / C1-C2 / T1-T2 在 `analysis-agent.md` 中落地。

**新增逻辑**：
- Skill 中多轮循环的终止条件与用户交互
- exploration_status 的完整 6 状态流转
- 消歧流程（identity 边 + identity_evidence 累积）
- 异常检测规则：S1-S4（机械）+ C1-C2/T1-T2（LLM 判断）

**预估工作量**：3-5 天

### Phase 4: 分析方法论

- ACH 矩阵（Skill 中维护，Markdown 表格）
- 情景生成
- 完整的优先级打分（含假设区分力维度）

### Phase 5: 体验优化

- 进度简报格式
- 用户中途介入
- 缓存 & 去重 & 性能
- 扩展专用子 Agent（工商、裁判文书等）

---

## 附录 A：工具索引

| # | 工具 | Phase | 所属文件 |
|---|---|---|---|
| 1 | session_create | 1 | tools/sessions.py |
| 2 | session_open | 1 | tools/sessions.py |
| 3 | session_get | 1 | tools/sessions.py |
| 4 | node_create | 1 | tools/nodes.py |
| 5 | node_get | 1 | tools/nodes.py |
| 6 | node_update | 1 | tools/nodes.py |
| 7 | node_search | 1 | tools/nodes.py |
| 8 | node_list_gaps | 1 | tools/nodes.py |
| 9 | edge_create | 1 | tools/edges.py |
| 10 | edge_get | 3 | tools/edges.py |
| 11 | edge_update | 3 | tools/edges.py |
| 12 | edges_from_node | 1 | tools/edges.py |
| 13 | graph_path | 3 | tools/graph.py |
| 14 | graph_neighbors | 3 | tools/graph.py |
| 15 | graph_snapshot | 1 | tools/graph.py |
| 16 | identity_edge_create | 3 | tools/identity.py |
| 17 | identity_edge_update | 3 | tools/identity.py |
| 18 | node_merge | 3 | tools/identity.py |
| 19 | node_unmerge | 3 | tools/identity.py |
| 20 | report_summary | 3 | tools/reports.py |

## 附录 B：版本变更记录

### v1.0 → v2.0（2026-07-16 信息存储模型重构）

1. **body 字段**：合并 properties、aliases、notes 为一个 TEXT Markdown 字段。node.body 和 edge.body 为 LLM 原生工作介质
2. **删除字段**：anchor_level、seed、network_metrics、observed_at、first_observed、last_observed。种子标记由 session.seed_node_id 替代，网络位置由 graph_snapshot 实时计算
3. **type 自由化**：实体类型和边类型从预定义枚举改为自由字符串。MCP 层不做类型约束
4. **goal 自由化**：session.goal 从枚举改为自由文本
5. **矛盾检测从 MCP 移出**：check_contradictions 函数删除。交叉验证和矛盾判断由主 Agent（LLM）在入库阶段执行
6. **edge_create 简化**：MCP 只做机械去重（同 source+target+type+direction），不做自动 verification_status 升级
7. **node_search 简化**：移除 properties_filter 参数（body 为自由文本，不可机械过滤）
8. **graph_snapshot 简化**：移除 nodes_by_anchor（anchor_level 已删除），seed_nodes 改为 JOIN sessions
9. **子 Agent 合约简化**：properties → body。source_type 和 edge_type 为自由字符串

### v2.0 → v2.1（2026-07-16 工作区模型 + 开发前决策）

1. **工作区 + 文件夹隔离**：一案件一文件夹一 case.db。所有表去 session_id 列，所有工具去 session_id 参数。MCP Server 维护活跃连接
2. **session_create 重定义**：创建 "{timestamp}-{name}/" 目录 + case.db，切换活跃连接
3. **新增 session_open**：切换到已有案件的 case.db
4. **Phase 1 工具扩展**：从 9 个增加到 11 个（+ session_open + node_list_gaps）。node_list_gaps 从 Phase 3 提前
5. **活跃 DB 持久性**：无状态设计，MCP Server 重启后不自动恢复连接
6. **错误处理约定**：5 种错误码（not_found / invalid_reference / case_not_found / already_exists / no_active_db），通过返回值报告
7. **source_chain_entry 规格**：定义必填/选填字段和默认值
8. **测试策略**：Phase 1 手工测试，Phase 2+ 自动化
