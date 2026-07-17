"""图分析：graph_snapshot, graph_path, graph_neighbors。"""

from __future__ import annotations

from collections import deque

from mcp.server import FastMCP

from investigation_graph.db import NoActiveCaseError, db_connection, get_active_case
from investigation_graph.models import GraphSnapshotInput, GraphPathInput, GraphNeighborsInput


def _get_all_edges(db) -> list[dict]:
    """读取当前案件所有边，返回 source/target/type/direction 列表。"""
    rows = db.execute("SELECT source_id, target_id, type, direction FROM edges").fetchall()
    return [dict(r) for r in rows]


def _build_neighbors(edges: list[dict]) -> dict[str, list[tuple[str, str, str]]]:
    """构建邻接表：node_id -> [(neighbor_id, edge_id, edge_type)]。"""
    neighbors: dict[str, list[tuple[str, str, str]]] = {}
    for edge in edges:
        eid = edge.get("id") or ""
        # edge rows from _get_all_edges don't have id; use type+direction as fallback key for dedup
        key = f"{edge['source_id']}-{edge['target_id']}-{edge['type']}-{edge['direction']}"
        source = edge["source_id"]
        target = edge["target_id"]
        etype = edge["type"]
        direction = edge["direction"]

        if source not in neighbors:
            neighbors[source] = []
        if target not in neighbors:
            neighbors[target] = []

        neighbors[source].append((target, key, etype))
        if direction == "undirected":
            neighbors[target].append((source, key, etype))
        else:
            neighbors[target].append((source, key, f"~{etype}"))
    return neighbors


def _node_exists(db, node_id: str) -> bool:
    return db.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone() is not None


def register_graph_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def graph_snapshot() -> dict:
        """返回当前案件的全图摘要。"""
        try:
            GraphSnapshotInput()
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            total_nodes = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            total_edges = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            session_round = db.execute("SELECT round_number FROM sessions LIMIT 1").fetchone()
            session_round = session_round[0] if session_round else 0

            nodes_by_type = [
                dict(r)
                for r in db.execute("SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type").fetchall()
            ]
            edges_by_type = [
                dict(r)
                for r in db.execute("SELECT type, COUNT(*) as cnt FROM edges GROUP BY type").fetchall()
            ]
            nodes_by_status = [
                dict(r)
                for r in db.execute(
                    "SELECT exploration_status, COUNT(*) as cnt FROM nodes GROUP BY exploration_status"
                ).fetchall()
            ]
            edges_by_vstatus = [
                dict(r)
                for r in db.execute(
                    "SELECT verification_status, COUNT(*) as cnt FROM edges GROUP BY verification_status"
                ).fetchall()
            ]

            top_central = [
                dict(r)
                for r in db.execute(
                    "SELECT n.id, n.name, n.type, "
                    " (SELECT COUNT(*) FROM edges WHERE source_id=n.id) + "
                    " (SELECT COUNT(*) FROM edges WHERE target_id=n.id) as degree "
                    "FROM nodes n ORDER BY degree DESC LIMIT 10"
                ).fetchall()
            ]

            seed_nodes = [
                dict(r)
                for r in db.execute(
                    "SELECT n.id, n.name, n.type FROM nodes n "
                    "JOIN sessions s ON s.seed_node_id = n.id"
                ).fetchall()
            ]

            nodes_with_anomalies = db.execute(
                "SELECT COUNT(*) FROM nodes WHERE anomaly_flags != '[]'"
            ).fetchone()[0]
            edges_with_anomalies = db.execute(
                "SELECT COUNT(*) FROM edges WHERE anomaly_flags != '[]'"
            ).fetchone()[0]

            return {
                "summary": {
                    "total_nodes": total_nodes,
                    "total_edges": total_edges,
                    "session_round": session_round,
                },
                "nodes_by_type": nodes_by_type,
                "edges_by_type": edges_by_type,
                "nodes_by_status": nodes_by_status,
                "edges_by_vstatus": edges_by_vstatus,
                "top_central_nodes": top_central,
                "seed_nodes": seed_nodes,
                "anomaly_counts": {
                    "nodes_with_anomalies": nodes_with_anomalies,
                    "edges_with_anomalies": edges_with_anomalies,
                },
            }

    @mcp.tool()
    def graph_path(
        source_node_id: str,
        target_node_id: str,
        max_depth: int = 5,
    ) -> dict:
        """返回 source_node_id 到 target_node_id 的最短路径（BFS）。"""
        try:
            GraphPathInput(
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                max_depth=max_depth,
            )
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            if not _node_exists(db, source_node_id):
                return {"error": "not_found", "detail": f"source node {source_node_id} not found"}
            if not _node_exists(db, target_node_id):
                return {"error": "not_found", "detail": f"target node {target_node_id} not found"}

            edges = _get_all_edges(db)
            neighbors = _build_neighbors(edges)

            # BFS
            visited = {source_node_id}
            queue: deque[tuple[str, list[str], list[dict]]] = deque(
                [(source_node_id, [source_node_id], [])]
            )

            while queue:
                current, path_nodes, path_edges = queue.popleft()
                if len(path_nodes) > max_depth + 1:
                    continue
                if current == target_node_id:
                    nodes = [
                        {
                            "node_id": nid,
                            "name": row["name"],
                            "type": row["type"],
                        }
                        for nid in path_nodes
                        for row in [db.execute("SELECT name, type FROM nodes WHERE id = ?", (nid,)).fetchone()]
                    ]
                    return {
                        "path": nodes,
                        "edges": path_edges,
                    }

                for neighbor, edge_key, etype in neighbors.get(current, []):
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)
                    queue.append(
                        (
                            neighbor,
                            path_nodes + [neighbor],
                            path_edges
                            + [
                                {
                                    "edge_key": edge_key,
                                    "type": etype,
                                }
                            ],
                        )
                    )

            return {"path": None, "edges": None}

    @mcp.tool()
    def graph_neighbors(
        node_id: str,
        depth: int = 1,
    ) -> dict:
        """返回 node_id 在指定深度内的邻居节点和路径边。"""
        try:
            GraphNeighborsInput(node_id=node_id, depth=depth)
            db_path = get_active_case()
        except Exception as exc:
            if isinstance(exc, NoActiveCaseError):
                return {"error": "no_active_db", "detail": str(exc)}
            return {"error": "invalid_input", "detail": str(exc)}

        with db_connection(db_path) as db:
            if not _node_exists(db, node_id):
                return {"error": "not_found", "detail": f"node {node_id} not found"}

            edges = _get_all_edges(db)
            neighbors = _build_neighbors(edges)

            # BFS up to depth
            visited = {node_id}
            result_nodes: list[dict] = []
            result_edges: list[dict] = []
            queue: deque[tuple[str, int]] = deque([(node_id, 0)])

            while queue:
                current, d = queue.popleft()
                if d >= depth:
                    continue
                for neighbor, edge_key, etype in neighbors.get(current, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        row = db.execute("SELECT name, type FROM nodes WHERE id = ?", (neighbor,)).fetchone()
                        result_nodes.append({"node_id": neighbor, "name": row["name"], "type": row["type"]})
                        queue.append((neighbor, d + 1))
                    result_edges.append({"edge_key": edge_key, "type": etype})

            return {
                "source_node_id": node_id,
                "depth": depth,
                "nodes": result_nodes,
                "edges": result_edges,
            }
