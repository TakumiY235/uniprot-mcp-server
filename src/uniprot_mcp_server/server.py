"""UniProt MCP Server implementation."""

import json
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence, Tuple, TypedDict

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uniprot-server")

# API configuration
API_BASE_URL = "https://rest.uniprot.org/uniprotkb"


class ProteinInfo(TypedDict):
    """Type definition for protein information."""

    accession: str
    protein_name: str
    function: list[str]
    sequence: str
    length: int
    organism: str


class Cache:
    """Simple cache implementation with TTL and max size limit."""

    def __init__(self, max_size: int = 100, ttl_hours: int = 24) -> None:
        """Initialize cache with size and TTL limits."""
        self.cache: OrderedDict[str, Tuple[Any, datetime]] = OrderedDict()
        self.max_size = max_size
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache if it exists and hasn't expired."""
        if key not in self.cache:
            return None
        item, timestamp = self.cache[key]
        if datetime.now() - timestamp > self.ttl:
            del self.cache[key]
            return None
        return item

    def set(self, key: str, value: Any) -> None:
        """Set a value in cache with current timestamp."""
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        self.cache[key] = (value, datetime.now())


class UniProtServer:
    """MCP server for UniProt protein data access."""

    def __init__(self) -> None:
        """Initialize the server with cache and handlers."""
        self.server = Server("uniprot-server")
        self.cache = Cache()
        self.setup_handlers()

    def setup_handlers(self) -> None:
        """Set up MCP protocol handlers."""
        self.setup_tool_handlers()

    def setup_tool_handlers(self) -> None:
        """Configure tool-related request handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available UniProt tools."""
            return [
                Tool(
                    name="get_protein_info",
                    description=(
                        "Get protein function and sequence information from UniProt "
                        "using an accession No."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "accession": {
                                "type": "string",
                                "description": "UniProt Accession No. (e.g., P12345)",
                            }
                        },
                        "required": ["accession"],
                    },
                ),
                Tool(
                    name="get_batch_protein_info",
                    description="Get protein information for multiple accession No.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "accessions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of UniProt accession No.",
                            }
                        },
                        "required": ["accessions"],
                    },
                ),
            ]

        async def fetch_protein_info(accession: str) -> ProteinInfo:
            """Fetch protein information from UniProt API with caching."""
            # Check cache first
            cached_data = self.cache.get(accession)
            if cached_data:
                logger.info(f"Cache hit for {accession}")
                return cached_data

            logger.info(f"Fetching data for {accession}")
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{API_BASE_URL}/{accession}",
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

                # Extract relevant information
                protein_info: ProteinInfo = {
                    "accession": accession,
                    "protein_name": data.get("proteinDescription", {})
                    .get("recommendedName", {})
                    .get("fullName", {})
                    .get("value", "Unknown"),
                    "function": [],
                    "sequence": "",
                    "length": 0,
                    "organism": "Unknown",
                }

                # Extract function information safely
                for comment in data.get("comments", []):
                    if comment.get("commentType") == "FUNCTION":
                        texts = comment.get("texts", [])
                        if texts:
                            protein_info["function"].extend(
                                [text.get("value", "") for text in texts]
                            )

                # Add sequence information
                seq_info = data.get("sequence", {})
                org_info = data.get("organism", {})

                protein_info.update(
                    {
                        "sequence": seq_info.get("value", ""),
                        "length": seq_info.get("length", 0),
                        "organism": org_info.get("scientificName", "Unknown"),
                    }
                )

                # Cache the result
                self.cache.set(accession, protein_info)
                return protein_info

        @self.server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> Sequence[TextContent]:
            """Handle tool execution requests."""
            try:
                if name == "get_protein_info":
                    accession = arguments.get("accession")
                    if not accession:
                        raise ValueError("Accession No. is required")

                    protein_info = await fetch_protein_info(accession)
                    return [
                        TextContent(
                            type="text", text=json.dumps(protein_info, indent=2)
                        )
                    ]

                elif name == "get_batch_protein_info":
                    accessions = arguments.get("accessions", [])
                    if not accessions:
                        raise ValueError("At least one accession No. is required")

                    results = []
                    for accession in accessions:
                        try:
                            protein_info = await fetch_protein_info(accession)
                            results.append(protein_info)
                        except httpx.HTTPError as e:
                            results.append(
                                {
                                    "accession": accession,
                                    "error": f"Failed to fetch data: {str(e)}",
                                }
                            )

                    return [
                        TextContent(type="text", text=json.dumps(results, indent=2))
                    ]

                else:
                    raise ValueError(f"Unknown tool: {name}")

            except httpx.HTTPError as e:
                logger.error(f"UniProt API error: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=f"Error fetching protein information: {str(e)}",
                    )
                ]
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=f"An unexpected error occurred: {str(e)}",
                    )
                ]

    async def run(self) -> None:
        """Start the server using stdio transport."""
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


async def main() -> None:
    """Run the server."""
    server = UniProtServer()
    await server.run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
