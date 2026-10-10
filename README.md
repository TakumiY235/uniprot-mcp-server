[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/takumiy235-uniprot-mcp-server-badge.png)](https://mseep.ai/app/takumiy235-uniprot-mcp-server)

# UniProt MCP Server

A Model Context Protocol (MCP) server that provides access to UniProt protein information. This server allows AI assistants to fetch protein function and sequence information directly from UniProt.

<a href="https://glama.ai/mcp/servers/ttjbai3lpx">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/ttjbai3lpx/badge" alt="UniProt Server MCP server" />
</a>

## Features

- Search UniProtKB by protein name, gene name or keyword when the accession
  number is not known yet
- Get protein information by UniProt accession number
- Batch retrieval of multiple proteins
- Get annotated sequence features with their positions: signal peptide,
  propeptide, mature chain, active and binding sites, disulfide bonds, domains,
  glycosylation, natural variants and mutagenesis
- Get the available structures: PDB entries with method, resolution and covered
  residue ranges, plus the AlphaFold DB model
- Caching for improved performance (24-hour TTL), shared across the tools that
  read the same entry
- Error handling and logging

## Requirements

- Python 3.10 or higher
- MCP Python SDK **1.x** (`mcp>=1.1,<2`)

> The MCP SDK's 2.0 release removed the `@server.list_tools()` / `@server.call_tool()`
> decorators from the low-level `Server` class that this project is built on. Installed
> against `mcp` 2.x, the server raises
> `AttributeError: 'Server' object has no attribute 'list_tools'` at startup, so the
> dependency is pinned to the 1.x line. Migrating to the 2.x server API is tracked
> separately.

## Quick Start

1. Ensure you have Python 3.10 or higher installed
2. Clone this repository:
   ```bash
   git clone https://github.com/TakumiY235/uniprot-mcp-server.git
   cd uniprot-mcp-server
   ```
3. Install dependencies:
   ```bash
   # Using uv (recommended)
   uv pip install -r requirements.txt
   
   # Or using pip
   pip install -r requirements.txt
   ```

## Configuration

Add to your Claude Desktop config file:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "uniprot": {
      "command": "uv",
      "args": ["--directory", "path/to/uniprot-mcp-server", "run", "uniprot-mcp-server"]
    }
  }
}
```

## Usage Examples

After configuring the server in Claude Desktop, you can ask questions like:

```
Can you get the protein information for UniProt accession number P98160?
```

For batch queries:

```
Can you get and compare the protein information for both P04637 and P02747?
```

When you do not have an accession number to hand:

```
Find the reviewed human phospholipase A2 entries and show me their lengths.
```

Before designing a construct or a variant panel, to get the boundaries and the
residues that have to be respected:

```
What are the signal peptide, propeptide and mature chain boundaries of P04054,
and where are its active sites and disulfide bonds?
```

To find a structure to work from:

```
Which PDB structures cover P04054, and at what resolution?
```

## API Reference

### Tools

1. `get_protein_info`
   - Get information for a single protein
   - Required parameter: `accession` (UniProt accession number)
   - Example response:
     ```json
     {
       "accession": "P12345",
       "protein_name": "Example protein",
       "function": ["Description of protein function"],
       "sequence": "MLTVX...",
       "length": 123,
       "organism": "Homo sapiens"
     }
     ```

2. `get_batch_protein_info`
   - Get information for multiple proteins
   - Required parameter: `accessions` (array of UniProt accession numbers)
   - Returns an array of protein information objects
   - A lookup that fails is reported per accession, so one bad entry does not
     lose the rest of the batch

3. `search_proteins`
   - Find entries when the accession number is not known yet
   - Required parameter: `query` (search terms; UniProt query syntax is accepted,
     e.g. `gene:PLA2G1B`)
   - Optional: `organism_id` (NCBI taxonomy ID, e.g. `9606` for human),
     `reviewed_only` (default `true`, Swiss-Prot only), `limit` (1-50,
     default 10)
   - Sequences are not included, so a result list stays small
   - Example response:
     ```json
     {
       "count": 1,
       "results": [
         {
           "accession": "P04054",
           "entry_name": "PA2GA_HUMAN",
           "protein_name": "Phospholipase A2",
           "gene_names": ["PLA2G1B"],
           "organism": "Homo sapiens",
           "taxon_id": 9606,
           "length": 148,
           "reviewed": true
         }
       ]
     }
     ```

4. `get_protein_features`
   - Get the annotated sequence features with 1-based inclusive positions
   - Required parameter: `accession`
   - Optional: `types` (keep only these feature types, matched
     case-insensitively, e.g. `["Active site", "Disulfide bond"]`),
     `include_secondary_structure` (default `false`)
   - Secondary structure (`Helix`, `Beta strand`, `Turn`) is reported per
     element, so an entry carries dozens of them and they say nothing a
     sequence-design decision needs. They are withheld unless
     `include_secondary_structure` is set or they are named in `types`.
   - Example response:
     ```json
     {
       "accession": "P04054",
       "length": 148,
       "feature_counts": {"Signal": 1, "Propeptide": 1, "Chain": 1,
                          "Active site": 2, "Disulfide bond": 7},
       "features": [
         {"type": "Signal", "start": 1, "end": 15, "description": ""},
         {"type": "Propeptide", "start": 16, "end": 22,
          "description": "Activation peptide"},
         {"type": "Chain", "start": 23, "end": 148,
          "description": "Phospholipase A2"}
       ]
     }
     ```
   - Features are ordered by position. A feature whose position UniProt leaves
     unset reports `null` and sorts last.

5. `get_protein_structures`
   - Get the structures available for a protein
   - Required parameter: `accession`
   - Example response:
     ```json
     {
       "accession": "P04054",
       "pdb_entries": [
         {"pdb_id": "3ELO", "method": "X-ray", "resolution": "1.55 A",
          "chains": "A=16-148"},
         {"pdb_id": "6Q42", "method": "X-ray", "resolution": "1.90 A",
          "chains": "A/B=23-148"}
       ],
       "alphafold_id": "P04054"
     }
     ```
   - A protein with no solved structure reports an empty list and a null
     `alphafold_id` rather than an error

`get_protein_info`, `get_protein_features` and `get_protein_structures` read
different parts of the same UniProt entry, so they share one cached request per
accession: asking for all three costs a single round trip.

## Development

### Setting up development environment

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

### Running tests

```bash
pytest
```

### Code style

This project uses:
- Black for code formatting
- isort for import sorting
- flake8 for linting
- mypy for type checking
- bandit for security checks
- pip-audit for dependency vulnerability checks

Run all checks:
```bash
black .
isort .
flake8 .
mypy .
bandit -r src/
pip-audit .
```

## Technical Details

- Built using the MCP Python SDK
- Uses httpx for async HTTP requests
- Implements caching with 24-hour TTL using an OrderedDict-based cache
- Bounds every UniProt request with a timeout (10s connect, 30s total)
- Surfaces UniProt API errors - including 429 rate limiting - as tool errors;
  there is no automatic retry or backoff
- Provides detailed error messages

### Error Handling

The server handles various error scenarios:
- Invalid accession numbers (UniProt answers with 400, not 404)
- API connection issues (network errors)
- Rate limiting (429 responses) - reported to the caller, not retried
- Malformed responses (JSON parsing errors)
- Cache management (TTL and size limits)

## Contributing

We welcome contributions! Please feel free to submit a Pull Request. Here's how you can contribute:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please make sure to update tests as appropriate and adhere to the existing coding style.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- UniProt for providing the protein data API
- Anthropic for the Model Context Protocol specification
- Contributors who help improve this project