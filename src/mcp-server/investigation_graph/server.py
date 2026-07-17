"""调查图谱 MCP Server — FastMCP 入口。"""

from __future__ import annotations

from mcp.server import FastMCP

from investigation_graph.tools.sessions import register_session_tools
from investigation_graph.tools.nodes import register_node_tools
from investigation_graph.tools.edges import register_edge_tools
from investigation_graph.tools.graph import register_graph_tools
from investigation_graph.tools.identity import register_identity_tools
from investigation_graph.tools.reports import register_report_tools


mcp = FastMCP(
    "investigation-graph",
    instructions="调查图谱存储引擎。每个案件一个 SQLite 文件（case.db），MCP Server 维护一个活跃数据库路径。",
)

register_session_tools(mcp)
register_node_tools(mcp)
register_edge_tools(mcp)
register_graph_tools(mcp)
register_identity_tools(mcp)
register_report_tools(mcp)


def main() -> None:
    mcp.run()
