"""安全的参数化 SQL 构造辅助函数。

规则：
- 所有用户提供的值使用 ? 占位符。
- 只有代码内部白名单中的字段名可以出现在 SQL 字面量中。
"""

from __future__ import annotations

from typing import Any

from investigation_graph.db import now_iso

# ---------------------------------------------------------------------------
# Whitelists
# ---------------------------------------------------------------------------

NODE_UPDATE_COLUMNS = {"body", "confidence", "exploration_status", "anomaly_flags"}
EDGE_UPDATE_COLUMNS = {
    "body",
    "confidence",
    "verification_status",
    "intensity",
    "anomaly_flags",
    "contradicted_by",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_update(
    table: str, fields: dict[str, Any], pk_column: str, pk_value: Any
) -> tuple[str, list[Any]]:
    """构造 UPDATE 语句。

    只保留白名单中的非 None 字段。返回 (sql, params)。
    """
    valid_cols = [c for c in fields if c in NODE_UPDATE_COLUMNS | EDGE_UPDATE_COLUMNS and fields[c] is not None]
    if not valid_cols:
        raise ValueError("no valid fields to update")

    sets = ", ".join(f"{col} = ?" for col in valid_cols)
    sql = f"UPDATE {table} SET {sets}, last_updated = ? WHERE {pk_column} = ?"
    params = [fields[col] for col in valid_cols] + [now_iso(), pk_value]
    return sql, params


def build_select_nodes_where(
    type_value: str | None = None,
    name_pattern: str | None = None,
    exploration_status_in: list[str] | None = None,
) -> tuple[str, list[Any]]:
    """构造节点查询的 WHERE 子句。"""
    conditions: list[str] = []
    params: list[Any] = []

    if type_value is not None:
        conditions.append("type = ?")
        params.append(type_value)

    if name_pattern is not None:
        conditions.append("name LIKE ?")
        params.append(f"%{name_pattern}%")

    if exploration_status_in:
        placeholders = ", ".join("?" for _ in exploration_status_in)
        conditions.append(f"exploration_status IN ({placeholders})")
        params.extend(exploration_status_in)

    where = " AND ".join(conditions) if conditions else "1=1"
    return where, params


def build_edges_where(node_id: str, edge_type: str | None, direction: str | None) -> tuple[str, list[Any]]:
    """构造边查询的 WHERE 子句。"""
    conditions = ["(e.source_id = ? OR e.target_id = ?)"]
    params: list[Any] = [node_id, node_id]

    if edge_type is not None:
        conditions.append("e.type = ?")
        params.append(edge_type)

    if direction is not None:
        conditions.append("e.direction = ?")
        params.append(direction)

    return " AND ".join(conditions), params
