"""会话工具测试。"""

from __future__ import annotations

import pytest

from investigation_graph.db import NoActiveCaseError, get_active_case
from investigation_graph.tools.sessions import register_session_tools
from mcp.server import FastMCP


@pytest.fixture
def sessions():
    mcp = FastMCP("test")
    register_session_tools(mcp)
    return {
        "create": mcp._tool_manager._tools["session_create"].fn,
        "open": mcp._tool_manager._tools["session_open"].fn,
        "get": mcp._tool_manager._tools["session_get"].fn,
    }
def test_session_create_makes_directory_and_db(sessions, tmp_path):
    result = sessions["create"](workspace_path=str(tmp_path), name="test")

    assert "error" not in result
    assert result["goal"] == ""
    assert result["depth_limit"] == 3
    assert (tmp_path / result["case_path"].split("/")[-1] / "case.db").exists()


def test_session_get_without_active_case(sessions):
    result = sessions["get"]()
    assert result["error"] == "no_active_db"


def test_session_open_and_get(sessions, fresh_case_with_session):
    case_path = str(fresh_case_with_session)
    opened = sessions["open"](case_path=case_path)
    assert "error" not in opened

    got = sessions["get"]()
    assert got["case_path"] == case_path
    assert got["goal"] == "test goal"
