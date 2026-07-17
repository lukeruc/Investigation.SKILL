"""图分析工具测试。"""

from __future__ import annotations

import pytest

from investigation_graph.tools.edges import register_edge_tools
from investigation_graph.tools.graph import register_graph_tools
from investigation_graph.tools.nodes import register_node_tools
from mcp.server import FastMCP


@pytest.fixture
def graph():
    mcp = FastMCP("test")
    register_graph_tools(mcp)
    return mcp._tool_manager._tools["graph_snapshot"].fn


@pytest.fixture
def nodes():
    mcp = FastMCP("test")
    register_node_tools(mcp)
    return mcp._tool_manager._tools["node_create"].fn


@pytest.fixture
def edges():
    mcp = FastMCP("test")
    register_edge_tools(mcp)
    return mcp._tool_manager._tools["edge_create"].fn


def test_graph_snapshot_empty(graph, fresh_case_with_session):
    snap = graph()
    assert snap["summary"]["total_nodes"] == 0
    assert snap["summary"]["total_edges"] == 0


def test_graph_snapshot_counts(graph, nodes, edges, fresh_case_with_session):
    a = nodes(type="person", name="张三")
    b = nodes(type="organization", name="A公司")
    c = nodes(type="organization", name="B公司")
    edges(source_id=a["node_id"], target_id=b["node_id"], type="employment")
    edges(source_id=a["node_id"], target_id=c["node_id"], type="employment")

    snap = graph()
    assert snap["summary"]["total_nodes"] == 3
    assert snap["summary"]["total_edges"] == 2
    assert len(snap["top_central_nodes"]) == 3
    assert snap["top_central_nodes"][0]["name"] == "张三"
    assert snap["top_central_nodes"][0]["degree"] == 2


def test_graph_snapshot_no_active_db(graph):
    result = graph()
    assert result["error"] == "no_active_db"
