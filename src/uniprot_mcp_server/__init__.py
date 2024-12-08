"""UniProt MCP Server package."""

from . import server
import asyncio


def main() -> None:
    """Main entry point for the package."""
    asyncio.run(server.main())