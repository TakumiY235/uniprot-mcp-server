"""Tests for the UniProt MCP Server."""

import json
from pathlib import Path
from typing import Any

import pytest

from uniprot_mcp_server.server import (
    Cache,
    UniProtServer,
    build_search_query,
    extract_features,
    extract_protein_info,
    extract_search_hit,
    extract_structures,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def pla2_entry() -> dict[str, Any]:
    """A real UniProtKB entry (P04054, human PLA2G1B), trimmed to what we read.

    Keeps the extractor tests offline, and pins the response shape we parse so
    a change on UniProt's side shows up as a test failure rather than as
    "Unknown" in a tool result.
    """
    with open(FIXTURE_DIR / "P04054.json", encoding="utf-8") as handle:
        entry: dict[str, Any] = json.load(handle)
    return entry


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


def test_extract_protein_info(pla2_entry: dict[str, Any]) -> None:
    """Protein info is projected from the fields UniProt actually returns."""
    info = extract_protein_info("P04054", pla2_entry)
    assert info["accession"] == "P04054"
    assert info["protein_name"] == "Phospholipase A2"
    assert info["organism"] == "Homo sapiens"
    assert info["length"] == 148
    assert len(info["sequence"]) == 148
    assert info["function"] and "phospholipid" in info["function"][0].lower()


def test_protein_name_falls_back_to_submission_name() -> None:
    """Unreviewed entries carry only a submitted name, not a recommended one."""
    entry = {
        "proteinDescription": {
            "submissionNames": [{"fullName": {"value": "Uncharacterized protein"}}]
        }
    }
    assert extract_protein_info("A0A000", entry)["protein_name"] == (
        "Uncharacterized protein"
    )


def test_protein_name_unknown_when_absent() -> None:
    """A nameless entry reports Unknown rather than raising."""
    assert extract_protein_info("A0A000", {})["protein_name"] == "Unknown"


def test_extract_features_reports_design_boundaries(
    pla2_entry: dict[str, Any],
) -> None:
    """The processing boundaries a construct has to respect are reported."""
    result = extract_features("P04054", pla2_entry)
    spans = {(f["type"], f["start"], f["end"]) for f in result["features"]}
    assert ("Signal", 1, 15) in spans
    assert ("Propeptide", 16, 22) in spans
    assert ("Chain", 23, 148) in spans
    assert result["length"] == 148
    assert result["feature_counts"]["Disulfide bond"] == 7
    assert result["feature_counts"]["Active site"] == 2


def test_extract_features_is_ordered_by_position(pla2_entry: dict[str, Any]) -> None:
    """Features come back in sequence order, whatever order UniProt listed them."""
    starts = [f["start"] for f in extract_features("P04054", pla2_entry)["features"]]
    assert starts == sorted(s or 0 for s in starts)


def test_extract_features_omits_secondary_structure(
    pla2_entry: dict[str, Any],
) -> None:
    """Helix, beta strand and turn are noise for sequence design, so excluded."""
    counts = extract_features("P04054", pla2_entry)["feature_counts"]
    assert "Helix" not in counts
    assert "Beta strand" not in counts
    assert "Turn" not in counts

    with_ss = extract_features("P04054", pla2_entry, include_secondary_structure=True)
    assert with_ss["feature_counts"]["Helix"] == 9


def test_extract_features_type_filter(pla2_entry: dict[str, Any]) -> None:
    """A type filter keeps only what was asked for, ignoring case."""
    result = extract_features("P04054", pla2_entry, types=["active site"])
    assert set(result["feature_counts"]) == {"Active site"}
    assert all(f["type"] == "Active site" for f in result["features"])


def test_extract_features_type_filter_overrides_secondary_default(
    pla2_entry: dict[str, Any],
) -> None:
    """Naming a secondary-structure type is enough to get it."""
    result = extract_features("P04054", pla2_entry, types=["Helix"])
    assert result["feature_counts"] == {"Helix": 9}


def test_extract_features_tolerates_missing_position() -> None:
    """A feature with no start sorts last instead of breaking the comparison."""
    entry = {
        "features": [
            {"type": "Region", "location": {}, "description": "unplaced"},
            {
                "type": "Chain",
                "location": {"start": {"value": 1}, "end": {"value": 10}},
                "description": "",
            },
        ]
    }
    features = extract_features("A0A000", entry)["features"]
    assert [f["type"] for f in features] == ["Chain", "Region"]
    assert features[-1]["start"] is None


def test_extract_structures(pla2_entry: dict[str, Any]) -> None:
    """PDB entries carry the method, resolution and covered residue ranges."""
    result = extract_structures("P04054", pla2_entry)
    assert result["alphafold_id"] == "P04054"
    assert [e["pdb_id"] for e in result["pdb_entries"]] == ["3ELO", "6Q42"]

    first = result["pdb_entries"][0]
    assert first["method"] == "X-ray"
    assert first["resolution"] == "1.55 A"
    assert first["chains"] == "A=16-148"


def test_extract_structures_without_any() -> None:
    """A protein with no solved structure reports empty, not an error."""
    result = extract_structures("A0A000", {"uniProtKBCrossReferences": []})
    assert result["pdb_entries"] == []
    assert result["alphafold_id"] is None


def test_extract_search_hit() -> None:
    """A search hit is projected without the sequence."""
    hit = extract_search_hit(
        {
            "primaryAccession": "P04054",
            "uniProtkbId": "PA2GA_HUMAN",
            "entryType": "UniProtKB reviewed (Swiss-Prot)",
            "proteinDescription": {
                "recommendedName": {"fullName": {"value": "Phospholipase A2"}}
            },
            "genes": [
                {"geneName": {"value": "PLA2G1B"}, "synonyms": [{"value": "PLA2"}]}
            ],
            "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
            "sequence": {"length": 148},
        }
    )
    assert hit["accession"] == "P04054"
    assert hit["entry_name"] == "PA2GA_HUMAN"
    assert hit["gene_names"] == ["PLA2G1B"]  # synonyms are not included
    assert hit["taxon_id"] == 9606
    assert hit["length"] == 148
    assert hit["reviewed"] is True


def test_extract_search_hit_unreviewed() -> None:
    """TrEMBL entries are reported as unreviewed."""
    hit = extract_search_hit({"entryType": "UniProtKB unreviewed (TrEMBL)"})
    assert hit["reviewed"] is False


@pytest.mark.parametrize(
    ("organism_id", "reviewed_only", "expected"),
    [
        (None, False, "(phospholipase A2)"),
        (9606, False, "(phospholipase A2) AND organism_id:9606"),
        (None, True, "(phospholipase A2) AND reviewed:true"),
        (9606, True, "(phospholipase A2) AND organism_id:9606 AND reviewed:true"),
    ],
)
def test_build_search_query(
    organism_id: int, reviewed_only: bool, expected: str
) -> None:
    """Filters are ANDed onto the caller's query, which stays parenthesised."""
    assert build_search_query("phospholipase A2", organism_id, reviewed_only) == (
        expected
    )
