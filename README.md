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
- safety for dependency vulnerability checks

Run all checks:
```bash
black .
isort .
flake8 .
mypy .
bandit -r src/
safety check
```

## Technical Details

- Built using the MCP Python SDK
- Uses httpx for async HTTP requests
- Implements caching with 24-hour TTL using an OrderedDict-based cache
- Handles rate limiting and retries
- Provides detailed error messages

### Error Handling

The server handles various error scenarios:
- Invalid accession numbers (404 responses)
- API connection issues (network errors)
- Rate limiting (429 responses)
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