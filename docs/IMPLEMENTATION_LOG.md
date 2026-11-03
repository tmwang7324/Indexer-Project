# Implementation log

One entry per **implementation wave**: a batch of work delivered together (one or more tickets, or a change of similar size). Each entry records three things, so the reasoning survives the code:

1. **Problems faced**: what went wrong or was harder than expected, including our own mistakes, and how it was resolved.
2. **Key decisions**: what was chosen, over what, and why. Decisions that change `REVAMP.md` section 7 are also recorded there.
3. **Testing strategy and standards**: how the work was tested, which standards were applied, and the numbers that show it (tests, coverage, mutation checks, manual checks that are not part of the suite).

Newest last. See `CLAUDE.md` for the rule, and the template at the end of this file.

---

## Wave 1 · Tickets 01 to 05 (commits `e5adf30` to `efb248c`)
Tracer bullet, typed messages, addresses, Terra from the replay cache, record from live nodes.

### Problems faced
- **Legacy tests collide with the new schema.** The old scripts create unqualified tables, and with a database user called `indexer` they land in the `indexer` schema (the user's schema is first on the default `search_path`), so 11 legacy tests failed against the shared test database. Worked around by giving the legacy tests their own database in CI and the README; the real fix is ticket 12 (`legacy` schema, D9).
- **A passing test that proved nothing.** The first version of the fake-node test (I8) still passed with the endpoint cool-down removed, and with the rate limiter removed it failed at an unrelated assertion. A deliberate breakage check found both; the test now asserts arrival times (an endpoint is left alone for the whole cool-down) and checks the rate limit before the rotation.
- **A real bug found by a test.** Waiting for a cool-down used up one of a block's fetch attempts, so a block could fail while an endpoint was about to recover. Fixed in the code (`_attempts()` generator), not in the test.
- **Slips of mine, caught before they did harm.** `.coverage` was committed by `git add -A` (untracked and ignored afterwards); a one-line script opened `errors.py` for writing before reading it and emptied it (restored from a backup).
- **Test plumbing.** In pytest's `importlib` mode, test files cannot import each other, so shared helpers live in `tests/indexer_support/`; Alembic needed `prepend_sys_path`; the local PostgreSQL stops between turns in this environment and has to be restarted.
- **Data limits.** About 4,500 recent Terra blocks contained no multi-coin fee, so that case uses a hand-made test. Only the 4 message types present in the Migaloo fixtures use real messages in the handler tests; the other 31 are hand-written (D24).

### Key decisions
- Handlers are declarative (table, column-to-path map, address fields) and grouped by module family, instead of one module per type; each is still a pure function from message JSON to a result. The registry refuses to start if `type.json` and the handlers disagree.
- Typed rows keep address values as text and the shared `address` table is linked through `message_addresses`; empty addresses are not linked; IBC `signer` addresses are linked.
- 35 typed tables plus 2 side tables; large blobs (IBC proofs, client headers, wasm byte code) stay only in `messages.raw`.
- `Message.details` is a JSON object, not a union of 35 GraphQL types; lists take a `limit` until cursor paging (ticket 11).
- Every fee coin goes into `transaction_fees` (`NUMERIC`); outcome columns are NULL when a source has no outcome.
- The REST source rotates endpoints with a cool-down, rate-limits per endpoint with a shared token bucket, and puts a timeout on every request; recording never alters the bytes.
- The only HTTP server tests use is the local fake node; nothing in the suite calls a public node (D25). Live checks were done by hand, once.
- Full list of deviations from the tickets: `REVAMP.md` section 9.

### Testing strategy and standards
- Layers by marker (`unit`, `component`, `integration`, `e2e`, `legacy`); each behaviour tested once, at the lowest layer that can prove it (rulebook rule 1); repeated shapes parametrised (35 handler cases, 35 schema-contract cases).
- Database layers **fail, never skip**, when the test database is missing; component tests roll back, integration and end-to-end tests truncate.
- One shared invariant checker ends every integration test (heights stored once, no partial blocks, every handled message has its typed row); `snapshot()` compares whole database contents with ids replaced by natural keys.
- Expected-JSON and handler golden files are regenerated only with `--update-golden` and were reviewed by hand against the inputs.
- Result at the end of the wave: 152 tests in the coverage run (unit, component, integration), 5 end-to-end, the 27 legacy tests. Coverage 97% overall (floor 80) and 99% on the critical modules (floor 90), run with the exact CI commands against a fresh database. The GitHub Actions workflow itself has not been seen running.
- Breakage checks: the rate limiter and the cool-down were removed in turn to confirm I8 fails for the right reason.
- Manual checks, outside the suite: REST source against the real publicnode endpoints (10 blocks fetched, recorded, replayed).

---

## Wave 2 · In-order prefetch and the ticket 16 spec (commits `06e6b3a`, `28f30b6`; the prefetch was reverted in wave 3)
Fetch several blocks at once but write them in height order; write the spec for fewer requests per block.

### Problems faced
- **Wrong assumptions about the nodes, corrected by measuring.** Earlier I said JSON-RPC batches of 5 worked; the real limit on publicnode is 10. `/blockchain` returns the *highest* 20 blocks of a range in descending order, so a wider range silently drops the older ones.
- **Environment.** PostgreSQL went down twice between turns; tests that need it errored with "connection refused" until it was restarted.
- **A concurrency test without sleeps needed new tooling.** The fake node got per-height gates and a condition variable so a test can hold the oldest block and see what else is requested.

### Key decisions
- Keep writes strictly in height order while fetches overlap, so no checkpoint logic was needed yet (that stays with tickets 07 to 09).
- Ticket 16 (header ranges and batched results) is a separate ticket, and D27 revises D4. D27 is **proposed**, not agreed.

### Testing strategy and standards
- Concurrency tests used gates, not sleeps (rulebook rule 8): later blocks are fetched while the oldest is held, the window is bounded and slides, results equal the sequential ones, an error comes out at its own height, closing early stops the workers. Repeated three times to look for flakiness.
- Measured live, 40 blocks, default limits: 2.1 blocks/s with one block in flight, 4.0 with four, 5.2 with eight, which is the rate-limit ceiling.

---

## Wave 3 · Keep the single-threaded pipeline as a baseline, and this log (the revert `318dce7` and the commit after it)
Reverted the prefetch; recorded the single-threaded pipeline as the reference for the final benchmark; added the rule that every wave gets an entry here.

### Problems faced
- **My earlier throughput projection was too high.** I estimated about 300 blocks/s offline by combining separately timed stages; the end-to-end run measures about 210. Corrected in `docs/benchmarks/single-threaded-baseline.md`; the gap is not investigated.
- **Two slips of mine, both caught before the push.** The revert's commit message contained a full commit hash I had written from memory and it was wrong (amended); a text replacement in ticket 16 swallowed the neighbouring "Empty block" bullet because the sentence ended at a line break (found by reading the diff, restored). Lesson applied: read the diff of every scripted edit.
- **The tag could not be pushed.** The branch push worked, but five attempts to push the tag `benchmark/single-threaded-baseline` all ended with "the remote end hung up" while the proxy reported no denial; I take it that the cloud session's git access accepts only the designated branch, and did not try to route around it. Because the container is ephemeral, a local tag would be lost, so the docs name the commit `3d34de0` instead (it is on the pushed branch); the tag can be pushed from a normal clone.
- **The first replay run was slower (132 blocks/s)** because the disk cache was cold, so the baseline reports three runs and says so.

### Key decisions
- Revert with `git revert` (history kept, nothing rewritten on the pushed branch) and keep the old code reachable by commit hash (`3d34de0`), with `tools/bench_single_threaded.py`.
- The final benchmark (ticket 14) has three contenders: the old pipeline, this baseline and the multi-threaded pipeline. It runs the baseline from a worktree of that commit with a scratch database migrated by that commit's own migrations, so later schema changes cannot break it.
- Ticket 16 no longer refers to a prefetch; it requires the range planner to be thread-safe instead.

### Testing strategy and standards
- After the revert, the whole CI sequence was run again on the reverted tree: same results as before the prefetch (152 + 5 tests, coverage 97% and 99%).
- Baseline numbers come from repeated runs (3 offline on 4,484 blocks, 3 offline on the 50-block sample, 3 live of 60 blocks each), with environment recorded.
- The benchmark tool is a tool, not a test (D25): its live mode uses the network and is never run in CI.

---

## Wave 4 · Tickets 06 to 10: verification, checkpoint and resume, worker threads, error handling, catch up then follow (commits `8e18ae8`, `fa71e63`, `5267a35`, `a15be0c`, `9bb28d4`)
Blocks are checked before they commit, a restart resumes from a contiguous checkpoint, N threads give the same rows as one, errors are classified and shutdown is orderly, and a live run catches up and then follows the head.

### Problems faced
- **PostgreSQL rounds nanoseconds, it does not truncate.** The first version of `verify` reported a false difference on every timestamp ending in 5 at the 7th digit. The test "all 50 sample blocks verify clean" found it; `verify` now rounds half up like the database. REVAMP.md section 9 had said only "microsecond precision".
- **My own test hook deadlocked, intermittently.** The crash-between-commits test made block 1006 wait inside `before_commit` for 1004 and 1005. By then 1006 held the checkpoint row's lock, so those two could not commit. It passed whenever 1005 happened to commit first, failed once with "gate never released", and cost 15 s per run as the symptom (34 s instead of 5 s for a few tests). I noticed the timing before the failure. Fix: wait while loading, not while holding the lock; the rule is written on `Hooks`. A second small cause: aborting did not wake the held worker. Six repeated runs and four more of the follow and error tests were stable afterwards.
- **The curated sample has gaps in its heights**, and a contiguous checkpoint needs a contiguous run. I added `renumbered_cache` (the real 50 blocks written as heights 1000 to 1049, only the height fields changed). It is synthetic in height only.
- **Behaviour changed under an old test.** Ticket 05's test expected exit 1 when every endpoint fails on a block. Ticket 09 says such a block goes to `failed_blocks`, so the test now expects exit 3 and a row with 5 attempts. This raised a real problem: a dead node would write a failed row for every remaining height, so I added an outage stop (10 blocks given up in a row stops the run, exit 1). That is not in the ticket.
- **Small slips of mine.** A handler dataclass holding a dict cannot be a set member (keyed by name instead). `diff_block` rolled back the caller's uncommitted data (removed). A text replace for `_rollback` did not apply and the first test run said so (`NameError`). Two lines of leftover junk were written into a test and removed before commit. During a breakage check on `retry.py` the file was untracked, so `git checkout` did not restore it; I restored the line by hand and confirmed with grep before running anything else.
- **Environment.** The background CI run used the `pytest` command, which is another interpreter (no `pytest-cov`, no `psycopg2`) and failed at once; rerun with `python -m pytest`. The legacy tests showed 11 failures until `INDEXER_TEST_DB_PASSWORD` and user were also set (the same code with a password: 27 passed). The local PostgreSQL listens on 5432, not Compose's 5433.
- **Not done:** the GitHub Actions workflow has still not been seen running; CI here is the same commands run locally on Python 3.13 (the workflow uses 3.12).

### Key decisions
- **The checkpoint is computed by the database, inside the block's transaction**, instead of by an in-memory tracker (a recursive query from the checkpoint through the stored `blocks` rows, under a row lock). A tracker would need locking against the writes and a final flush, and could be ahead of the data after a crash; this cannot. Cost: serialised commits at the very end of each transaction. Consequence: U6 became a component test. D7's rule is unchanged.
- Sources expose `items()` (height known before loading), so failures are recorded against a height; one pipeline serves 1 to N workers (same code path, so "1 worker vs 8" really compares the same thing).
- Retry policy in one small module (`retry.py`): classification, doubling delay, stop-aware sleep. Bad data is never retried; a bug stops the run; exit codes 0/1/2/3 are documented in the README.
- Follow is the default for `--source rest` without `--to-height`; `--no-follow` replaces the old default. A pruned height (HTTP 500 or JSON-RPC error saying "lowest height ... is not available") is not a fault of the endpoint, so the next endpoint is tried, and when every endpoint has said it the block is bad data with a retention-window message. Wording confirmed by hand against publicnode and Polkachu; their retention differs a lot (Polkachu keeps 15.60M and up, publicnode 23.08M), so rotation matters.
- No decision in REVAMP.md section 7 changed. New behaviour and deviations are in section 9 (rows for tickets 05 to 10).

### Testing strategy and standards
- Layers by folder marker as before. Unit: count rules (U10) and error policy (U8, 15 cases). Component: count check on an open transaction (C4), `verify` against all 50 sample blocks plus one changed field in a block, transaction, outcome, message, typed row and a missing row (C5), checkpoint cases (C2, U6). Integration: failed blocks (I1), verify command, crash and resume incl. out of order (I6), 1 vs 8 workers and a held block (I2, I3), the six error cases (I4), a crash while another worker waits to commit (I5), seeded stress with 6 rounds (I7, marked slow), catch up then follow, restart while following, start rule, pruned heights, SIGTERM on a real subprocess (I9).
- Rulebook standards kept: gates and events instead of sleeps for ordering (the stress test uses tiny random sleeps by design); every integration test ends with the invariant checker, which now also checks failed vs stored, checkpoint, returned connections and ended threads; the only HTTP server is the local fake node (D25).
- Numbers (local, exact CI commands, fresh run at the end): **232** tests in the coverage run (unit, component, integration), **5** end-to-end, **27** legacy (with the database password set). Coverage **95.5%** overall (floor 80) and **98%** on the critical modules (floor 90); `pipeline.py` 99%, `checkpoint.py` and `retry.py` 100%, `run.py` 88%, `verify.py` 94%.
- Breakage checks: removing the count check makes the writer-mismatch test fail; making the checkpoint ignore gaps fails the gap test; removing `OperationalError` from the transient class fails the dropped-connection test. One mutation survived by design: always passing `broken=False` for a connection that raised changes nothing, because the pool also closes a connection that reports itself closed.
- Repeated runs for flakiness: the order-dependent tests were run 6 times in a row, the follow and error tests 4 times, no failures after the deadlock fix.
- Manual checks outside the suite (2026-11-03): pruned-height responses from publicnode and Polkachu; a live follow run against the real nodes for 40 s with 2 workers (it resumed at the checkpoint left by a first short run, indexed 7 blocks, every new block within about 2 s of appearing, stopped on SIGTERM with the message "stopped: 7 blocks indexed" and exit 124 from `timeout`, i.e. the process exit code was not captured). Not checked: a long live run, memory growth, many hours of following.
- Known rough edge: the "caught up" line is logged after every new block while following; it is noisy and could be quieter.

---

## Template
```
## Wave N · <what was delivered> (commits <first> to <last>)
<one line>

### Problems faced
- <what went wrong or was hard, including our own mistakes, and how it was resolved>

### Key decisions
- <what was chosen, over what, why; mention REVAMP.md if a decision changed>

### Testing strategy and standards
- <layers and markers used, what each new test proves, standards applied>
- <numbers: tests, coverage vs floors, breakage checks, manual checks outside the suite>
```
