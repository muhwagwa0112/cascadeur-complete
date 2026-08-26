"""PyInstaller entry point for the MCP server and its self-contained smoke client."""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        del sys.argv[1]
        from mcp_smoke_runtime import main as smoke_main

        smoke_main()
        return

    from cascadeur_complete.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
