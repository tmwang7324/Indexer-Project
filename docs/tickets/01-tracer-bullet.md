# 01 · Tracer bullet: a Migaloo block, queried through GraphQL

**Slice:** index the Migaloo test blocks from files into the new `indexer` schema, then query a block and a transaction over GraphQL. It's the thinnest path through every layer, plus the test and CI scaffolding the rest builds on.

**Acceptance test (E2E):** `E1[block_by_height, transaction_by_hash]`: start the indexer as a separate process on `test_blocks/`, then query the API over HTTP and compare with expected-JSON files.

**Depends on:** none · **Decisions:** D2, D9, D12, D13, D15, D17, D18, D19, D20, D23, D25

## Scope
- **In:**
  - Alembic setup and a first migration in schema `indexer`: `blocks`, `transactions`, `messages` (raw JSONB, `msg_index`, `UNIQUE (tx_id, msg_index)`), and `checkpoints` (table only).
  - Numeric columns as `BIGINT`/`NUMERIC` (5.4).
  - Files source, parser, synchronous writer (one database transaction per block).
  - Decoded transactions come from the saved fixtures; Migaloo is raw-only (D12).
  - API with `block(chainId, height)` and `transaction(hash)`, bound to 127.0.0.1.
  - Test scaffolding: pytest with markers, Compose `postgres-test`, and the invariant checker (only "stored once, no partial blocks" for now).
  - CI workflow running every layer with the coverage floors.
- **Out:** typed tables, addresses, outcomes, Terra, threads, verification.

## Spec
- `python -m indexer run --source files:test_blocks` indexes every block file that has a decoded fixture. Until ticket 15 adds local decoding (D26), other files are reported and skipped.
- **Writer:** each insert takes a cursor and never commits; `write_block()` does `BEGIN … COMMIT` around a whole block. Inserts use `ON CONFLICT DO NOTHING`, then look up the existing id when no row is returned.
- **Transaction hash:** SHA-256 of the raw bytes, uppercase hex (as `hash_to_hex` does today).
- **pytest:**
  - markers `unit`, `component`, `integration`, `e2e`, `slow`, `legacy`; the legacy tests in `tests/` are marked `legacy`;
  - `--import-mode=importlib`, so test file names may repeat across layer folders;
  - database fixtures: session-scoped `alembic upgrade head`; component tests are rolled back; integration and end-to-end tests are truncated afterwards (D20);
  - **fail, don't skip**, if `postgres-test` isn't reachable (D19).
- **Compose:** a `postgres-test` service (PostgreSQL 16, port bound to 127.0.0.1, tmpfs data).
- **CI:** GitHub Actions on every push and pull request, with PostgreSQL 16 as a service container; runs all markers, plus `coverage report --include=<critical> --fail-under=90` and `--cov-fail-under=80`.

## Acceptance criteria
- [ ] Indexing `test_blocks/` twice leaves the same rows (idempotent).
- [ ] `block(chainId: "migaloo-1", height: 7027410)` returns the hash, time and 3 transactions.
- [ ] `transaction(hash: "E77D14CB…5C20")` returns the vote transaction, with its memo, fee and 1 message.
- [ ] CI runs on push and fails when any test or coverage floor fails.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| E1 | e2e | `block_by_height`, `transaction_by_hash` |
| I1 | integration | valid block commits |
| C1 | component | upgrade, downgrade, upgrade |
| C2 | component | block, transaction, `messages` row |
| U1 | unit | Migaloo block, empty block, multi-message transaction |
| U2 | unit | known transaction → known hash |
