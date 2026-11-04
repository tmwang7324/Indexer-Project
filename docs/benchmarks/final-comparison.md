# Final comparison: old pipeline, single-threaded baseline, revamped pipeline

Measured 2026-11-03 with `python -m indexer bench` (ticket 14). Raw output of every run: [`final-comparison-raw.txt`](final-comparison-raw.txt).

## Setup
- **Machine:** the cloud container, 4 CPUs, 16 GB, Python 3.13.18, PostgreSQL 16.15 **on the same machine** (on-disk cluster, fsync on, one commit per block). Postgres and the contenders compete for the same 4 CPUs.
- **Workload:** 1,000 consecutive `phoenix-1` blocks, heights 23,585,000 to 23,585,999: 877 transactions, 983 messages, all of types the old pipeline knows. Prepared once with `bench --prepare` (the new indexer's responses recorded into a replay cache, plus the old-format block files from `/cosmos/base/tendermint/v1beta1/blocks/{h}`).
- **Rules:** each contender ran **alone**, one after another, in its own scratch database that was dropped afterwards. Nothing else of ours was running. Parity was checked height by height (blocks, transactions, messages) for every run that wrote rows: all matched the source.
- **The three contenders:** the **old pipeline** (`load_transactions.sh`, schema `legacy`); the **single-threaded baseline** (commit `3d34de0`, checked out into a `git worktree` and migrated with its own migrations by the bench command); the **revamped pipeline** of this tree (commit of this entry) with N workers.

## 1. Offline: everything read from the replay cache (no network)
| Contender | Blocks/s | Tx/s | Seconds for 1,000 blocks | Runs |
|---|---|---|---|---|
| Old pipeline, decode answered by a local fake | **0.80** | 0.71 | 1,243 | 1 |
| Single-threaded baseline | **239.5** (222 to 249) | 210 | 4.2 | 3 |
| Revamped, 1 worker | 150.5 (141 to 157) | 132 | 6.7 | 3 |
| Revamped, 2 workers | 232.5 (227 to 237) | 204 | 4.3 | 3 |
| Revamped, 4 workers | **261.6** (246 to 283) | 229 | 3.8 | 3 |
| Revamped, 8 workers | 249.5 (237 to 274) | 219 | 4.0 | 3 |
| Revamped, 16 workers | 226.7 (221 to 233) | 199 | 4.4 | 3 |

- Both new designs are about **300 times faster than the old pipeline** (0.80 blocks/s, which spawns Python processes for every block and every transaction and asks the decode endpoint twice per transaction).
- **The revamped pipeline barely beats the single-threaded baseline offline: at best about +9% (4 workers, 262 vs 240 blocks/s), and the ranges overlap.** One worker is 37% slower than the baseline. That gap is the price of the safety added after the baseline (tickets 06 to 09): per block an "is it stored?" query, the count check, the checkpoint update under a row lock, and the failed-block cleanup. A stack sample of one worker put the skip check, the count check and the checkpoint update at roughly a fifth of its time.
- Offline there is nothing to wait for. My reading (not separately measured) is that the limit is the 4 CPUs shared with PostgreSQL plus the Python GIL, which would explain why more than 4 workers does not help and 16 is slightly worse.

## 2. Live: blocks fetched from the public nodes (default limits: publicnode and Polkachu, 5 requests/s each, 2 requests per block)
First 300 of the same heights (665 transactions, 705 messages).

| Contender | Blocks/s | Tx/s | Seconds | Runs |
|---|---|---|---|---|
| Single-threaded baseline | 2.9 | 6.4 | 104.2 | 1 |
| Revamped, 1 worker | 2.9 | 6.3 | 104.8 | 1 |
| Revamped, 4 workers | **5.0** | 11.1 | 59.9 | 1 |
| Revamped, 8 workers | **5.0** | 11.2 | 59.6 | 2 |
| Revamped, 16 workers | **5.0** | 11.1 | 59.7 | 1 |

- Live, threads pay off: **1.7 times the baseline**. The ceiling is the rate limit, as predicted: 2 endpoints × 5 requests/s ÷ 2 requests per block = 5.0 blocks/s. Four workers already reach it; more cannot go faster. Going beyond needs fewer requests per block (ticket 16, not built) or higher limits.
- Old pipeline with its decode requests sent to the **public nodes**, on the first 40 blocks (8 transactions): 40.8 s, 1.0 blocks/s; the same 40 blocks with the local fake: 35.2 s. So the live decode calls cost it about 0.7 s per transaction on top. (A full live old-pipeline run over 300 blocks was not done; it would take about 6 minutes of mostly process start-up, and the offline run already shows its rate.)
- For reference, the chain itself adds one block every 5.8 s (0.17 blocks/s): even the old pipeline's 0.8 blocks/s keeps up with live following; the difference is how fast any of them can backfill.

## 3. A bug the benchmark found (fixed in this commit)
The first offline sweep showed the revamped pipeline getting **slower** with more workers:

| Revamped workers | 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| Blocks/s before the fix | 161 | 211 | **57** | **45** | **42** |
| Blocks/s after the fix | 151 | 233 | 262 | 250 | 227 |

Cause: `ConnectionPool` was created with `ThreadedConnectionPool(1, size)`. psycopg2 closes a returned connection when more than `minconn` are idle, so with several workers almost every block opened and closed a database connection. A thread-stack sample showed the workers spending most of their time in `putconn`, `getconn` and `psycopg2.connect`; the database showed its sessions mostly idle waiting for the client. The fix is `ThreadedConnectionPool(size, size)`. Ticket 08's tests only checked correctness (same rows as one worker), so they could not see this. A new test counts the connections opened during a 4-worker run and fails with the old setting.

## Conclusions
1. The old pipeline is about 300 times slower than either new design on the same blocks. The speed-up that matters comes from the redesign (no process per block, no per-transaction decode round trips), not from threads.
2. Threads matter when the work waits on the network: live, the revamped pipeline reaches the rate-limit ceiling of 5.0 blocks/s with 4 workers, against 2.9 for the single-threaded baseline.
3. Offline, the revamped pipeline is about as fast as the baseline (best +9%) even though it does extra work per block (the verification and checkpoint steps). It is not a clear win there, and I would not claim one.
4. The next gains: fewer requests per block (ticket 16), and, offline, fewer statements per block (for example one "which of these heights are stored" query per batch instead of one per block).

## Caveats
- One machine, one network, one day; PostgreSQL shares the 4 CPUs. Live figures depend on the providers at the time.
- The old pipeline ran once over the full range (it takes 21 minutes); the others ran 3 times offline and 1 to 2 times live. The spread across repeats is in the table.
- The workload is mostly empty or small Terra blocks (0.88 transactions per block over the 1,000; 2.2 over the first 300). Denser blocks cost more per block for every contender.
- The old pipeline's decode answers came from a local fake in the headline figure, so it is shown without public-network latency; with live decode it is slower still (section 2).
- "Parity" means counts per height against the source (blocks, transactions, messages). It is not a field-by-field comparison; `verify` does that for the new indexer.
