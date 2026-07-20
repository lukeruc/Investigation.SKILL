---
name: investigation
description: "通用情报调查引擎。输入一个人/公司/地址/事件，通过多轮网络搜索构建实体关系图，产出全景画像报告。适用于：商业尽职调查（企业背景、股东结构、关联交易穿透）、司法尽调（涉诉记录、失信名单）、个人背景调查（任职履历、商业关联图谱）、地址反查、事件线索扩展。触发场景：'调查XXX'、'查一下XXX的背景'、'帮我收集XXX的信息'、'XXX是什么来头'、'这家公司的股东是谁'、'这个人在哪些公司任职'、'这个地址关联了哪些公司'。"
---

# 调查图谱（Investigation Graph）

本技能引导你通过多轮网络搜索构建实体关系图，最终产出全景画像报告。适用于商业尽职调查、司法尽调、个人背景调查、地址反查、事件线索扩展等场景。

## 工作方式

调查分为采集和报告两个阶段。采集阶段由多轮循环组成：每轮 web-search-agent 搜集信息并写入搜索结果 JSON 文件，analysis-agent 读取文件后产出分析结论和入库指令（`integration_instructions`），主 Agent 机械执行入库指令；搜索与分析串行执行，下一轮完全依赖上一轮的分析结论。报告阶段由 report-agent 对多轮分析结论做跨轮合成，产出全景报告。

**关键约束**：

- 主 Agent 只做调度（编译任务、分派子 Agent）和机械执行（按 `integration_instructions` 写库），不直接调用 WebSearch/WebFetch，不做信息解读
- 子 Agent 不访问图数据库；analysis-agent 通过输出入库指令间接写库
- 信息解读、消歧判断、矛盾检测、方向决策全部由 analysis-agent 完成
- 搜索与分析串行执行，不要跳过分析直接开始下一轮搜索
- **子 Agent 一律通过"读取定义 + `general-purpose` 分派"创建**：`agents/` 目录下的定义文件不是注册的 agent 类型，用 `Agent(subagent_type="web-search-agent")` 会失败。正确做法是先 `Read` 定义文件，再以 `subagent_type="general-purpose"` 分派，把定义全文放在 prompt 开头
- 分派子 Agent 时不得传入 `isolation` 参数——调查工作区不一定是 git 仓库，`isolation: "worktree"` 要求 git init 会直接报错

## 文件索引

本技能拆分为以下文件，按需读取：

| 文件（相对本 SKILL.md） | 何时读取 |
|---|---|
| `references/mcp-commands.md` | 每次调用 MCP 工具时参考，含全部工具签名和用法 |
| `references/workflow.md` | 执行调查流程时参考，含阶段 0/1-N/交付的完整步骤 |
| `agents/web-search-agent.md` | 分派搜索任务前 Read，把定义全文放入 general-purpose 子 Agent 的 prompt |
| `agents/analysis-agent.md` | 分派分析任务前 Read，用法同上 |
| `agents/report-agent.md` | 交付阶段分派报告任务前 Read，用法同上 |

## 快速启动

当用户表示要调查某人/某公司/某事物时：

1. 读 `references/workflow.md`，按阶段 0 收集种子信息
2. 读 `references/mcp-commands.md`，调用 MCP 工具创建会话和种子节点
3. 进入调查循环（workflow 阶段 1）。每轮必须先完成搜索与分析，再启动下一轮：
   - Round 1：基于种子信息和调查目标编译搜索任务。Read `agents/web-search-agent.md`，以 `general-purpose` 分派子 Agent（prompt = 定义全文 + 任务，指定结果写入 `<案件目录>/search-results/`）
   - 后续轮：基于上一轮 `analysis-agent` 的 `next_round_hints` 编译搜索任务
   - 每轮搜索完成后 Read `agents/analysis-agent.md`，以 `general-purpose` 分派分析任务，然后机械执行其 `integration_instructions`
4. 根据 `next_round_hints` 判断是否继续
5. 用户说"出报告"时，分派 `report-agent` 生成全景报告

## 外部依赖

- MCP Server: `investigation-graph`（通过 `mcp__investigation-graph__*` 调用）
- 子 Agent 定义文件（非注册类型，分派时 Read 后以 `general-purpose` 创建）: `web-search-agent`（搜索，结果写入 JSON 文件）、`analysis-agent`（分析 + 生成入库指令 + 搜索调度）、`report-agent`（报告）
