"""E1: one indexing run, then every GraphQL query is compared with its expected-JSON file.

Each case is queries/<name>.graphql with queries/<name>.json beside it. Regenerate the
expected files deliberately with `pytest --update-golden`, then review the diff (D24).
"""
import json
from pathlib import Path

import pytest

QUERIES = Path(__file__).parent / "queries"
CASES = sorted(p.stem for p in QUERIES.glob("*.graphql"))


@pytest.mark.parametrize("name", CASES)
def test_graphql(graphql, name, request):
    result = graphql.query((QUERIES / f"{name}.graphql").read_text())
    assert "errors" not in result, result.get("errors")
    expected_path = QUERIES / f"{name}.json"
    if request.config.getoption("--update-golden"):
        expected_path.write_text(json.dumps(result["data"], indent=2, ensure_ascii=False) + "\n")
    assert result["data"] == json.loads(expected_path.read_text())
