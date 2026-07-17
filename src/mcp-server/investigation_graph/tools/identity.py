"""消歧工具：identity_edge_create, identity_edge_update, node_merge, node_unmerge。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from mcp.server import FastMCP

from investigation_graph.db import NoActiveCaseError, db_connection, get_active_case, now_iso
from investigation_graph.models import (
    IdentityEdgeCreateInput,
    IdentityEdgeUpdateInput,
    NodeMergeInput,
    NodeUnmergeInput,
)
from investigation_graph.queries import build_update
from investigation_graph.tools.nodes import _insert_source_chain


def _edge_row_to_dict(row) -> dict:
    d = dict(row)
    d["anomaly_flags"] = json.loads(d.get("anomaly_flags", "[]"))
    d["contradicted_by"] = json.loads(d.get("contradicted_by", "[]"))
    return d


def _get_edge(db, edge_id: str) -> dict | None:
    row = db.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone()
    if row is None:
        return None
    return _edge_row_to_dict(row)


def _get_node(db, node_id: str) -> dict | None:
    row = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["anomaly_flags"] = json.loads(d.get("anomaly_flags", "[]"))
    return d


def register_identity_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def identity_edge_create(
        node_a_id: str,
        node_b_id: str,
        match_basis: str = "name_match",
    ) -> dict:
        """创建 type='identity' 的边，表示两个节点可能为同一实体。"""
        try:
            IdentityEdgeCreateInput(node_a_id=node_a_id, node_b_id=node_b_id, match_basis=match_basis)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            if not _get_node(db, node_a_id):
                return {"error": "not_found", "detail": f"node {node_a_id} not found"}
            if not _get_node(db, node_b_id):
                return {"error": "not_found", "detail": f"node {node_b_id} not found"}

            # 对 identity 边规范化端点顺序，避免重复
            source_id, target_id = (node_a_id, node_b_id) if node_a_id <= node_b_id else (node_b_id, node_a_id)

            existing = db.execute(
                "SELECT id FROM edges WHERE source_id=? AND target_id=? AND type='identity'",
                (source_id, target_id),
            ).fetchone()
            if existing:
                return {"edge_id": existing["id"], "created": False}

            edge_id = str(uuid.uuid4())
            now = now_iso()
            db.execute(
                """INSERT INTO edges (id, source_id, target_id, type, direction, body,
                   intensity, confidence, verification_status, first_seen, last_updated)
                   VALUES (?, ?, ?, 'identity', 'undirected', ?, 0.3, 'medium', 'unverified', ?, ?)""",
                (edge_id, source_id, target_id, f"match_basis: {match_basis}", now, now),
            )

            return {"edge_id": edge_id, "created": True}

    @mcp.tool()
    def identity_edge_update(
        identity_edge_id: str,
        evidence_entry: dict | None = None,
        intensity: float | None = None,
        verification_status: str | None = None,
    ) -> dict:
        """更新 identity 边；若提供 evidence_entry，写入 identity_evidence 表。"""
        try:
            IdentityEdgeUpdateInput(
                identity_edge_id=identity_edge_id,
                evidence_entry=evidence_entry,
                intensity=intensity,
                verification_status=verification_status,
            )
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            edge = _get_edge(db, identity_edge_id)
            if edge is None:
                return {"error": "not_found", "detail": f"identity edge {identity_edge_id} not found"}
            if edge["type"] != "identity":
                return {"error": "invalid_type", "detail": "edge is not an identity edge"}

            fields: dict[str, object] = {}
            if intensity is not None:
                fields["intensity"] = intensity
            if verification_status is not None:
                fields["verification_status"] = verification_status

            if fields:
                sql, params = build_update("edges", fields, "id", identity_edge_id)
                db.execute(sql, params)

            if evidence_entry:
                ev_id = str(uuid.uuid4())
                db.execute(
                    """INSERT INTO identity_evidence
                       (id, identity_edge_id, signal_name, signal_value, direction, weight,
                        source_entry_id, recorded_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ev_id,
                        identity_edge_id,
                        evidence_entry.get("signal_name", ""),
                        evidence_entry.get("signal_value"),
                        evidence_entry.get("direction", "neutral"),
                        evidence_entry.get("weight", "medium"),
                        evidence_entry.get("source_entry_id"),
                        now_iso(),
                    ),
                )

            return _get_edge(db, identity_edge_id)

    @mcp.tool()
    def node_merge(
        node_ids: list[str],
        reason: str = "",
    ) -> dict:
        """合并多个节点为一个。保留第一个 node_id 作为主节点，迁移关系和属性。"""
        try:
            NodeMergeInput(node_ids=node_ids, reason=reason)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            nodes = []
            for nid in node_ids:
                node = _get_node(db, nid)
                if node is None:
                    return {"error": "not_found", "detail": f"node {nid} not found"}
                nodes.append(node)

            merged_node_id = node_ids[0]
            absorbed_ids = node_ids[1:]
            now = now_iso()

            # 合并 body：简单拼接，主节点在前
            merged_body = "\n\n---\n\n".join(
                [f"# {n['name']} ({n['type']})\n{n['body']}" for n in nodes]
            )
            db.execute(
                "UPDATE nodes SET body = ?, last_updated = ? WHERE id = ?",
                (merged_body, now, merged_node_id),
            )

            # 迁移边：source 或 target 为被吸收节点的，改为主节点
            for absorbed in absorbed_ids:
                # 更新 source_id
                db.execute(
                    "UPDATE edges SET source_id = ?, last_updated = ? WHERE source_id = ?",
                    (merged_node_id, now, absorbed),
                )
                # 更新 target_id
                db.execute(
                    "UPDATE edges SET target_id = ?, last_updated = ? WHERE target_id = ?",
                    (merged_node_id, now, absorbed),
                )

            # 删除被吸收节点
            for absorbed in absorbed_ids:
                db.execute("DELETE FROM nodes WHERE id = ?", (absorbed,))

            # 记录 merge_history
            history_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO merge_history
                   (id, merged_node_id, absorbed_node_ids, reason, evidence_snapshot, merged_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    history_id,
                    merged_node_id,
                    json.dumps(absorbed_ids),
                    reason,
                    "{}",
                    now,
                ),
            )

            return {
                "merged_node_id": merged_node_id,
                "absorbed_node_ids": absorbed_ids,
                "merge_history_id": history_id,
            }

    @mcp.tool()
    def node_unmerge(
        node_id: str,
        merge_event_index: int | None = None,
    ) -> dict:
        """拆分已合并节点。当前为简化实现：恢复最近一条 merge_history 记录。

        注意：这会丢失合并后新增的关系，属于破坏性恢复；完整 undo 需要更复杂的版本机制。
        """
        try:
            NodeUnmergeInput(node_id=node_id, merge_event_index=merge_event_index)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            current = _get_node(db, node_id)
            if current is None:
                return {"error": "not_found", "detail": f"node {node_id} not found"}

            if merge_event_index is None:
                row = db.execute(
                    "SELECT * FROM merge_history WHERE merged_node_id = ? ORDER BY merged_at DESC LIMIT 1",
                    (node_id,),
                ).fetchone()
            else:
                rows = db.execute(
                    "SELECT * FROM merge_history WHERE merged_node_id = ? ORDER BY merged_at ASC",
                    (node_id,),
                ).fetchall()
                if merge_event_index < 0 or merge_event_index >= len(rows):
                    return {"error": "invalid_index", "detail": "merge_event_index out of range"}
                row = rows[merge_event_index]

            if row is None:
                return {"error": "no_merge_history", "detail": f"node {node_id} has no merge history"}

            absorbed_ids = json.loads(row["absorbed_node_ids"])
            now = now_iso()

            # 恢复被吸收节点（仅恢复 id/name/type/body，关系需人工处理）
            restored = []
            for absorbed_id in absorbed_ids:
                # 这里无法精确还原原节点 body，简化用空 body
                db.execute(
                    "INSERT INTO nodes (id, type, name, body, first_seen, last_updated) "
                    "VALUES (?, 'unknown', ?, '', ?, ?)",
                    (absorbed_id, f"restored-{absorbed_id[:8]}", now, now),
                )
                restored.append(absorbed_id)

            return {
                "merged_node_id": node_id,
                "restored_node_ids": restored,
                "note": "unmerge restored node IDs only; original bodies and relationships are not fully recovered",
            }
