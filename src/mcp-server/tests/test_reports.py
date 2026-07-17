from __future__ import annotations

import pytest

from investigation_graph.tools.edges import register_edge_tools
from investigation_graph.tools.nodes import register_node_tools
from investigation_graph.tools.reports import register_report_tools
from mcp.server import FastMCP


@pytest.fixture
def report_tools():
    mcp = FastMCP("test")
    register_node_tools(mcp)
    register_edge_tools(mcp)
    register_report_tools(mcp)
    return {
        "node_create": mcp._tool_manager._tools["node_create"].fn,
        "edge_create": mcp._tool_manager._tools["edge_create"].fn,
        "report_summary": mcp._tool_manager._tools["report_summary"].fn,
    }


def test_report_summary_basic(fresh_case_with_session, report_tools):
    node_create = report_tools["node_create"]
    edge_create = report_tools["edge_create"]
    report_summary = report_tools["report_summary"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="organization", name="A公司")["node_id"]
    edge_create(source_id=a, target_id=b, type="employment")

    summary = report_summary(node_id=a)
    assert "error" not in summary
    assert summary["node"]["name"] == "张三"
    assert len(summary["edges"]) == 1
    assert summary["edges"][0]["target_name"] == "A公司"
    assert "verification_summary" in summary


def test_report_summary_not_found(fresh_case_with_session, report_tools):
    report_summary = report_tools["report_summary"]
    result = report_summary(node_id="nonexistent")
    assert result["error"] == "not_found"
