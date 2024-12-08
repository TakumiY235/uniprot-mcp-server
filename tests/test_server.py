"""Tests for the UniProt MCP Server."""

import pytest

from uniprot_mcp_server.server import Cache, UniProtServer


def test_cache_initialization() -> None:
    """Test cache initialization with default values."""
    cache = Cache()
    assert cache.max_size == 100
    assert len(cache.cache) == 0


@pytest.mark.asyncio
async def test_server_initialization() -> None:
    """Test server initialization."""
    server = UniProtServer()
    assert server is not None
    assert server.cache is not None


def test_cache_set_get() -> None:
    """Test cache set and get operations."""
    cache = Cache()
    cache.set("test_key", "test_value")
    assert cache.get("test_key") == "test_value"
    assert cache.get("non_existent_key") is None


def test_cache_max_size() -> None:
    """Test cache respects max size limit."""
    cache = Cache(max_size=2)
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")  # This should remove key1
    assert cache.get("key1") is None
    assert cache.get("key2") == "value2"
    assert cache.get("key3") == "value3"
