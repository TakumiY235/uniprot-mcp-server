"""UniProt MCP Server implementation."""

import json
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence, Tuple, TypedDict, Union

import httpx
from mcp.server import Server
from mcp.types import TextContent, Tool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uniprot-server")

# API configuration
API_BASE_URL = "https://rest.uniprot.org/uniprotkb"
SEARCH_URL = f"{API_BASE_URL}/search"
# Bound every request so an unresponsive UniProt endpoint cannot hang the
# server indefinitely: 10s to connect, 30s overall.
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Ask the search endpoint for just these columns; a bare search returns whole
# entries, which is far more than a result list needs.
SEARCH_FIELDS = "accession,id,protein_name,organism_name,length,reviewed,gene_names"
MAX_SEARCH_RESULTS = 50

# Secondary structure is reported per element, so an entry carries dozens of
# these. They say nothing a sequence-design decision needs -- read them off the
# structure instead -- so they are withheld unless asked for by name.
SECONDARY_STRUCTURE_TYPES = frozenset({"Helix", "Beta strand", "Turn"})


class ProteinInfo(TypedDict):
    """Type definition for protein information."""

    accession: str
    protein_name: str
    function: list[str]
    sequence: str
    length: int
    organism: str


class Feature(TypedDict):
    """A single annotated region or residue, in 1-based inclusive coordinates."""

    type: str
    start: Optional[int]
    end: Optional[int]
    description: str


class FeatureInfo(TypedDict):
    """Sequence annotations for one protein."""

    accession: str
    length: int
    feature_counts: dict[str, int]
    features: list[Feature]


class PdbEntry(TypedDict):
    """An experimental structure covering part of a protein."""

    pdb_id: str
    method: str
    resolution: str
    chains: str


class StructureInfo(TypedDict):
    """Structures available for one protein."""

    accession: str
    pdb_entries: list[PdbEntry]
    alphafold_id: Optional[str]


class SearchHit(TypedDict):
    """One entry from a search, without the sequence."""

    accession: str
    entry_name: str
    protein_name: str
    gene_names: list[str]
    organism: str
    taxon_id: Optional[int]
    length: int
    reviewed: bool


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


def _protein_name(data: dict[str, Any]) -> str:
    """Read the display name, falling back the way UniProt nests alternatives.

    Reviewed entries carry a recommendedName; unreviewed ones often only have
    the name the submitter supplied, so reading recommendedName alone reports
    most of TrEMBL as "Unknown".
    """
    description = data.get("proteinDescription", {})
    recommended = description.get("recommendedName", {}).get("fullName", {})
    if recommended.get("value"):
        return str(recommended["value"])
    for submitted in description.get("submissionNames", []):
        value = submitted.get("fullName", {}).get("value")
        if value:
            return str(value)
    return "Unknown"


def _gene_names(data: dict[str, Any]) -> list[str]:
    """Collect primary gene names, skipping synonyms."""
    names: list[str] = []
    for gene in data.get("genes", []):
        value = gene.get("geneName", {}).get("value")
        if value:
            names.append(str(value))
    return names


def extract_protein_info(accession: str, data: dict[str, Any]) -> ProteinInfo:
    """Project a UniProt entry onto the fields get_protein_info reports."""
    protein_info: ProteinInfo = {
        "accession": accession,
        "protein_name": _protein_name(data),
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

    return protein_info


def extract_features(
    accession: str,
    data: dict[str, Any],
    types: Optional[Sequence[str]] = None,
    include_secondary_structure: bool = False,
) -> FeatureInfo:
    """Project a UniProt entry onto its sequence annotations, ordered by position.

    `types` keeps only the named feature types, compared case-insensitively.
    When it is given it decides on its own, so a caller may ask for "Helix"
    without also setting include_secondary_structure.
    """
    wanted = {t.casefold() for t in types} if types else None

    features: list[Feature] = []
    counts: dict[str, int] = {}
    for raw in data.get("features", []):
        feature_type = str(raw.get("type", "Unknown"))
        if wanted is not None:
            if feature_type.casefold() not in wanted:
                continue
        elif not include_secondary_structure:
            if feature_type in SECONDARY_STRUCTURE_TYPES:
                continue

        location = raw.get("location", {})
        features.append(
            {
                "type": feature_type,
                "start": location.get("start", {}).get("value"),
                "end": location.get("end", {}).get("value"),
                "description": str(raw.get("description", "")),
            }
        )
        counts[feature_type] = counts.get(feature_type, 0) + 1

    # A feature whose position is unknown sorts last rather than crashing the
    # comparison; UniProt leaves start null for those.
    features.sort(key=lambda f: (f["start"] is None, f["start"] or 0))

    return {
        "accession": accession,
        "length": data.get("sequence", {}).get("length", 0),
        "feature_counts": counts,
        "features": features,
    }


def extract_structures(accession: str, data: dict[str, Any]) -> StructureInfo:
    """Collect the PDB entries and AlphaFold model covering a protein."""
    pdb_entries: list[PdbEntry] = []
    alphafold_id: Optional[str] = None

    for xref in data.get("uniProtKBCrossReferences", []):
        database = xref.get("database")
        if database == "PDB":
            properties = {
                prop.get("key"): prop.get("value", "")
                for prop in xref.get("properties", [])
            }
            pdb_entries.append(
                {
                    "pdb_id": str(xref.get("id", "")),
                    "method": str(properties.get("Method", "")),
                    "resolution": str(properties.get("Resolution", "")),
                    "chains": str(properties.get("Chains", "")),
                }
            )
        elif database == "AlphaFoldDB" and alphafold_id is None:
            alphafold_id = str(xref.get("id", ""))

    pdb_entries.sort(key=lambda entry: entry["pdb_id"])

    return {
        "accession": accession,
        "pdb_entries": pdb_entries,
        "alphafold_id": alphafold_id,
    }


def _is_reviewed(entry: dict[str, Any]) -> bool:
    """Say whether an entry is Swiss-Prot rather than TrEMBL.

    The two entryType strings are "UniProtKB reviewed (Swiss-Prot)" and
    "UniProtKB unreviewed (TrEMBL)", so a bare substring test for "reviewed"
    matches both -- "unreviewed" has to be ruled out first.
    """
    entry_type = str(entry.get("entryType", "")).casefold()
    return "unreviewed" not in entry_type and "reviewed" in entry_type


def extract_search_hit(entry: dict[str, Any]) -> SearchHit:
    """Project one search result, leaving out the sequence."""
    organism = entry.get("organism", {})
    return {
        "accession": str(entry.get("primaryAccession", "")),
        "entry_name": str(entry.get("uniProtkbId", "")),
        "protein_name": _protein_name(entry),
        "gene_names": _gene_names(entry),
        "organism": str(organism.get("scientificName", "Unknown")),
        "taxon_id": organism.get("taxonId"),
        "length": entry.get("sequence", {}).get("length", 0),
        "reviewed": _is_reviewed(entry),
    }


def build_search_query(
    query: str, organism_id: Optional[int], reviewed_only: bool
) -> str:
    """Compose a UniProt query string from the caller's filters."""
    clauses = [f"({query})"]
    if organism_id is not None:
        clauses.append(f"organism_id:{organism_id}")
    if reviewed_only:
        clauses.append("reviewed:true")
    return " AND ".join(clauses)


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

    async def fetch_entry(self, accession: str) -> dict[str, Any]:
        """Fetch one whole UniProt entry, caching it by accession.

        get_protein_info, get_protein_features and get_protein_structures all
        read different parts of the same entry, so they share this one request
        rather than fetching the accession once each.
        """
        cached: Optional[dict[str, Any]] = self.cache.get(accession)
        if cached is not None:
            logger.info(f"Cache hit for {accession}")
            return cached

        logger.info(f"Fetching data for {accession}")
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(
                f"{API_BASE_URL}/{accession}",
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            entry: dict[str, Any] = response.json()

        self.cache.set(accession, entry)
        return entry

    async def search(
        self,
        query: str,
        organism_id: Optional[int] = None,
        reviewed_only: bool = True,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Search UniProtKB and return compact hits."""
        size = max(1, min(limit, MAX_SEARCH_RESULTS))
        full_query = build_search_query(query, organism_id, reviewed_only)
        cache_key = f"search:{size}:{full_query}"

        cached: Optional[list[SearchHit]] = self.cache.get(cache_key)
        if cached is not None:
            logger.info(f"Cache hit for search {full_query!r}")
            return cached

        logger.info(f"Searching for {full_query!r} (size={size})")
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(
                SEARCH_URL,
                params={
                    "query": full_query,
                    "fields": SEARCH_FIELDS,
                    "size": str(size),
                    "format": "json",
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

        hits = [extract_search_hit(entry) for entry in payload.get("results", [])]
        self.cache.set(cache_key, hits)
        return hits

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
                Tool(
                    name="search_proteins",
                    description=(
                        "Search UniProtKB by protein name, gene name or keyword and "
                        "return matching accession No. with their names, organisms "
                        "and lengths. Use this when the accession No. is not known "
                        "yet; sequences are not included."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Search terms, e.g. 'phospholipase A2' or "
                                    "'gene:PLA2G1B'. UniProt query syntax is accepted."
                                ),
                            },
                            "organism_id": {
                                "type": "integer",
                                "description": (
                                    "Restrict to one NCBI taxonomy ID "
                                    "(e.g., 9606 for human)."
                                ),
                            },
                            "reviewed_only": {
                                "type": "boolean",
                                "description": (
                                    "Restrict to reviewed Swiss-Prot entries. "
                                    "Defaults to true."
                                ),
                            },
                            "limit": {
                                "type": "integer",
                                "description": (
                                    f"Maximum hits to return, 1-{MAX_SEARCH_RESULTS}. "
                                    "Defaults to 10."
                                ),
                            },
                        },
                        "required": ["query"],
                    },
                ),
                Tool(
                    name="get_protein_features",
                    description=(
                        "Get the annotated sequence features of a protein with their "
                        "1-based inclusive positions: signal peptide, propeptide, "
                        "mature chain, active and binding sites, disulfide bonds, "
                        "domains, glycosylation, natural variants and mutagenesis. "
                        "Use this to find the boundaries and residues a construct or "
                        "variant design must respect. Secondary structure (helix, "
                        "beta strand, turn) is omitted unless asked for."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "accession": {
                                "type": "string",
                                "description": "UniProt Accession No. (e.g., P04054)",
                            },
                            "types": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Keep only these feature types, e.g. "
                                    "['Active site', 'Disulfide bond']. "
                                    "Omit for all types."
                                ),
                            },
                            "include_secondary_structure": {
                                "type": "boolean",
                                "description": (
                                    "Include Helix, Beta strand and Turn features. "
                                    "Defaults to false."
                                ),
                            },
                        },
                        "required": ["accession"],
                    },
                ),
                Tool(
                    name="get_protein_structures",
                    description=(
                        "Get the structures available for a protein: PDB entries "
                        "with their experimental method, resolution and the chains "
                        "and residue ranges they cover, plus the AlphaFold DB model "
                        "if one exists."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "accession": {
                                "type": "string",
                                "description": "UniProt Accession No. (e.g., P04054)",
                            }
                        },
                        "required": ["accession"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> Sequence[TextContent]:
            """Handle tool execution requests."""
            try:
                if name == "get_protein_info":
                    accession = self._require_accession(arguments)
                    entry = await self.fetch_entry(accession)
                    return self._as_json(extract_protein_info(accession, entry))

                elif name == "get_batch_protein_info":
                    accessions = arguments.get("accessions", [])
                    if not accessions:
                        raise ValueError("At least one accession No. is required")

                    results: list[Union[ProteinInfo, dict[str, str]]] = []
                    for accession in accessions:
                        try:
                            entry = await self.fetch_entry(accession)
                            results.append(extract_protein_info(accession, entry))
                        except httpx.HTTPError as e:
                            results.append(
                                {
                                    "accession": accession,
                                    "error": f"Failed to fetch data: {str(e)}",
                                }
                            )

                    return self._as_json(results)

                elif name == "search_proteins":
                    query = arguments.get("query")
                    if not query:
                        raise ValueError("A query is required")

                    hits = await self.search(
                        query=query,
                        organism_id=arguments.get("organism_id"),
                        reviewed_only=arguments.get("reviewed_only", True),
                        limit=arguments.get("limit", 10),
                    )
                    return self._as_json({"count": len(hits), "results": hits})

                elif name == "get_protein_features":
                    accession = self._require_accession(arguments)
                    entry = await self.fetch_entry(accession)
                    return self._as_json(
                        extract_features(
                            accession,
                            entry,
                            types=arguments.get("types"),
                            include_secondary_structure=arguments.get(
                                "include_secondary_structure", False
                            ),
                        )
                    )

                elif name == "get_protein_structures":
                    accession = self._require_accession(arguments)
                    entry = await self.fetch_entry(accession)
                    return self._as_json(extract_structures(accession, entry))

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
            except ValueError as e:
                logger.error(f"Invalid request: {str(e)}")
                return [TextContent(type="text", text=f"Invalid request: {str(e)}")]
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=f"An unexpected error occurred: {str(e)}",
                    )
                ]

    @staticmethod
    def _require_accession(arguments: dict[str, Any]) -> str:
        """Read the accession argument or say which one is missing."""
        accession = arguments.get("accession")
        if not accession:
            raise ValueError("Accession No. is required")
        return str(accession)

    @staticmethod
    def _as_json(payload: Any) -> Sequence[TextContent]:
        """Render a tool result as the single text block MCP expects."""
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

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
