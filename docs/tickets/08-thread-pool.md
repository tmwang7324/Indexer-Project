# 08 · Thread pool with identical results

**Slice:** `--workers N` indexes with N threads that share one connection pool, and the result is exactly the same as with one worker, even though blocks finish out of order.

**Acceptance test (Integration):** `I2`: index the curated sample with 1 worker, dump the indexer schema (ignoring generated ids), truncate, index again with 8 workers, dump again. The two dumps are equal, and on failure the test prints the differing rows. The invariant checker passes after each run.

**Depends on:** 07 · **Decisions:** D7, D22

## Scope
- **In:**
  - a `ThreadedConnectionPool` sized to the worker count;
  - a shared height queue, and one `requests.Session` per thread;
  - out-of-order checkpoint advancement (5.2);
  - test gates in the fake and replay sources (a `threading.Event` per height);
  - `pytest-timeout` on threaded tests;
  - the invariant checker gains "every connection returned" and "every worker thread exited".
- **Out:** error handling (09).

## Spec
- **Checkpoint with out-of-order blocks:** completed heights above the checkpoint are tracked. When height `checkpoint + 1` completes, the checkpoint advances through every consecutive completed height, in the same database transaction.
- **Connections:** each block borrows a connection for its transaction and returns it in a `finally`.

## Acceptance criteria
- [x] 1 worker and 8 workers give identical rows on the curated sample.
- [x] With 103 held at its gate and 105 committed, the checkpoint stays at 102; releasing 103 (and 104) moves it to 105.
- [x] Crash between out-of-order commits, restart: no gaps, no duplicates.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I2 | integration | 1 worker vs 8 workers, row by row |
| I3 | integration | hold 103, commit 105, release |
| I6 | integration | crash between out-of-order blocks, restart (case added) |
