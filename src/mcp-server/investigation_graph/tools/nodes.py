"""实体操作：node_create, node_get, node_update, node_search, node_list_gaps。"""

from __future__ import annotations

import json
import uuid

from mcp.server import FastMCP

from investigation_graph.db import NoActiveCaseError, db_connection, get_active_case, now_iso
from investigation_graph.models import (
    NodeCreateInput,
    NodeGetInput,
    NodeListGapsInput,
    NodeSearchInput,
    NodeUpdateInput,
)
from investigation_graph.queries import build_select_nodes_where


def _insert_source_chain(
    db,
    entry: dict,
    target_type: str,
    target_id: str,
) -> None:
    """写入 source_chain_entry 到 source_chains 表。补全默认值。"""
    sc_id = str(uuid.uuid4())
    now = now_iso()
    db.execute(
        """INSERT INTO source_chains
           (id, target_type, target_id, source_name, source_type,
            source_reliability, info_credibility, discovery_time,
            discovery_agent, discovery_context, raw_data, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sc_id,
            target_type,
            target_id,
            entry["source_name"],
            entry.get("source_type", "web_search"),
            entry.get("source_reliability", "X"),
            entry.get("info_credibility", "6"),
            entry.get("discovery_time", now),
            entry.get("discovery_agent"),
            entry.get("discovery_context"),
            entry.get("raw_data", "{}"),
            now,
        ),
    )


def _node_row_to_dict(row) -> dict:
    d = dict(row)
    d["anomaly_flags"] = json.loads(d.get("anomaly_flags", "[]"))
    return d


def _edge_row_to_dict(row) -> dict:
    d = dict(row)
    d["anomaly_flags"] = json.loads(d.get("anomaly_flags", "[]"))
    d["contradicted_by"] = json.loads(d.get("contradicted_by", "[]"))
    return d


def register_node_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def node_create(
        type: str,
        name: str,
        body: str = "",
        confidence: str = "medium",
        source_chain_entry: dict | None = None,
    ) -> dict:
        """创建新节点。"""
        try:
            NodeCreateInput(
                type=type,
                name=name,
                body=body,
                confidence=confidence,
                source_chain_entry=source_chain_entry,
            )
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        node_id = str(uuid.uuid4())
        now = now_iso()
        with db_connection(db_path) as db:
            db.execute(
                """INSERT INTO nodes (id, type, name, body, confidence, first_seen, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (node_id, type, name, body, confidence, now, now),
            )
            if source_chain_entry:
                _insert_source_chain(db, source_chain_entry, "node", node_id)

        return {
            "node_id": node_id,
            "type": type,
            "name": name,
            "body": body,
            "confidence": confidence,
            "exploration_status": "unexplored",
            "first_seen": now,
            "last_updated": now,
        }

    @mcp.tool()
    def node_get(node_id: str) -> dict:
        """获取节点完整信息（body + 关联边 + 来源链）。"""
        try:
            NodeGetInput(node_id=node_id)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            row = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if row is None:
                return {"error": "not_found", "detail": f"node {node_id} not found"}

            node = _node_row_to_dict(row)

            edges = db.execute(
                """SELECT e.*,
                          CASE WHEN e.source_id = ? THEN tgt.name ELSE src.name END as neighbor_name,
                          CASE WHEN e.source_id = ? THEN tgt.type ELSE src.type END as neighbor_type,
                          CASE WHEN e.source_id = ? THEN 'outgoing' ELSE 'incoming' END as direction_relative
                   FROM edges e
                   JOIN nodes src ON e.source_id = src.id
                   JOIN nodes tgt ON e.target_id = tgt.id
                   WHERE e.source_id = ? OR e.target_id = ?""",
                (node_id, node_id, node_id, node_id, node_id),
            ).fetchall()
            node["edges"] = [_edge_row_to_dict(e) for e in edges]

            sources = db.execute(
                "SELECT * FROM source_chains WHERE target_type='node' AND target_id=?",
                (node_id,),
            ).fetchall()
            node["source_chains"] = [dict(s) for s in sources]

            return node

    @mcp.tool()
    def node_update(
        node_id: str,
        body: str | None = None,
        confidence: str | None = None,
        exploration_status: str | None = None,
        anomaly_flags: list[str] | None = None,
    ) -> dict:
        """增量更新节点。body 非空时完全替换。"""
        try:
            NodeUpdateInput(
                node_id=node_id,
                body=body,
                confidence=confidence,
                exploration_status=exploration_status,
                anomaly_flags=anomaly_flags,
            )
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            existing = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if existing is None:
                return {"error": "not_found", "detail": f"node {node_id} not found"}

            now = now_iso()
            fields: dict[str, object] = {}
            if body is not None:
                fields["body"] = body
            if confidence is not None:
                fields["confidence"] = confidence
            if exploration_status is not None:
                fields["exploration_status"] = exploration_status
            if anomaly_flags is not None:
                fields["anomaly_flags"] = json.dumps(anomaly_flags)

            if not fields:
                return _node_row_to_dict(existing)

            from investigation_graph.queries import build_update

            sql, params = build_update("nodes", fields, "id", node_id)
            db.execute(sql, params)

            row = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return _node_row_to_dict(row)

    @mcp.tool()
    def node_search(
        type: str | None = None,
        name_pattern: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """搜索节点。name_pattern 做 LIKE '%pattern%' 匹配。"""
        try:
            NodeSearchInput(type=type, name_pattern=name_pattern, limit=limit)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return [{"error": "no_active_db", "detail": str(exc)}]
            return [{"error": "invalid_input", "detail": str(exc)}]

        where, params = build_select_nodes_where(type_value=type, name_pattern=name_pattern)
        params.append(limit)

        with db_connection(db_path) as db:
            rows = db.execute(
                f"SELECT id, name, type, exploration_status, confidence, first_seen, last_updated "
                f"FROM nodes WHERE {where} LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    @mcp.tool()
    def node_list_gaps(type: str | None = None) -> list[dict]:
        """列出有探索缺口的节点。"""
        try:
            NodeListGapsInput(type=type)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return [{"error": "no_active_db", "detail": str(exc)}]
            return [{"error": "invalid_input", "detail": str(exc)}]

        gap_statuses = ["unexplored", "exploring", "partial", "skipped"]
        where, params = build_select_nodes_where(
            type_value=type, exploration_status_in=gap_statuses
        )

        with db_connection(db_path) as db:
            rows = db.execute(
                f"SELECT id, name, type, exploration_status, confidence, first_seen, last_updated "
                f"FROM nodes WHERE {where}",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
