"""UniProt MCP Server package."""

import asyncio

from . import server


def main() -> None:
    """Main entry point for the package."""
    asyncio.run(server.main())
