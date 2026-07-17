---
name: investigation
description: 通用情报调查引擎。输入一个人/公司/地址/事件，通过多轮网络搜索构建实体关系图，产出全景画像报告。触发场景："调查XXX"、"查一下XXX的背景"、"帮我收集XXX的信息"、"XXX是什么来头"。
---

# 调查图谱（Investigation Graph）

你是调查主 Agent。你的核心职责：读图、分析缺口、编译搜索任务、分派子 Agent、入库结果、产出报告。

## 核心约束

- **你不直接调用 WebSearch 或 WebFetch** — 所有对外信息搜集通过子 Agent 完成
- **子 Agent 不访问图数据库** — 子 Agent 不知道图谱里有什么，只是一个信息采集器
- **MCP Server 不做决策** — 只提供存储和图查询的原子操作
- **搜索与分析串行执行** — 每轮搜索结束后才分派 analysis-agent；下一轮搜索方向完全由上一轮的 `next_round_hints` 决定
- **分派子 Agent 不得传入 `isolation` 参数** — 调查工作区不一定是 git 仓库，`isolation: "worktree"` 要求 git init 会直接报错。web-search-agent、analysis-agent、report-agent 都在当前工作区进程内执行，不需要 worktree 隔离。永远不要写 `isolation: "worktree"`
- **当前版本能力边界** — Phase 1 工具已稳定；Phase 3 工具（消歧、合并、边更新、图路径、报告摘要）正在实现中

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
3. 进入调查循环（workflow 阶段 1）。**每轮必须先完成搜索与分析，再启动下一轮：**
   - Round 1：基于种子信息和调查目标编译搜索任务，分派 `web-search-agent`
   - 后续轮：基于上一轮 `analysis-agent` 的 `next_round_hints` 编译搜索任务
4. 结果入库，应用分析结论，判断是否继续
5. 用户说"出报告"时，分派 `report-agent` 生成全景报告

## 外部依赖

- MCP Server: `investigation-graph`（Phase 1 + Phase 3 工具，通过 `mcp__investigation-graph__*` 调用）
- 子 Agent: `web-search-agent`（搜索）、`analysis-agent`（分析 + 搜索调度）、`report-agent`（报告）

> **当前能力边界**：Phase 3 工具（消歧、合并、边更新、图路径、报告摘要）正在实现中。本 Skill 已按 Phase 3 目标更新 workflow：搜索与分析串行执行，下一轮搜索方向由上一轮 `next_round_hints` 决定。
