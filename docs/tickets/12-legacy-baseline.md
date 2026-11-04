# 12 · Legacy pipeline as a baseline

**Slice:** the old shell pipeline stays as a **performance baseline**. It is never run at the same time as the new indexer: it runs on its own, one contender at a time, so its timing is not disturbed by (and does not disturb) anything else. It loads into its own `legacy` schema, reading the same database settings, so its tables cannot collide with the `indexer` schema and the two results can be compared afterwards. It also accepts Terra blocks, and its line-5 fixer only touches a block whose schema error is about line 5.

**Acceptance test (Integration):** `I10`: the `indexer` schema already holds indexed data and the indexer is not running. Run `load_transactions.sh` on the Migaloo fixtures with the schema set to `legacy`. The legacy tables fill, the `indexer` schema is unchanged (row counts and a checksum), and the 27 legacy tests pass against `postgres-test`. Nothing in the test runs the two pipelines at the same time.

**Depends on:** 01 · **Decisions:** D8, D9, D11, D13

## Scope
- **In:**
  - a schema setting for the old scripts (`db_schema` in `info.json`, or `INDEXER_DB_SCHEMA`), applied as the connection's `search_path`, and through `PGOPTIONS` for the `psql` call that runs `Txs.sql`;
  - database settings read from environment variables when present (D13);
  - generalizing `sdk_block.header.proposer_address` in `Validate_json` to any chain's validator consensus address, instead of exactly 53 characters;
  - the line-5 fixer deleting only when the error's path (`ValidationError.absolute_path`) is `block_id.part_set_header.total`.
- **Out:** the speed comparison (14); running the old pipeline alongside the indexer (it is a baseline, not a second writer).

## Spec
- **One at a time:** the old pipeline is only ever run alone. The schema split is for isolation and for the parity check afterwards, not so both can run together. The README says so, and the benchmark (14) runs its contenders one after another.
- **Default:** with no schema setting, the old scripts behave exactly as today (`public` schema), so existing setups keep working.
- **Decode endpoints:** the old pipeline's decode endpoint list becomes overridable by environment variable. Ticket 14 needs this to point it at a local fake; the default is unchanged.

## Acceptance criteria
- [x] Legacy load into `legacy` leaves the `indexer` schema untouched.
- [x] The README states that the legacy loader is a baseline and must not run while the indexer is running.
- [x] A real Terra block file passes `check_one_file.py`.
- [x] A block failing the schema for an unrelated reason exits 8 and the file is unchanged; a block whose line 5 has a malformed `total` loses only line 5.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I10 | integration | legacy load into `legacy` with the indexer stopped; `indexer` schema unchanged |
| legacy `CheckOneFileTest` | legacy | cases added: Terra block passes; unrelated schema failure leaves the file unchanged |
