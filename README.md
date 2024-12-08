# UniProt MCP Server

A Model Context Protocol (MCP) server that provides access to UniProt protein information. This server allows AI assistants to fetch protein function and sequence information directly from UniProt.

## Features

- Get protein information by UniProt accession number
- Batch retrieval of multiple proteins
- Caching for improved performance (24-hour TTL)
- Error handling and logging
- Information includes:
  - Protein name
  - Function description
  - Full sequence
  - Sequence length
  - Organism

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

[残りの内容は同じ...]