# 06 · In-transaction verification and `failed_blocks`

**Slice:** before each block commits, its counts are checked against the source. A mismatch rolls the whole block back and records it in `failed_blocks`. A sampled `verify` command compares stored blocks field by field.

**Acceptance test (Integration):** `I1[count_mismatch]`: a replay-cache block whose `block_results` has one fewer result than the block has transactions leaves **no rows**, a `failed_blocks` row with the reason, and the next block still indexes.

**Depends on:** 04 · **Decisions:** D14

## Scope
- **In:**
  - `failed_blocks(chain_id, height, error, attempts, last_tried)` migration;
  - count rules: transactions written = block transaction count, outcomes = `txs_results` count, messages = sum of each transaction's messages;
  - the checks run inside the block's transaction, before `COMMIT`;
  - the `python -m indexer verify --sample N` command.
- **Out:** retries (09).

## Spec
- **Count rules:** a pure function `check_counts(source_summary, written_summary) -> list[Mismatch]`. The writer queries what it wrote in the open transaction and calls it.
- **On mismatch:** `ROLLBACK`, then insert or update the `failed_blocks` row in a separate short transaction.
- **`verify`:**
  - picks N stored heights at random (seeded, seed printed);
  - re-reads them from the configured source (the replay cache by default);
  - compares every stored field, and prints each difference as `height / table / column: stored != source`;
  - exits non-zero if any difference is found.

## Acceptance criteria
- [x] A count mismatch leaves no rows for that block and records the reason.
- [x] `verify` reports a field changed by hand in the database, and exits 0 when nothing differs.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I1 | integration | count mismatch rolls back into `failed_blocks` |
| C4 | component | clean block; missing tx; duplicate tx; missing outcome; wrong message count |
| C5 | component | one changed field in a block, a transaction, a message |
| U10 | unit | match; missing tx; extra tx; missing outcome; wrong message count |
