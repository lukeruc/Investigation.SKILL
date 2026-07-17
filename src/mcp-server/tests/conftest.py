"""pytest 配置与共享 fixtures。"""

from __future__ import annotations

import pytest

from investigation_graph.db import clear_active_case, init_db, set_active_case


@pytest.fixture(autouse=True)
def reset_active_case():
    """每个测试结束后清除全局活跃案件路径。"""
    yield
    clear_active_case()


@pytest.fixture
def fresh_case(tmp_path):
    """创建一个空白案件目录并切换为活跃案件。"""
    case_dir = tmp_path / "test-case"
    case_dir.mkdir()
    db_path = case_dir / "case.db"
    init_db(db_path)
    set_active_case(db_path)
    return case_dir


@pytest.fixture
def fresh_case_with_session(fresh_case):
    """创建案件并插入一条 session 记录。"""
    import uuid

    from investigation_graph.db import db_connection, now_iso

    session_id = str(uuid.uuid4())
    now = now_iso()
    with db_connection() as db:
        db.execute(
            "INSERT INTO sessions (id, goal, depth_limit, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, ?)",
            (session_id, "test goal", 3, now, now),
        )
    return fresh_case
