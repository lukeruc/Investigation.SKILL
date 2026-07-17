"""会话操作：session_create, session_open, session_get。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from datetime import datetime, timezone

from mcp.server import FastMCP

from investigation_graph.db import (
    NoActiveCaseError,
    db_connection,
    get_active_case,
    init_db,
    now_iso,
    set_active_case,
)
from investigation_graph.models import SessionCreateInput, SessionOpenInput


def _case_dir_name(name: str) -> str:
    """生成案件目录名，清理不合法字符。"""
    safe_name = name.replace("/", "-").replace("\\", "-").replace("..", "-")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    return f"{ts}-{safe_name}"


def register_session_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def session_create(
        workspace_path: str,
        name: str,
        goal: str = "",
        depth_limit: int = 3,
    ) -> dict:
        """创建新的调查案件。

        在 workspace_path 下创建 '{timestamp}-{name}/' 目录 + case.db，
        切换活跃连接到此新案件。
        """
        try:
            SessionCreateInput(
                workspace_path=workspace_path, name=name, goal=goal, depth_limit=depth_limit
            )
        except Exception as exc:
            return {"error": "invalid_input", "detail": str(exc)}

        case_dir = Path(workspace_path) / _case_dir_name(name)
        db_path = case_dir / "case.db"

        if db_path.exists():
            return {"error": "already_exists", "detail": f"case already exists at {case_dir}"}

        try:
            case_dir.mkdir(parents=True, exist_ok=True)
            init_db(db_path)
            set_active_case(db_path)
        except Exception as exc:
            return {"error": "internal_error", "detail": str(exc)}

        with db_connection() as db:
            session_id = str(uuid.uuid4())
            now = now_iso()
            db.execute(
                "INSERT INTO sessions (id, goal, depth_limit, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (session_id, goal, depth_limit, now, now),
            )

        return {
            "case_path": str(case_dir),
            "case_id": session_id,
            "goal": goal,
            "depth_limit": depth_limit,
            "created_at": now,
        }

    @mcp.tool()
    def session_open(case_path: str) -> dict:
        """打开已有案件，切换到该案件的 case.db。"""
        try:
            SessionOpenInput(case_path=case_path)
        except Exception as exc:
            return {"error": "invalid_input", "detail": str(exc)}

        db_path = Path(case_path) / "case.db"
        if not db_path.exists():
            return {
                "error": "case_not_found",
                "detail": f"path {case_path} does not contain case.db",
            }

        try:
            from investigation_graph.db import ensure_schema

            ensure_schema(db_path)
            set_active_case(db_path)
        except Exception as exc:
            return {"error": "internal_error", "detail": str(exc)}

        with db_connection() as db:
            row = db.execute("SELECT * FROM sessions LIMIT 1").fetchone()
            if row is None:
                return {"error": "case_not_found", "detail": "database has no session record"}

            return {
                "case_path": str(case_path),
                "goal": row["goal"],
                "depth_limit": row["depth_limit"],
                "round_number": row["round_number"],
                "status": row["status"],
                "seed_node_id": row["seed_node_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    @mcp.tool()
    def session_get() -> dict:
        """获取当前活跃案件的会话状态。"""
        try:
            db_path = get_active_case()
        except NoActiveCaseError as exc:
            return {"error": "no_active_db", "detail": str(exc)}

        with db_connection(db_path) as db:
            row = db.execute("SELECT * FROM sessions LIMIT 1").fetchone()
            if row is None:
                return {"error": "case_not_found", "detail": "no session record in current database"}

            return {
                "case_path": str(db_path.parent),
                "goal": row["goal"],
                "depth_limit": row["depth_limit"],
                "round_number": row["round_number"],
                "status": row["status"],
                "seed_node_id": row["seed_node_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
