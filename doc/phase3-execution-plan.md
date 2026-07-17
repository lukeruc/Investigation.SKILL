# Phase 3 执行方案

本文档是调查图谱项目 Phase 3 的执行方案。Phase 3 的目标是实现完整多轮调查循环、消歧合并、异常检测与报告摘要能力。文档按工作项拆分，记录每个点的改动范围、实现要点和验证方式。

## 工作项 1：工作流范式改为完全串行

### 背景

当前 `workflow.md` 阶段 1-N 采用「搜索 ∥ 分析」并行：Round N 的搜索与 Round N-1 的分析同时启动。这导致 Round N 的搜索无法使用 Round N-1 分析产生的 `next_round_hints`，分析结论延迟一轮才能影响搜索方向。

### 决策

**改为完全串行：每轮必须先完成分析，再基于分析结论启动下一轮搜索。**

### 新流程

```
Round N:
  1. 读图（graph_snapshot + node_list_gaps）
  2. 识别搜索任务
     - 若 N == 1：仅基于种子信息 + 调查目标
     - 若 N > 1：基于上一轮 analysis-agent 的 next_round_hints
  3. 分派 web-search-agent（并行多个搜索任务）
  4. 等待所有搜索返回
  5. 结果入库（node_create / edge_create / node_update）
  6. 分派 analysis-agent（处理本轮所有变更）
  7. 等待分析返回，读 analysis/round-N.json
  8. 应用分析结论到图中
  9. 决定是否继续 / 出报告
```

### 关键设计

- 每轮只有一组搜索任务，来源单一：
  - 第一轮：由种子信息和调查目标推导。
  - 后续轮：由 `next_round_hints` 直接翻译而来。
- 去重和优先级排序放在分析 agent 内部完成：`next_round_hints` 已经按 priority 排序，主 Agent 不再重新打分。
- 若 analysis-agent 失败，本轮结束，向用户报告失败并询问是否继续；不再 fallback 到机械搜索，避免偏离分析驱动原则。
- 状态追踪仍保持：当前轮次、最新 analysis 文件路径、连续无进展轮数。

### 改动文件

- `src/skills/investigation/references/workflow.md`
  - 重写阶段 1-N 步骤，去掉「步骤 7：分派分析 Agent + 下一轮搜索（并行）」。
  - 新增「步骤 7：分派分析 Agent 并等待其结论」。
  - 新增「步骤 8：基于分析结论决定是否继续」。
- `src/skills/investigation/SKILL.md`
  - 更新「快速启动」中进入调查循环的描述。
  - 在「核心约束」中新增："每轮搜索方向由上一轮分析结论决定，搜索与分析串行执行。"
- `src/skills/investigation/agents/analysis-agent.md`
  - 扩展 `next_round_hints` schema，使其能直接翻译为下一轮搜索任务（见工作项 2）。

### 验证

- 触发一次完整调查，确认：
  1. 第一轮搜索结束后才启动 analysis-agent。
  2. 第二轮搜索任务明确引用 Round 1 的 `next_round_hints`。
  3. 无并行搜索与分析同时发生。

---

## 工作项 2：让 analysis-agent 成为搜索调度器

### 背景

完全串行后，analysis-agent 不仅要产出分析结论，还要决定下一轮搜什么。当前 `next_round_hints` 只是建议性文字，主 Agent 需要额外推理才能编译成搜索任务。

### 决策

**让 analysis-agent 输出可直接执行的搜索任务列表，主 Agent 只做翻译和分派。**

### 新输出字段

在 `analysis/round-N.json` 中，扩展 `next_round_hints` 为结构化任务规格：

```json
{
  "next_round_hints": [
    {
      "hint_id": "hint-1-1",
      "priority": 1,
      "what": "查 XXX 在 2020-2024 年间的工商变更记录，确认其是否从 YYY 退股",
      "why": "若退股属实，将削弱 XXX 与 YYY 的控制关系假设",
      "target_entity": {
        "name": "XXX",
        "type": "person",
        "node_id": "node-xxx 或 null"
      },
      "suggested_dimensions": [
        {
          "dimension": "工商变更与股东结构",
          "rationale": "确认持股比例变化",
          "suggested_skill": null
        }
      ],
      "expected_action": "search",
      "notes": "YYY 公司 node_id 为 node-yyy"
    }
  ]
}
```

### 主 Agent 处理

- 读取 `next_round_hints` 后，对每个 hint：
  1. 若 `target_entity.node_id` 为 null，先用 `node_search` 查找；仍未命中则作为新实体搜索。
  2. 将 `suggested_dimensions` 和 `notes` 组合成 `web-search-agent` 输入合约。
  3. 直接分派 `web-search-agent`。
- 不再额外做目标匹配打分；优先级直接采用 hint 中的 `priority`。
- 下一轮任务数量上限由 analysis-agent 自行控制（建议每轮最多 5 个）。

### 改动文件

- `src/skills/investigation/agents/analysis-agent.md`
  - 更新 `next_round_hints` schema。
  - 新增说明：每个 hint 必须能直接翻译成一个 web-search-agent prompt；禁止模糊描述。
- `src/skills/investigation/references/workflow.md`
  - 在步骤 2 中说明搜索任务来源为 `analysis/round-(N-1).json` 的 `next_round_hints`。
  - 在步骤 3 中说明主 Agent 如何将 hint 翻译为搜索 prompt。

### 验证

- 检查 analysis-agent 输出中 `next_round_hints` 是否都包含 `target_entity` 和 `suggested_dimensions`。
- 主 Agent 能无歧义地将其分派为 web-search-agent 任务。

---

## 工作项 3：消歧与合并

### 背景

当前 Phase 1 中，同名/疑似同一实体的消歧完全由主 Agent 在入库阶段手动处理（通过 `node_search` + body 备注）。Phase 3 需要在图中显式表达同一性假设，并支持节点合并与拆分。

### 决策

**实现 identity 边、证据累积、合并/拆分四个 MCP 工具，并让主 Agent 在入库阶段自动创建 identity 边。**

### 数据模型

已有 schema 支持：

- `edges` 表：增加 `type="identity"` 的边，表示两个节点可能为同一实体。
- `merge_history` 表：记录合并事件。
- `identity_evidence` 表：记录支持或反对同一性的证据信号。

### 新增 / 完善 MCP 工具

| 工具 | 行为 |
|---|---|
| `identity_edge_create(node_a_id, node_b_id, match_basis)` | 创建 type="identity" 的边，verification_status="unverified"，intensity=0.3。 |
| `identity_edge_update(identity_edge_id, evidence_entry, intensity, verification_status)` | 更新 identity 边；若提供 evidence_entry，写入 identity_evidence。 |
| `node_merge(node_ids)` | 合并多个节点为一个。原节点标记为 merged，关系迁移到新节点，写入 merge_history。 |
| `node_unmerge(node_id, merge_event_index)` | 根据 merge_history 恢复原始节点。 |

### identity 边与 evidence 规则

- 主 Agent 在 `node_create` 前调用 `node_search(name_pattern=..., type=...)`。
- 发现同名或高相似候选时，创建 `identity_edge_create`，将候选与现有节点连接，而不是直接合并。
- analysis-agent 负责评估 identity 边的证据：
  - 支持信号：同名、同地址、同联系方式、同一时间出现、关联网络重叠。
  - 反对信号：明显矛盾属性（年龄/性别/成立时间冲突）。
- 当 identity 边 verification_status 变为 "confirmed" 时，主 Agent 调用 `node_merge`。

### 改动文件

- `src/mcp-server/investigation_graph/tools/identity.py`
  - 替换当前 `not_implemented` 占位实现。
- `src/mcp-server/investigation_graph/models.py`
  - 增加 identity 工具输入模型。
- `src/mcp-server/investigation_graph/db.py`
  - 确认 schema 已覆盖 merge_history / identity_evidence / identity 边需求。
- `src/skills/investigation/references/workflow.md`
  - 在「结果入库」中增加 identity 边创建流程。
- `src/skills/investigation/agents/analysis-agent.md`
  - 增加对 identity 边证据评估的说明。
- `src/skills/investigation/references/mcp-commands.md`
  - 补充 identity 工具签名。

### 验证

- 单元测试：
  - `identity_edge_create` 后，两个节点间存在 type="identity" 边。
  - `identity_edge_update` 添加 evidence 后，`identity_evidence` 表有记录。
  - `node_merge` 后，原节点关系正确迁移到新节点。
  - `node_unmerge` 能恢复合并前状态。

---

## 工作项 4：边更新与图路径

### 背景

当前 `edge_create` 只负责去重创建；`edge_update` 不存在，导致 verification_status、contradicted_by 等字段无法修改，矛盾标记只能通过 `node_update`  workaround。

### 决策

**实现 `edge_update` / `edge_get`，以及 `graph_path` / `graph_neighbors`。**

### 新增 / 完善 MCP 工具

| 工具 | 行为 |
|---|---|
| `edge_get(edge_id)` | 返回边完整信息 + source_chains + contradicted_by。 |
| `edge_update(edge_id, body, confidence, verification_status, intensity, anomaly_flags, contradicted_by)` | 增量更新边字段。 |
| `graph_path(source_node_id, target_node_id, max_depth=5)` | BFS 最短路径，返回节点和边序列。 |
| `graph_neighbors(node_id, depth=1)` | 返回指定深度邻居 + 路径边。 |

### 主 Agent 流程变化

- 入库阶段的矛盾检测：发现冲突后调用 `edge_update(verification_status="contradicted", contradicted_by=[...])`。
- 发现独立印证后调用 `edge_update(verification_status="verified")`。
- 不再把 edge 相关标记写入 node body。

### 改动文件

- `src/mcp-server/investigation_graph/tools/edges.py`
  - 新增 `edge_get` 和 `edge_update`。
- `src/mcp-server/investigation_graph/tools/graph.py`
  - 替换 `graph_path` / `graph_neighbors` 的占位实现。
- `src/mcp-server/investigation_graph/models.py`
  - 增加对应输入模型。
- `src/mcp-server/investigation_graph/queries.py`
  - 如需要，增加路径/邻居查询辅助函数。
- `src/skills/investigation/references/workflow.md`
  - 更新「矛盾检测」和「验证状态升级」步骤，使用 `edge_update`。
- `src/skills/investigation/references/mcp-commands.md`
  - 补充 edge 和 graph 工具签名。

### 验证

- 单元测试：
  - `edge_update` 更新 verification_status 后读取正确。
  - `graph_path` 在直连两节点间返回单一边路径。
  - `graph_neighbors` depth=2 正确返回二阶邻居。

---

## 工作项 5：报告摘要

### 背景

当前 `report_summary` 为占位实现，report-agent 依赖主 Agent 手动打包所有分析文件。Phase 3 需要提供以节点为中心的结构化摘要能力。

### 决策

**实现 `report_summary(node_id)`，聚合节点为中心的证据、关系、缺口和异常。**

### 输出格式

```json
{
  "node": { ... },
  "edges": [ ... ],
  "source_summary": {
    "A1_count": 0,
    "B2_count": 0,
    ...
  },
  "anomaly_flags": [ ... ],
  "gaps": [ ... ]
}
```

- `source_summary` 按 `(source_reliability, info_credibility)` 组合统计来源数量。
- `gaps` 列出与该节点相关、仍缺失的关键维度。

### 主 Agent 使用方式

- 交付阶段：对种子节点和度中心性 top-5 节点调用 `report_summary(node_id)`。
- 将结果与 `analysis/round-*.json`、证据日志一起打包给 report-agent。

### 改动文件

- `src/mcp-server/investigation_graph/tools/reports.py`
  - 替换 `report_summary` 占位实现。
- `src/mcp-server/investigation_graph/models.py`
  - 增加 `ReportSummaryInput` 模型。
- `src/skills/investigation/references/workflow.md`
  - 在交付阶段加入 `report_summary` 调用。
- `src/skills/investigation/agents/report-agent.md`
  - 说明主 Agent 会传入 `report_summary` 结果。
- `src/skills/investigation/references/mcp-commands.md`
  - 补充 `report_summary` 签名。

### 验证

- 单元测试：
  - 对存在 source_chain 的节点调用 `report_summary`，`source_summary` 统计正确。
  - 异常节点返回的 `anomaly_flags` 与节点一致。

---

## 工作项 6：异常检测规则落地

### 背景

设计文档 `doc/design-doc.md` 提到 Phase 3 需要异常检测规则（S1-S4 机械规则 + C1-C2/T1-T2 LLM 判断规则），但尚未在 analysis-agent 中明确化。

### 决策

**在 analysis-agent 中定义异常检测清单，输出 `anomaly_signals` 时使用统一分类。**

### 规则分类

**机械规则（主 Agent 或 MCP 侧可预检）**：

| 编号 | 规则 | 触发 |
|---|---|---|
| S1 | 结构异常 | 节点度数为 0 但非孤立 intended |
| S2 | 时间聚集 | 多个关联节点在同一短时间段内创建/变更 |
| S3 | 循环引用 | 图中存在环但关系类型暗示无环 |
| S4 | 单点来源 | 关键结论仅依赖单一来源 |

**LLM 判断规则（由 analysis-agent 执行）**：

| 编号 | 规则 | 触发 |
|---|---|---|
| C1 | 属性矛盾 | 同一实体的不同来源属性冲突 |
| C2 | 关系矛盾 | 两条边在逻辑上不能同时成立 |
| T1 | 时机异常 | 关键事件发生在不合常理的时间点 |
| T2 | 模式异常 | 关联结构与已知典型模式明显偏离 |

### analysis-agent 输出规范

`anomaly_signals` 每项增加 `rule_code`：

```json
{
  "target_type": "node | edge",
  "target_id": "xxx",
  "rule_code": "S1 | S2 | S3 | S4 | C1 | C2 | T1 | T2",
  "signal": "suspicious_timing | structural_anomaly | information_gap | pattern",
  "description": "..."
}
```

### 改动文件

- `src/skills/investigation/agents/analysis-agent.md`
  - 新增「异常检测规则」章节，列出 S1-S4、C1-C2、T1-T2 的定义和判断标准。
  - 更新 `anomaly_signals` schema，增加 `rule_code`。
- `src/skills/investigation/references/workflow.md`
  - 在步骤 8 中说明如何根据 `rule_code` 决定后续动作（如 S4 触发验证搜索、C1 触发 identity 边审查）。

### 验证

- 跑一轮调查，检查 `analysis/round-*.json` 中的 `anomaly_signals` 是否包含 `rule_code`。
- 人为构造矛盾数据，确认 analysis-agent 能输出 C1/C2 类型异常。

---

## 工作项 7：连续无进展检测

### 背景

当前 workflow 提到「连续 2 轮无明显进展 → 告知用户，建议暂停或调整方向」，但没有定义什么叫「明显进展」。

### 决策

**明确进展判定标准，由主 Agent 在每轮结束后计算。**

### 判定标准

以下任一条件视为有进展：

1. 本轮新增节点数 > 0 或新增边数 > 0。
2. 本轮 `analysis-agent` 的 `key_findings` 非空且至少有一条 rank <= 2。
3. 本轮有节点的 `exploration_status` 从 `partial` / `exploring` 变为 `explored`。
4. 本轮 `quality_flags` 或 `anomaly_signals` 非空（发现新问题也视为进展，因为它改变了调查状态）。

否则视为无进展。

### 处理逻辑

- 无进展时递增 `consecutive_no_progress`。
- `consecutive_no_progress >= 2` 时，向用户汇报并建议：
  - 调整调查目标
  - 扩大 depth_limit
  - 出报告
  - 暂停

### 改动文件

- `src/skills/investigation/references/workflow.md`
  - 在「步骤 9：判断下一步」中明确进展判定标准。
- `src/skills/investigation/SKILL.md`
  - 在状态追踪中保留 `consecutive_no_progress`。

### 验证

- 构造一轮无新增节点的调查，确认 `consecutive_no_progress` 正确递增。
- 连续两轮无进展后，主 Agent 向用户报告并询问下一步。

---

## 工作项 8：MCP Server 测试覆盖

### 背景

Phase 1 以手工测试为主，Phase 3 需要稳定的自动化测试覆盖新增工具。

### 决策

**为每个 Phase 3 MCP 工具新增 pytest 测试，并保持现有测试通过。**

### 测试文件规划

| 文件 | 覆盖内容 |
|---|---|
| `tests/test_identity.py` | identity_edge_create / update / node_merge / unmerge |
| `tests/test_edges_advanced.py` | edge_get / edge_update |
| `tests/test_graph_advanced.py` | graph_path / graph_neighbors |
| `tests/test_reports.py` | report_summary |

### 测试规范

- 每个测试使用 `fresh_case` 或 `fresh_case_with_session` fixture。
- 工具测试不直接调用 SQL，通过工具函数验证。
- 对于路径类工具，构造小型图（3-5 个节点，3-5 条边）后验证路径结果。

### 改动文件

- `src/mcp-server/tests/test_identity.py`（新建）
- `src/mcp-server/tests/test_edges_advanced.py`（新建）
- `src/mcp-server/tests/test_graph_advanced.py`（新建）
- `src/mcp-server/tests/test_reports.py`（新建）

### 验证

- 运行 `pytest -q`，所有测试通过。

---

## 工作项 9：文档同步

### 背景

Phase 3 改动涉及多个 Markdown 文件，需要保持文档一致。

### 同步清单

| 文件 | 需要更新的内容 |
|---|---|
| `README.md` | 更新「当前能力边界」，移除 Phase 3 未实现的说明。 |
| `CLAUDE.md` | 更新 capability boundaries 和 architecture 描述。 |
| `doc/design-doc.md` | 将 Phase 3 工具状态从「未实现」改为「已实现」，更新 workflow 描述。 |
| `src/skills/investigation/references/mcp-commands.md` | 补充 Phase 3 工具签名和错误码。 |

### 验证

- 文档中无自相矛盾之处。
- 工具签名与代码一致。

---

## 总体实施顺序

建议按以下顺序执行，减少相互阻塞：

1. 工作项 1 + 工作项 2：先确定串行 workflow 和 analysis-agent 输出格式。
2. 工作项 4：实现 edge_update / graph_path，让主 Agent 能正确标记矛盾和验证状态。
3. 工作项 3：实现 identity 和 node_merge，支持消歧。
4. 工作项 5：实现 report_summary。
5. 工作项 6：在 analysis-agent 中落地异常规则。
6. 工作项 7：明确无进展检测。
7. 工作项 8：补齐测试。
8. 工作项 9：同步文档。

---

## 附录：Phase 3 工具实现清单

| 工具 | Phase | 所属文件 | 当前状态 |
|---|---|---|---|
| `edge_update` | 3 | `tools/edges.py` | 未实现 |
| `edge_get` | 3 | `tools/edges.py` | 未实现 |
| `graph_path` | 3 | `tools/graph.py` | 未实现 |
| `graph_neighbors` | 3 | `tools/graph.py` | 未实现 |
| `identity_edge_create` | 3 | `tools/identity.py` | 未实现 |
| `identity_edge_update` | 3 | `tools/identity.py` | 未实现 |
| `node_merge` | 3 | `tools/identity.py` | 未实现 |
| `node_unmerge` | 3 | `tools/identity.py` | 未实现 |
| `report_summary` | 3 | `tools/reports.py` | 未实现 |
