# 07 · Checkpoint and resume

**Slice:** the indexer records the highest contiguous height it has fully stored, and a restart resumes from there without gaps or duplicates (single worker).

**Acceptance test (Integration):** `I6[sync]`: index part of the curated sample, kill the process (a `before_commit` hook raises `SystemExit` on a chosen height), restart, and finish. Every block is stored once, and the checkpoint equals the last height.

**Depends on:** 06 · **Decisions:** D7 (checkpoint design in 5.2)

## Scope
- **In:**
  - `checkpoints(chain_id, contiguous_height)`, updated in the same transaction as the block that extends it;
  - start-height resolution: the checkpoint + 1, otherwise `--from-height`;
  - skipping heights that already have a `blocks` row;
  - writer hook points (`before_commit(height)`, `after_commit(height)`); production passes none (D22);
  - the invariant checker gains "checkpoint = highest contiguous height".
- **Out:** threads (08). A failed height blocking the checkpoint is tested in 09.

## Spec
- **Advancing the checkpoint:** a block at height H moves the checkpoint only if the checkpoint is H − 1. Out-of-order arrivals are handled in 08; this ticket is sequential.
- **Restart:** re-reading a height that is already stored is harmless (idempotent inserts), but it is skipped for speed.

## Acceptance criteria
- [x] Kill at any height, restart: every block is stored once and the checkpoint is correct.
- [x] Restarting a finished run does nothing and exits 0.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I6 | integration | crash then restart, single worker |
| C2 | component | checkpoint (written twice → one row) |
| U6 | unit | nothing done; in order; a gap; the gap filled |
