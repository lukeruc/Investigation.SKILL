from __future__ import annotations

import pytest

from investigation_graph.tools.identity import register_identity_tools
from investigation_graph.tools.nodes import register_node_tools
from mcp.server import FastMCP


@pytest.fixture
def identity_tools():
    mcp = FastMCP("test")
    register_node_tools(mcp)
    register_identity_tools(mcp)
    return {
        "node_create": mcp._tool_manager._tools["node_create"].fn,
        "identity_edge_create": mcp._tool_manager._tools["identity_edge_create"].fn,
        "identity_edge_update": mcp._tool_manager._tools["identity_edge_update"].fn,
        "node_merge": mcp._tool_manager._tools["node_merge"].fn,
        "node_unmerge": mcp._tool_manager._tools["node_unmerge"].fn,
    }


def test_identity_edge_create_and_update(fresh_case_with_session, identity_tools):
    node_create = identity_tools["node_create"]
    identity_edge_create = identity_tools["identity_edge_create"]
    identity_edge_update = identity_tools["identity_edge_update"]

    a = node_create(type="person", name="张三")["node_id"]
    b = node_create(type="person", name="张三")["node_id"]

    edge = identity_edge_create(node_a_id=a, node_b_id=b, match_basis="name_match")
    assert edge["created"] is True
    assert "edge_id" in edge

    duplicate = identity_edge_create(node_a_id=a, node_b_id=b, match_basis="name_match")
    assert duplicate["created"] is False
    assert duplicate["edge_id"] == edge["edge_id"]

    updated = identity_edge_update(
        identity_edge_id=edge["edge_id"],
        intensity=0.9,
        verification_status="verified",
        evidence_entry={
            "signal_name": "同名同地址",
            "signal_value": "北京市海淀区",
            "direction": "supporting",
            "weight": "high",
        },
    )
    assert updated["verification_status"] == "verified"
    assert updated["intensity"] == 0.9


def test_node_merge_and_unmerge(fresh_case_with_session, identity_tools):
    node_create = identity_tools["node_create"]
    node_merge = identity_tools["node_merge"]
    node_unmerge = identity_tools["node_unmerge"]

    a = node_create(type="person", name="张三-A")["node_id"]
    b = node_create(type="person", name="张三-B")["node_id"]

    merged = node_merge(node_ids=[a, b], reason="同名同公司")
    assert merged["merged_node_id"] == a
    assert merged["absorbed_node_ids"] == [b]

    unmerged = node_unmerge(node_id=a)
    assert b in unmerged["restored_node_ids"]
