"""边工具测试。"""

from __future__ import annotations

import pytest

from investigation_graph.tools.edges import register_edge_tools
from investigation_graph.tools.nodes import register_node_tools
from mcp.server import FastMCP


@pytest.fixture
def edges():
    mcp = FastMCP("test")
    register_edge_tools(mcp)
    return {
        "create": mcp._tool_manager._tools["edge_create"].fn,
        "from_node": mcp._tool_manager._tools["edges_from_node"].fn,
    }


@pytest.fixture
def nodes():
    mcp = FastMCP("test")
    register_node_tools(mcp)
    return mcp._tool_manager._tools["node_create"].fn


@pytest.fixture
def two_nodes(fresh_case_with_session, nodes):
    a = nodes(type="person", name="张三")
    b = nodes(type="organization", name="A公司")
    return a["node_id"], b["node_id"]


def test_edge_create_and_from_node(edges, fresh_case_with_session, two_nodes):
    a, b = two_nodes
    created = edges["create"](source_id=a, target_id=b, type="employment", body="总经理")
    assert created["created"] is True
    assert created["deduplicated"] is False

    from_a = edges["from_node"](node_id=a)
    assert len(from_a) == 1
    assert from_a[0]["source_name"] == "张三"
    assert from_a[0]["target_name"] == "A公司"


def test_edge_create_dedup_directed(edges, fresh_case_with_session, two_nodes):
    a, b = two_nodes
    first = edges["create"](source_id=a, target_id=b, type="employment")
    second = edges["create"](source_id=a, target_id=b, type="employment")

    assert second["created"] is False
    assert second["deduplicated"] is True
    assert first["edge_id"] == second["edge_id"]


def test_edge_create_undirected_dedup_both_orientations(
    edges, fresh_case_with_session, two_nodes
):
    a, b = two_nodes
    first = edges["create"](source_id=a, target_id=b, type="partner", direction="undirected")
    second = edges["create"](source_id=b, target_id=a, type="partner", direction="undirected")

    assert second["created"] is False
    assert second["deduplicated"] is True
    assert first["edge_id"] == second["edge_id"]


def test_edge_invalid_reference(edges, fresh_case_with_session, nodes):
    a = nodes(type="person", name="张三")
    result = edges["create"](source_id=a["node_id"], target_id="missing", type="x")
    assert result["error"] == "invalid_reference"


def test_edges_from_node_filter(edges, fresh_case_with_session, two_nodes):
    a, b = two_nodes
    edges["create"](source_id=a, target_id=b, type="employment")
    edges["create"](source_id=a, target_id=b, type="investment")

    filtered = edges["from_node"](node_id=a, edge_type="employment")
    assert len(filtered) == 1
    assert filtered[0]["type"] == "employment"


def test_edge_invalid_intensity(edges, fresh_case_with_session, two_nodes):
    a, b = two_nodes
    result = edges["create"](source_id=a, target_id=b, type="x", intensity=1.5)
    assert result["error"] == "invalid_input"
