# 04 · Terra blocks from the replay cache, with outcomes and events

**Slice:** index Terra (`phoenix-1`) blocks from the replay cache: the `txs/block` and `block_results` responses, gzipped. Each transaction gets its outcome (`code`, `codespace`, `gas_wanted`, `gas_used`, `log`), its events as JSONB and all its fee coins. GraphQL shows whether a transaction failed.

**Acceptance test (E2E):** `E1[failed_transaction]`: index the curated Terra sample from the replay cache, then query a known failed transaction and get a non-zero `code`, its `log` and its events.

**Depends on:** 01 · **Decisions:** D4, D5, D6, D24

## Scope
- **In:**
  - the replay-cache source, reading gzipped response pairs from a folder;
  - the parser for the `txs/block` response shape;
  - matching transactions to outcomes by position;
  - a migration adding the outcome columns, an `events` JSONB column and `transaction_fees(tx_id, denom, amount NUMERIC)`;
  - the **curated sample**: about 50 hand-picked Terra blocks, roughly 1 MB, committed under `tests/indexer/data/terra/`. It must include empty blocks, multi-message transactions, a failed transaction and a multi-coin fee if one can be found;
  - a one-off `tools/curate_sample.py` that picks the blocks from a local cache.
- **Out:** fetching from live nodes (05) and verification of counts (06). Here a count disagreement is just an error.

## Spec
- **Replay cache layout:** `<dir>/<chain_id>/<height>.txs.json.gz` and `<height>.results.json.gz`, holding the raw response bytes unchanged.
- **No protobuf on this path (D6):** transactions arrive decoded; the hash is computed from `block.data.txs`; the base64 `data` field is not stored.
- **Pagination:** a `txs/block` response with `pagination.next_key` set needs its follow-up pages, which are cached as `<height>.txs.<n>.json.gz`.

## Acceptance criteria
- [ ] Every curated block indexes; failed transactions have a non-zero `code` and their `log`.
- [ ] A transaction with several fee coins stores every coin.
- [ ] An amount larger than 64 bits is stored exactly.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| E1 | e2e | `failed_transaction` |
| C2 | component | outcome and events, fee coins |
| C3 | component | 2^64 + 1 stored exactly |
| U1 | unit | Terra block |
| U3 | unit | counts agree; one result missing |
| U11 | unit | write then read gives the same bytes |
