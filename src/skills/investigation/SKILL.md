---
name: investigation
description: "通用情报调查引擎。输入一个人/公司/地址/事件，通过多轮网络搜索构建实体关系图，产出全景画像报告。适用于：商业尽职调查（企业背景、股东结构、关联交易穿透）、司法尽调（涉诉记录、失信名单）、个人背景调查（任职履历、商业关联图谱）、地址反查、事件线索扩展。触发场景：'调查XXX'、'查一下XXX的背景'、'帮我收集XXX的信息'、'XXX是什么来头'、'这家公司的股东是谁'、'这个人在哪些公司任职'、'这个地址关联了哪些公司'。"
---

# 调查图谱（Investigation Graph）

本技能引导你通过多轮网络搜索构建实体关系图，最终产出全景画像报告。适用于商业尽职调查、司法尽调、个人背景调查、地址反查、事件线索扩展等场景。

## 工作方式

调查分为采集和报告两个阶段。采集阶段由多轮循环组成：每轮通过 web-search-agent 搜集信息，入库后由 analysis-agent 分析并产出下一轮搜索方向；搜索与分析串行执行，下一轮完全依赖上一轮的分析结论。报告阶段由 report-agent 对多轮分析结论做跨轮合成，产出全景报告。

**关键约束**：

- 主 Agent 不直接调用 WebSearch/WebFetch，所有信息搜集通过子 Agent 完成
- 子 Agent 不访问图数据库，只负责信息采集
- MCP Server 只做存储和查询，矛盾检测、消歧、方向判断由主 Agent 完成
- 搜索与分析串行执行，不要跳过分析直接开始下一轮搜索
- 分派子 Agent 时不得传入 `isolation` 参数——调查工作区不一定是 git 仓库，`isolation: "worktree"` 要求 git init 会直接报错

## 文件索引

本技能拆分为以下文件，按需读取：

| 文件（相对本 SKILL.md） | 何时读取 |
|---|---|
| `references/mcp-commands.md` | 每次调用 MCP 工具时参考，含全部工具签名和用法 |
| `references/workflow.md` | 执行调查流程时参考，含阶段 0/1-N/交付的完整步骤 |
| `agents/web-search-agent.md` | 子 Agent 定义，分派搜索任务时使用 |
| `agents/analysis-agent.md` | 子 Agent 定义，分派分析任务时使用 |
| `agents/report-agent.md` | 子 Agent 定义，交付阶段生成全景报告时使用 |

## 快速启动

当用户表示要调查某人/某公司/某事物时：

1. 读 `references/workflow.md`，按阶段 0 收集种子信息
2. 读 `references/mcp-commands.md`，调用 MCP 工具创建会话和种子节点
3. 进入调查循环（workflow 阶段 1）。每轮必须先完成搜索与分析，再启动下一轮：
   - Round 1：基于种子信息和调查目标编译搜索任务，分派 `web-search-agent`
   - 后续轮：基于上一轮 `analysis-agent` 的 `next_round_hints` 编译搜索任务
4. 结果入库，应用分析结论，判断是否继续
5. 用户说"出报告"时，分派 `report-agent` 生成全景报告

## 外部依赖

- MCP Server: `investigation-graph`（通过 `mcp__investigation-graph__*` 调用）
- 子 Agent: `web-search-agent`（搜索）、`analysis-agent`（分析 + 搜索调度）、`report-agent`（报告）
