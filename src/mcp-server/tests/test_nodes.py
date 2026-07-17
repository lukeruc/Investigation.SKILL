"""节点工具测试。"""

from __future__ import annotations

import pytest

from investigation_graph.tools.nodes import register_node_tools
from mcp.server import FastMCP


@pytest.fixture
def nodes():
    mcp = FastMCP("test")
    register_node_tools(mcp)
    return {
        "create": mcp._tool_manager._tools["node_create"].fn,
        "get": mcp._tool_manager._tools["node_get"].fn,
        "update": mcp._tool_manager._tools["node_update"].fn,
        "search": mcp._tool_manager._tools["node_search"].fn,
        "list_gaps": mcp._tool_manager._tools["node_list_gaps"].fn,
    }


def test_node_create_and_get(nodes, fresh_case_with_session):
    created = nodes["create"](type="person", name="张三", body="测试")
    assert "error" not in created
    assert created["type"] == "person"

    got = nodes["get"](node_id=created["node_id"])
    assert got["name"] == "张三"
    assert got["edges"] == []


def test_node_update(nodes, fresh_case_with_session):
    created = nodes["create"](type="person", name="张三")
    updated = nodes["update"](
        node_id=created["node_id"],
        exploration_status="explored",
        confidence="high",
        anomaly_flags=["suspicious"],
    )
    assert updated["exploration_status"] == "explored"
    assert updated["confidence"] == "high"
    assert updated["anomaly_flags"] == ["suspicious"]


def test_node_update_not_found(nodes, fresh_case_with_session):
    result = nodes["update"](node_id="nonexistent", exploration_status="explored")
    assert result["error"] == "not_found"


def test_node_search(nodes, fresh_case_with_session):
    nodes["create"](type="person", name="张三")
    nodes["create"](type="organization", name="A公司")

    results = nodes["search"](name_pattern="张三")
    assert len(results) == 1
    assert results[0]["name"] == "张三"

    results = nodes["search"](type="organization")
    assert len(results) == 1
    assert results[0]["name"] == "A公司"


def test_node_list_gaps(nodes, fresh_case_with_session):
    nodes["create"](type="person", name="张三")
    explored = nodes["create"](type="person", name="李四")
    nodes["update"](node_id=explored["node_id"], exploration_status="explored")

    gaps = nodes["list_gaps"]()
    assert len(gaps) == 1
    assert gaps[0]["name"] == "张三"


def test_node_invalid_confidence(nodes, fresh_case_with_session):
    result = nodes["create"](type="person", name="张三", confidence="invalid")
    assert result["error"] == "invalid_input"


def test_node_no_active_db(nodes):
    result = nodes["create"](type="person", name="张三")
    assert result["error"] == "no_active_db"
