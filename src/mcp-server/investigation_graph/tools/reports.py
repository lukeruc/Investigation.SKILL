"""报告工具：report_summary。

以指定节点为中心，聚合关系、来源、异常和缺口，生成结构化摘要。
"""

from __future__ import annotations

import json
from collections import Counter

from mcp.server import FastMCP

from investigation_graph.db import NoActiveCaseError, db_connection, get_active_case
from investigation_graph.models import ReportSummaryInput


def _node_row_to_dict(row) -> dict:
    d = dict(row)
    d["anomaly_flags"] = json.loads(d.get("anomaly_flags", "[]"))
    return d


def _edge_row_to_dict(row) -> dict:
    d = dict(row)
    d["anomaly_flags"] = json.loads(d.get("anomaly_flags", "[]"))
    d["contradicted_by"] = json.loads(d.get("contradicted_by", "[]"))
    return d


def register_report_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def report_summary(node_id: str) -> dict:
        """返回节点为中心的结构化摘要。"""
        try:
            ReportSummaryInput(node_id=node_id)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            node_row = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if node_row is None:
                return {"error": "not_found", "detail": f"node {node_id} not found"}

            node = _node_row_to_dict(node_row)

            edges = db.execute(
                """SELECT e.*,
                          src.name as source_name, src.type as source_type,
                          tgt.name as target_name, tgt.type as target_type
                   FROM edges e
                   JOIN nodes src ON e.source_id = src.id
                   JOIN nodes tgt ON e.target_id = tgt.id
                   WHERE e.source_id = ? OR e.target_id = ?""",
                (node_id, node_id),
            ).fetchall()
            edge_list = [_edge_row_to_dict(e) for e in edges]

            # source chains for this node
            node_sources = db.execute(
                "SELECT * FROM source_chains WHERE target_type='node' AND target_id=?",
                (node_id,),
            ).fetchall()

            # source chains for connected edges
            edge_ids = [e["id"] for e in edge_list]
            edge_sources: list[dict] = []
            if edge_ids:
                placeholders = ", ".join("?" for _ in edge_ids)
                edge_sources = [
                    dict(r)
                    for r in db.execute(
                        f"SELECT * FROM source_chains WHERE target_type='edge' AND target_id IN ({placeholders})",
                        edge_ids,
                    ).fetchall()
                ]

            all_sources = [dict(r) for r in node_sources] + edge_sources
            source_counter = Counter(
                (s.get("source_reliability", "X"), s.get("info_credibility", "6"))
                for s in all_sources
            )
            source_summary = {
                f"{rel}_{cred}": count for (rel, cred), count in sorted(source_counter.items())
            }

            # verification status summary
            verification_counter = Counter(e["verification_status"] for e in edge_list)

            # gaps: if node itself is not explored, list its own missing dimensions as a gap
            gaps = []
            if node["exploration_status"] in {"unexplored", "partial", "skipped"}:
                gaps.append(
                    {
                        "node_id": node_id,
                        "name": node["name"],
                        "missing": f"node exploration_status is {node['exploration_status']}",
                    }
                )

            # connected unexplored/partial nodes also count as gaps
            for edge in edge_list:
                neighbor_id = edge["target_id"] if edge["source_id"] == node_id else edge["source_id"]
                neighbor_row = db.execute(
                    "SELECT name, exploration_status FROM nodes WHERE id = ?", (neighbor_id,)
                ).fetchone()
                if neighbor_row and neighbor_row["exploration_status"] in {"unexplored", "partial", "skipped"}:
                    gaps.append(
                        {
                            "node_id": neighbor_id,
                            "name": neighbor_row["name"],
                            "missing": f"neighbor exploration_status is {neighbor_row['exploration_status']}",
                        }
                    )

            # deduplicate gaps
            seen = set()
            unique_gaps = []
            for gap in gaps:
                if gap["node_id"] not in seen:
                    seen.add(gap["node_id"])
                    unique_gaps.append(gap)

            return {
                "node": node,
                "edges": edge_list,
                "source_summary": source_summary,
                "verification_summary": dict(verification_counter),
                "anomaly_flags": node["anomaly_flags"],
                "gaps": unique_gaps,
            }

    @mcp.tool()
    def graph_path(source_node_id: str, target_node_id: str, max_depth: int = 5) -> dict:
        """（已迁移到 tools/graph.py）保留占位防止注册冲突。"""
        return {"error": "not_implemented", "detail": "graph_path is implemented in tools/graph"}

    @mcp.tool()
    def graph_neighbors(node_id: str, depth: int = 1) -> dict:
        """（已迁移到 tools/graph.py）保留占位防止注册冲突。"""
        return {"error": "not_implemented", "detail": "graph_neighbors is implemented in tools/graph"}
