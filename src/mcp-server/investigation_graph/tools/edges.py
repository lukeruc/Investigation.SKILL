"""关系操作：edge_create, edge_get, edge_update, edges_from_node。"""

from __future__ import annotations

import json
import uuid

from mcp.server import FastMCP

from investigation_graph.db import NoActiveCaseError, db_connection, get_active_case, now_iso
from investigation_graph.models import EdgeCreateInput, EdgeGetInput, EdgeUpdateInput, EdgesFromNodeInput
from investigation_graph.queries import build_update, build_edges_where
from investigation_graph.tools.nodes import _insert_source_chain


def _edge_row_to_dict(row) -> dict:
    d = dict(row)
    d["anomaly_flags"] = json.loads(d.get("anomaly_flags", "[]"))
    d["contradicted_by"] = json.loads(d.get("contradicted_by", "[]"))
    return d


def _normalize_undirected(source_id: str, target_id: str) -> tuple[str, str]:
    """对无向边规范化端点顺序，保证 source_id <= target_id。"""
    if source_id <= target_id:
        return source_id, target_id
    return target_id, source_id


def _edge_get_by_id(db, edge_id: str) -> dict | None:
    """通过 edge_id 读取边，并附加 source_chains。"""
    row = db.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone()
    if row is None:
        return None
    edge = _edge_row_to_dict(row)
    sources = db.execute(
        "SELECT * FROM source_chains WHERE target_type='edge' AND target_id=?",
        (edge_id,),
    ).fetchall()
    edge["source_chains"] = [dict(s) for s in sources]
    return edge


def register_edge_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def edge_create(
        source_id: str,
        target_id: str,
        type: str,
        direction: str = "directed",
        body: str = "",
        intensity: float = 0.5,
        confidence: str = "medium",
        source_chain_entry: dict | None = None,
    ) -> dict:
        """创建新边。

        若同 source+target+type+direction 的边已存在，追加 source_chain 而非新建。
        对 undirected 边会规范化端点顺序并检查双向重复。
        """
        try:
            EdgeCreateInput(
                source_id=source_id,
                target_id=target_id,
                type=type,
                direction=direction,
                body=body,
                intensity=intensity,
                confidence=confidence,
                source_chain_entry=source_chain_entry,
            )
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            # 检查 source_id 和 target_id 是否存在
            src = db.execute("SELECT id FROM nodes WHERE id = ?", (source_id,)).fetchone()
            if src is None:
                return {"error": "invalid_reference", "detail": f"source_id {source_id} not found"}
            tgt = db.execute("SELECT id FROM nodes WHERE id = ?", (target_id,)).fetchone()
            if tgt is None:
                return {"error": "invalid_reference", "detail": f"target_id {target_id} not found"}

            # 规范化存储
            store_source, store_target = source_id, target_id
            if direction == "undirected":
                store_source, store_target = _normalize_undirected(source_id, target_id)

            # 检查重复
            existing = db.execute(
                "SELECT id FROM edges WHERE source_id=? AND target_id=? AND type=? AND direction=?",
                (store_source, store_target, type, direction),
            ).fetchone()

            if existing:
                edge_id = existing["id"]
                if source_chain_entry:
                    _insert_source_chain(db, source_chain_entry, "edge", edge_id)
                return {"edge_id": edge_id, "created": False, "deduplicated": True}

            # 创建新边
            edge_id = str(uuid.uuid4())
            now = now_iso()
            db.execute(
                """INSERT INTO edges (id, source_id, target_id, type, direction, body,
                   intensity, confidence, first_seen, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (edge_id, store_source, store_target, type, direction, body, intensity, confidence, now, now),
            )
            if source_chain_entry:
                _insert_source_chain(db, source_chain_entry, "edge", edge_id)

            return {"edge_id": edge_id, "created": True, "deduplicated": False}

    @mcp.tool()
    def edge_get(edge_id: str) -> dict:
        """获取边完整信息（body + source_chains + contradicted_by）。"""
        try:
            EdgeGetInput(edge_id=edge_id)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            edge = _edge_get_by_id(db, edge_id)
            if edge is None:
                return {"error": "not_found", "detail": f"edge {edge_id} not found"}
            return edge

    @mcp.tool()
    def edge_update(
        edge_id: str,
        body: str | None = None,
        confidence: str | None = None,
        verification_status: str | None = None,
        intensity: float | None = None,
        anomaly_flags: list[str] | None = None,
        contradicted_by: list[str] | None = None,
    ) -> dict:
        """增量更新边。body 非空时完全替换。"""
        try:
            EdgeUpdateInput(
                edge_id=edge_id,
                body=body,
                confidence=confidence,
                verification_status=verification_status,
                intensity=intensity,
                anomaly_flags=anomaly_flags,
                contradicted_by=contradicted_by,
            )
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            existing = _edge_get_by_id(db, edge_id)
            if existing is None:
                return {"error": "not_found", "detail": f"edge {edge_id} not found"}

            fields: dict[str, object] = {}
            if body is not None:
                fields["body"] = body
            if confidence is not None:
                fields["confidence"] = confidence
            if verification_status is not None:
                fields["verification_status"] = verification_status
            if intensity is not None:
                fields["intensity"] = intensity
            if anomaly_flags is not None:
                fields["anomaly_flags"] = json.dumps(anomaly_flags)
            if contradicted_by is not None:
                fields["contradicted_by"] = json.dumps(contradicted_by)

            if not fields:
                return existing

            sql, params = build_update("edges", fields, "id", edge_id)
            db.execute(sql, params)

            return _edge_get_by_id(db, edge_id)

    @mcp.tool()
    def edges_from_node(
        node_id: str,
        edge_type: str | None = None,
        direction: str | None = None,
    ) -> list[dict]:
        """获取某节点的所有关联边 + 邻居节点摘要。"""
        try:
            EdgesFromNodeInput(node_id=node_id, edge_type=edge_type, direction=direction)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return [{"error": "no_active_db", "detail": str(exc)}]
            return [{"error": "invalid_input", "detail": str(exc)}]

        where, params = build_edges_where(node_id, edge_type, direction)

        with db_connection(db_path) as db:
            rows = db.execute(
                f"""SELECT e.*,
                           src.name as source_name, src.type as source_type,
                           tgt.name as target_name, tgt.type as target_type
                    FROM edges e
                    JOIN nodes src ON e.source_id = src.id
                    JOIN nodes tgt ON e.target_id = tgt.id
                    WHERE {where}""",
                params,
            ).fetchall()
            return [_edge_row_to_dict(r) for r in rows]
