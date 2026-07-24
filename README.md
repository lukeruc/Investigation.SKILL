# 调查.SKILL

以 Claude Code 为运行环境的通用情报分析引擎。输入一个人/公司/地址/事件，通过多轮网络搜索构建实体关系图，产出全景画像报告。

## About

调查.SKILL 是一个 Claude Code Skill，将人类分析师的调查方法论编码为 AI 可执行的多轮工作流。它不是搜索引擎包装器——它在每一轮中自主决定"搜什么、怎么搜、搜到的东西意味着什么、下一步该查什么"，用节点和边构建可追溯的信息网络，最终输出全景画像报告。

## 适用场景

- **商业尽职调查**：企业背景调查、关联方穿透、实际控制人挖掘、供应链依赖分析。输入一家公司，自动梳理股权结构、高管任职网络、关联交易路径。
- **司法尽调**：涉诉记录检索、执行信息汇总、失信名单核验、裁判文书交叉比对。
- **个人背景调查**：商业关联图谱、任职履历验证、舆情与风险信号扫描。
- **地址与资产追踪**：地址反查关联企业与人员、资产线索串联。
- **事件线索扩展**：从单一线索（新闻、合同、判决）出发，逐跳扩展关联实体，构建完整事件拼图。

核心理念：**不替代分析师判断，而是让分析师从"手工搜索、逐页整理"中解放出来**，把精力集中在判断和决策上。

## 信息处理模型

引擎使用**节点（Node）和边（Edge）**作为信息的基本单位，每个案件的所有数据存储在一个独立的 SQLite 数据库中（`case.db`）。

### 节点（Node）

节点代表一个实体——一个人、一家公司、一个地址、一个事件。每个节点包含：

- `name` / `type`：实体名称和类型（person / organization / address / event 等，自由字符串）
- `body`：Markdown 格式的完整描述，是模型内部的工作介质——所有已知信息都以结构化 Markdown 存储在这里
- `exploration_status`：探索状态（unexplored → exploring → partial → explored / exhausted），控制哪些节点还需要进一步搜索
- `confidence`：置信度（high / medium / low）
- `anomaly_flags`：异常标记列表

节点是信息的**落脚点**。搜索过程中发现的每个实体最终落在一个节点上，后续分析通过节点关联的边来理解其在整体关系网络中的位置。

### 边（Edge）

边代表节点之间的关系。每条边连接两个节点，描述它们之间的关联：

- `source_id` / `target_id`：连接的两个节点
- `type`：关系类型（employment / investment / litigation / identity 等，自由字符串）
- `body`：关于该关系的 Markdown 描述
- `verification_status`：验证状态（unverified → verified / contradicted），每个关系可能被多个来源印证、也可能被矛盾证据标记
- `intensity`：关系强度（0.0-1.0）

### 来源链（Source Chain）

节点和边的每次创建都附带来源记录（`source_chain_entry`），包含来源名称、可靠性评级（A/B/C/D/E/X）和信息可信度（1/2/3/4/5/6）。这意味着**每条信息都可追溯**——报告中"A 是 B 的股东"可以追溯到到底是谁说的，以及那有多可信。

### 与知识图谱的区别

这不是传统的 RDF/OWL 知识图谱，也不是图数据库。SQLite + Markdown body 的选择是有意为之：

- **body 是 LLM 的原生工作介质**：结构化 Markdown 可以同时承载"工商登记号"这样的硬数据和"这个人商业布局的核心企业"这样的判断层信息
- **类型自由**：不需要预定义 schema，调查中会发现什么类型无法预知
- **每条信息有来源**：不是"数据"而是"从哪得知的信息"，矛盾也是信息的一部分

## 项目结构

```
├── src/
│   ├── mcp-server/               ← MCP Server（Python FastMCP）
│   │   ├── investigation_graph/  ← db / models / queries / server / tools
│   │   ├── tests/                ← pytest 测试
│   │   ├── server.py             ← 兼容 shim
│   │   └── pyproject.toml
│   └── skills/
│       └── investigation/        ← Skill（Claude Code Agent 编排层）
│           ├── SKILL.md          ← 入口：工作方式、核心约束、快速启动
│           ├── agents/           ← 子 Agent 定义（非注册类型，分派时 Read + general-purpose）
│           │   ├── web-search-agent.md
│           │   ├── analysis-agent.md
│           │   └── report-agent.md
│           └── references/       ← 工作流与 MCP 命令参考
│               ├── workflow.md
│               └── mcp-commands.md
├── doc/                          ← 设计文档与讨论记录
├── requirements.txt
└── LICENSE
```

## 环境要求

- Python >= 3.12
- Claude Code

## 安装

```bash
# 1. 创建并激活虚拟环境（conda / venv 均可）
python -m venv .venv && source .venv/bin/activate

# 2. 安装 MCP Server（开发模式，改源码自动生效）
cd src/mcp-server
pip install -e ".[dev]"
```

### 配置 MCP Server

在**工作区项目根目录**创建 `.mcp.json`（项目级）或在 `~/.claude/settings.json` 中添加（全局）：

```json
{
  "mcpServers": {
    "investigation-graph": {
      "command": "python",
      "args": ["-m", "investigation_graph"],
      "cwd": "${workspaceFolder}/src/mcp-server"
    }
  }
}
```

> 使用 conda 或虚拟环境时，将 `command` 替换为对应 Python 解释器的绝对路径。

### 配置 Skill

将 Skill 目录链接到工作区的 `.claude/skills/`（项目级）或 `~/.claude/skills/`（全局）：

```bash
ln -s /path/to/intelligence-graph/src/skills/investigation \
      <工作区>/.claude/skills/investigation
```

### 验证安装

重启 Claude Code，确认 `investigation-graph` MCP 服务器已连接，输入"调查 XXX"测试 Skill 是否触发。

## 开发与测试

```bash
cd src/mcp-server
pip install -e ".[dev]"
pytest -q
```

## 使用

在任意目录打开 Claude Code，输入调查意图即可：

```
调查张三，建筑行业
```

```
调查 A 公司，了解股东结构和潜在关联交易
```

系统自动创建案件目录（`{timestamp}-调查张三/`），经过多轮搜索与分析循环后输出全景画像报告。
