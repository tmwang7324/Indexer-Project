# Project notes for Claude

## Essential rule: log every implementation wave
After **every implementation wave** (a batch of work delivered together: one or more tickets, or a change of similar size), add an entry to `docs/IMPLEMENTATION_LOG.md` **before** the final summary and push. Each entry has three parts:

1. **Problems faced**: what went wrong or was harder than expected, including your own mistakes, and how it was resolved.
2. **Key decisions**: what was chosen, over what, and why. If a decision in `REVAMP.md` section 7 changes, record it there too.
3. **Testing strategy and standards**: layers and markers used, what the new tests prove, standards applied (`docs/TESTING_RULEBOOK.md`), and the numbers: tests, coverage against the floors, breakage checks, manual checks outside the suite.

Use the template at the end of the log. Report faithfully: failures, wrong estimates and slips belong in the entry, not only the good news. The same entry goes in the same push as the work.

## The single-threaded baseline is frozen
Git tag `benchmark/single-threaded-baseline` and `tools/bench_single_threaded.py` are the reference for the final performance comparison (`docs/benchmarks/single-threaded-baseline.md`, ticket 14). Never move or delete the tag.

## Working here
- Plan and decisions: `REVAMP.md`; tickets: `docs/tickets/`; test rules: `docs/TESTING_RULEBOOK.md`.
- New code: `indexer/` (service), `api/` (GraphQL), `migrations/` (hand-written SQL). The old pipeline is kept and unchanged (D8).
- Tests need PostgreSQL 16 (`docker compose up -d postgres-test`, port 5433; or point `INDEXER_TEST_DB_*` at another server). In a container without Docker, start a local cluster with `pg_ctlcluster 16 main start`; it may need restarting between turns.
- Run: `pytest -m "unit or component or integration" --cov`, `pytest -m e2e`, and the legacy tests with `INDEXER_TEST_DB_NAME=<separate database> pytest -m legacy`.
- Coverage floors: 80% overall, 90% on `indexer/writer.py`, `indexer/handlers/*`, `indexer/parse.py`, `indexer/addresses.py`.
- No test may call a public node (D25). Live checks are manual and are written down in the log.
- Golden files change only with `pytest --update-golden`, and the diff is reviewed.
- Stage explicit paths when committing; do not use `git add -A` (it once committed `.coverage`).
