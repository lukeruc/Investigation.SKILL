"""兼容 shim：旧的 MCP 配置使用 `-m server` 启动时会进入此文件。"""

from __future__ import annotations

from investigation_graph.server import main

if __name__ == "__main__":
    main()
