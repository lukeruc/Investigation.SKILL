# 调查图谱（Investigation Graph）

通用情报分析引擎。以 Claude Code 为运行环境，通过多轮网络搜索构建实体关系图，产出全景画像报告。

## 适用场景

- **商业尽职调查**：企业背景调查、关联方穿透、实际控制人挖掘、供应链依赖分析。输入一家公司，自动梳理股权结构、高管任职网络、关联交易路径。
- **司法尽调**：涉诉记录检索、执行信息汇总、失信名单核验、裁判文书交叉比对。
- **个人背景调查**：商业关联图谱、任职履历验证、舆情与风险信号扫描。
- **地址与资产追踪**：地址反查关联企业与人员、资产线索串联。
- **事件线索扩展**：从单一线索（新闻、合同、判决）出发，逐跳扩展关联实体，构建完整事件拼图。

核心理念：**不替代分析师判断，而是让分析师从"手工搜索、逐页整理"中解放出来**，把精力集中在判断和决策上。

## 项目结构

```
├── src/
│   ├── mcp-server/               ← MCP Server（Python FastMCP）
│   │   ├── investigation_graph/  ← 核心包：db / models / queries / server / tools
│   │   ├── tests/                ← pytest 测试
│   │   ├── server.py             ← 兼容 shim，转发到 investigation_graph.server
│   │   └── pyproject.toml
│   └── skills/
│       └── investigation/        ← 主 Skill
│           ├── SKILL.md          ← 主 Agent 控制逻辑
│           ├── agents/           ← 子 Agent 定义
│           │   ├── analysis-agent.md
│           │   └── web-search-agent.md
│           └── references/       ← 工作流与 MCP 命令参考
│               ├── mcp-commands.md
│               └── workflow.md
├── doc/                          ← 设计文档
└── README.md
```

## 环境要求

- Python >= 3.12
- conda 环境 `inte`
- Claude Code

## 安装

```bash
# 1. 激活环境
conda activate inte

# 2. 安装 MCP Server（开发模式，改源码自动生效）
cd src/mcp-server
pip install -e ".[dev]"

# 3. 配置 Claude Code
```

### 配置 MCP Server

在**工作区项目根目录**创建 `.mcp.json`（项目级）或在 `~/.claude/settings.json` 中添加（全局）：

```json
{
  "mcpServers": {
    "investigation-graph": {
      "command": "/home/luke/miniconda3/envs/inte/bin/python",
      "args": ["-m", "investigation_graph"],
      "cwd": "${workspaceFolder}/src/mcp-server"
    }
  }
}
```

> 旧配置使用 `-m server` 仍可启动（`server.py` 为兼容 shim），但建议迁移到 `-m investigation_graph`。

### 配置 Skill

将 Skill 目录链接到 Claude Code 的全局 skills 路径：

```bash
ln -s /path/to/intelligence-graph/src/skills/investigation \
      ~/.claude/skills/investigation
```

### 验证安装

重启 Claude Code，确认 `investigation-graph` MCP 服务器已连接，然后输入"调查 XXX"测试 Skill 是否触发。

## 开发与测试

```bash
cd src/mcp-server
conda run -n inte pytest -q
```

## 当前能力边界

- **Phase 1（已完成）**：案件管理（session_create / open / get）、实体 CRUD、边创建与查询、全图快照，共 11 个工具。
- **Phase 3（进行中）**：消歧合并（identity / merge / unmerge）、边更新（edge_update / edge_get）、图路径（graph_path / graph_neighbors）、报告摘要（report_summary）已在 `doc/phase3-execution-plan.md` 中规划，部分已实现。

Workflow 已更新为完全串行：每轮搜索结束后进行 analysis，下一轮搜索方向由 `analysis-agent` 的 `next_round_hints` 决定。

## 使用

在任意目录打开 Claude Code，输入调查意图即可：

```
调查张三，person 类型，建筑行业
```

```
调查 A 公司，organization 类型，目标是了解股东结构和潜在关联交易
```

系统自动创建案件目录（`{timestamp}-调查张三/`），内含 `case.db`，多轮搜索后输出全景报告。
