# Single-threaded baseline

The new indexer as built by tickets 01 to 05: it fetches or reads **one block, writes it in its own database transaction, then moves to the next**. No threads, no queue, no prefetch, one request at a time. It is kept as a performance reference. At the end of the revamp the finished multi-threaded pipeline with queued prefetches is compared with it (ticket 14).

- **Code:** commit `3d34de0`, on branch `claude/quirky-feynman-v7wozd`. Do not rewrite history before it. A tag `benchmark/single-threaded-baseline` was created on it, but the remote refused to take the tag push, so it exists only in the session that made it; to publish it from a normal clone run `git tag benchmark/single-threaded-baseline 3d34de0 && git push origin benchmark/single-threaded-baseline`.
- **Tool:** `tools/bench_single_threaded.py`, which prints one JSON line per run (blocks, transactions, messages, seconds, rates, environment, git commit).
- **Reproduce** (use a scratch database: `--reset` empties the indexer tables):

```bash
git worktree add ../baseline 3d34de0
cd ../baseline && pip install -r requirements-dev.txt
INDEXER_DB_NAME=<scratch db> alembic upgrade head
INDEXER_DB_NAME=<scratch db> python tools/bench_single_threaded.py --replay <replay cache> --reset
INDEXER_DB_NAME=<scratch db> python tools/bench_single_threaded.py --live 60 --from-height <H> --reset
```

The final comparison with the old pipeline and the finished multi-threaded pipeline is in [`final-comparison.md`](final-comparison.md).

## Results (2026-11-03)
Environment: this cloud container, Python 3.13.18, PostgreSQL 16.15 on the same machine (on-disk cluster, fsync on), one commit per block. Live runs use the default endpoint limits (publicnode and Polkachu, 5 requests/s each) and 2 requests per block.

**Offline, from a replay cache** (no network)

| Input | Run | Blocks/s | Tx/s | Msgs/s |
|---|---|---|---|---|
| 4,484 blocks (2,786 tx, 3,268 msgs) | 1 (cold disk cache) | 132 | 82 | 96 |
| | 2 | 215 | 133 | 157 |
| | 3 | 205 | 128 | 150 |
| Curated sample, 50 blocks (57 tx, 77 msgs) | 1 | 137 | 156 | 211 |
| | 2 | 142 | 162 | 219 |
| | 3 | 125 | 143 | 193 |

**Live, 60 blocks per run, distinct height ranges**

| Heights | Tx in the range | Seconds | Blocks/s |
|---|---|---|---|
| from 23,581,328 | 112 | 27.9 | 2.15 |
| from 23,579,328 | 14 | 24.8 | 2.42 |
| from 23,577,328 | 15 | 24.3 | 2.47 |

Reference points: the chain adds 0.173 blocks/s (one block every 5.77 s); the old pipeline measured 0.45 blocks/s and 0.6 tx/s on Migaloo with live decoding (a different workload, so not like for like).

## Caveats
- Live figures depend on the network and the providers at the time; repeat them on the day of the final comparison.
- The offline figure is for mostly empty Terra blocks (0.62 transactions per block). Denser blocks cost more per block.
- An earlier estimate of "about 300 blocks/s offline" was wrong. I got it by combining separately timed stages (read and parse 893 blocks/s, write 453 blocks/s); the end-to-end run, which is the real pipeline, measures about 210. The stage figures are real; I have not investigated the gap.

## The in-order prefetch experiment (reverted)
A sliding window of N blocks fetched at once and still written in height order was tried, then reverted (commit `06e6b3a`, reverted by `318dce7`; `git show 06e6b3a` has the code). Live, 40 blocks, default limits, no endpoint failures:

| Blocks in flight | Blocks/s |
|---|---|
| 1 | 2.1 |
| 4 | 4.0 |
| 8 | 5.2 |

5.2 is the rate-limit ceiling for these endpoints (2 × 5 requests/s ÷ 2 requests per block). The threaded pipeline of tickets 07 to 10 should reach at least that; going beyond it needs fewer requests per block (ticket 16) or higher limits.
