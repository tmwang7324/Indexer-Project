# 12 · Legacy pipeline coexistence

**Slice:** the old shell pipeline loads into its own `legacy` schema, next to the new indexer's `indexer` schema, reading the same database settings. It also accepts Terra blocks, and its line-5 fixer only touches a block whose schema error is about line 5.

**Acceptance test (Integration):** `I10`: run `load_transactions.sh` on the Migaloo fixtures with the schema set to `legacy`, while the `indexer` schema holds indexed data. The legacy tables fill, the `indexer` schema is unchanged (row counts and a checksum), and the 27 legacy tests pass against `postgres-test`.

**Depends on:** 01 · **Decisions:** D8, D9, D11, D13

## Scope
- **In:**
  - a schema setting for the old scripts (`db_schema` in `info.json`, or `INDEXER_DB_SCHEMA`), applied as the connection's `search_path`, and through `PGOPTIONS` for the `psql` call that runs `Txs.sql`;
  - database settings read from environment variables when present (D13);
  - generalizing `sdk_block.header.proposer_address` in `Validate_json` to any chain's validator consensus address, instead of exactly 53 characters;
  - the line-5 fixer deleting only when the error's path (`ValidationError.absolute_path`) is `block_id.part_set_header.total`.
- **Out:** the speed comparison (14).

## Spec
- **Default:** with no schema setting, the old scripts behave exactly as today (`public` schema), so existing setups keep working.
- **Decode endpoints:** the old pipeline's decode endpoint list becomes overridable by environment variable. Ticket 14 needs this to point it at a local fake; the default is unchanged.

## Acceptance criteria
- [ ] Legacy load into `legacy` leaves the `indexer` schema untouched.
- [ ] A real Terra block file passes `check_one_file.py`.
- [ ] A block failing the schema for an unrelated reason exits 8 and the file is unchanged; a block whose line 5 has a malformed `total` loses only line 5.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I10 | integration | legacy load into `legacy`; `indexer` schema unchanged |
| legacy `CheckOneFileTest` | legacy | cases added: Terra block passes; unrelated schema failure leaves the file unchanged |
