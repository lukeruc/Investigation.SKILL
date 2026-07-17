from __future__ import annotations

import pytest

from investigation_graph.tools.edges import register_edge_tools
from investigation_graph.tools.graph import register_graph_tools
from investigation_graph.tools.nodes import register_node_tools
from mcp.server import FastMCP


@pytest.fixture
def graph_tools():
    mcp = FastMCP("test")
    register_node_tools(mcp)
    register_edge_tools(mcp)
    register_graph_tools(mcp)
    return {
        "node_create": mcp._tool_manager._tools["node_create"].fn,
        "edge_create": mcp._tool_manager._tools["edge_create"].fn,
        "graph_path": mcp._tool_manager._tools["graph_path"].fn,
        "graph_neighbors": mcp._tool_manager._tools["graph_neighbors"].fn,
    }


def test_graph_path_direct(fresh_case_with_session, graph_tools):
    node_create = graph_tools["node_create"]
    edge_create = graph_tools["edge_create"]
    graph_path = graph_tools["graph_path"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="organization", name="A公司")["node_id"]
    edge_create(source_id=a, target_id=b, type="employment")

    result = graph_path(source_node_id=a, target_node_id=b)
    assert result["path"] is not None
    assert len(result["path"]) == 2
    assert result["path"][0]["node_id"] == a
    assert result["path"][1]["node_id"] == b
    assert len(result["edges"]) == 1


def test_graph_path_via_intermediate(fresh_case_with_session, graph_tools):
    node_create = graph_tools["node_create"]
    edge_create = graph_tools["edge_create"]
    graph_path = graph_tools["graph_path"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="organization", name="A公司")["node_id"]
    c = node_create(type="organization", name="B公司")["node_id"]
    edge_create(source_id=a, target_id=b, type="employment")
    edge_create(source_id=b, target_id=c, type="investment")

    result = graph_path(source_node_id=a, target_node_id=c)
    assert result["path"] is not None
    assert len(result["path"]) == 3
    assert result["path"][0]["node_id"] == a
    assert result["path"][2]["node_id"] == c
    assert len(result["edges"]) == 2


def test_graph_path_not_found(fresh_case_with_session, graph_tools):
    node_create = graph_tools["node_create"]
    graph_path = graph_tools["graph_path"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="person", name="李四")["node_id"]

    result = graph_path(source_node_id=a, target_node_id=b)
    assert result["path"] is None
    assert result["edges"] is None


def test_graph_neighbors_depth_one(fresh_case_with_session, graph_tools):
    node_create = graph_tools["node_create"]
    edge_create = graph_tools["edge_create"]
    graph_neighbors = graph_tools["graph_neighbors"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="organization", name="A公司")["node_id"]
    c = node_create(type="organization", name="B公司")["node_id"]
    edge_create(source_id=a, target_id=b, type="employment")
    edge_create(source_id=a, target_id=c, type="employment")

    result = graph_neighbors(node_id=a, depth=1)
    neighbor_ids = {n["node_id"] for n in result["nodes"]}
    assert neighbor_ids == {b, c}


def test_graph_neighbors_depth_two(fresh_case_with_session, graph_tools):
    node_create = graph_tools["node_create"]
    edge_create = graph_tools["edge_create"]
    graph_neighbors = graph_tools["graph_neighbors"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="organization", name="A公司")["node_id"]
    c = node_create(type="person", name="李四")["node_id"]
    edge_create(source_id=a, target_id=b, type="employment")
    edge_create(source_id=b, target_id=c, type="shareholder")

    result = graph_neighbors(node_id=a, depth=2)
    neighbor_ids = {n["node_id"] for n in result["nodes"]}
    assert c in neighbor_ids
    assert b in neighbor_ids
