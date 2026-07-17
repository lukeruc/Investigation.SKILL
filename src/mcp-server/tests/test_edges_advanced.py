from __future__ import annotations

import pytest

from investigation_graph.tools.edges import register_edge_tools
from investigation_graph.tools.nodes import register_node_tools
from mcp.server import FastMCP


@pytest.fixture
def edge_tools():
    mcp = FastMCP("test")
    register_node_tools(mcp)
    register_edge_tools(mcp)
    return {
        "node_create": mcp._tool_manager._tools["node_create"].fn,
        "edge_create": mcp._tool_manager._tools["edge_create"].fn,
        "edge_get": mcp._tool_manager._tools["edge_get"].fn,
        "edge_update": mcp._tool_manager._tools["edge_update"].fn,
    }


def test_edge_get_and_update(fresh_case_with_session, edge_tools):
    node_create = edge_tools["node_create"]
    edge_create = edge_tools["edge_create"]
    edge_get = edge_tools["edge_get"]
    edge_update = edge_tools["edge_update"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="organization", name="A公司")["node_id"]

    edge = edge_create(source_id=a, target_id=b, type="employment", body="执行董事")
    edge_id = edge["edge_id"]

    got = edge_get(edge_id=edge_id)
    assert got["id"] == edge_id
    assert got["verification_status"] == "unverified"
    assert got["source_chains"] == []

    updated = edge_update(
        edge_id=edge_id,
        verification_status="verified",
        intensity=0.9,
        anomaly_flags=["single_source"],
    )
    assert updated["id"] == edge_id
    assert updated["verification_status"] == "verified"
    assert updated["intensity"] == 0.9
    assert updated["anomaly_flags"] == ["single_source"]
    assert updated["last_updated"] > updated["first_seen"]


def test_edge_update_not_found(fresh_case_with_session, edge_tools):
    edge_update = edge_tools["edge_update"]
    result = edge_update(edge_id="nonexistent")
    assert result["error"] == "not_found"


def test_edge_update_no_fields(fresh_case_with_session, edge_tools):
    node_create = edge_tools["node_create"]
    edge_create = edge_tools["edge_create"]
    edge_update = edge_tools["edge_update"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="organization", name="A公司")["node_id"]
    edge_id = edge_create(source_id=a, target_id=b, type="employment")["edge_id"]

    updated = edge_update(edge_id=edge_id)
    assert updated["id"] == edge_id
    assert updated["verification_status"] == "unverified"
