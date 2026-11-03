# 14 · Old-vs-new benchmark command

**Slice:** one command prepares a set of Terra blocks for the pipelines, runs each into its own schema, and writes a report: blocks/s, tx/s, and whether the schemas hold the same blocks, transactions and messages (D10). There are three contenders: the **old pipeline**, the **single-threaded baseline** (the first version of the new indexer, kept on purpose), and the **revamped multi-threaded pipeline** with its queued prefetch (tickets 07 to 10). It's a tool, not a test (D25), but the tool itself is tested.

**Acceptance test (Integration):** `I11`: run the benchmark command on a **5-block** slice of the curated sample, with both pipelines pointed at local fakes: the replay cache for the new indexer, and a fake decode endpoint (ticket 12's override) for the old one. The report file exists, lists both pipelines' throughput, and shows matching block, transaction and message counts.

**Depends on:** 04, 12 (and 08, 10 for the multi-threaded pipeline to compare) · **Decisions:** D9, D10

## Scope
- **In:**
  - `python -m indexer bench --heights A:B --prepare`, which:
    - records the new indexer's responses into the replay cache;
    - fetches `/cosmos/base/tendermint/v1beta1/blocks/{h}` (with `sdk_block`) as old-format files;
  - `python -m indexer bench --heights A:B`, which runs both pipelines and writes `bench/report-<date>.md` (git-ignored);
  - the parity check (counts per height, both schemas).
- **Out:** making the old pipeline faster; it is measured as it is.

## The single-threaded baseline
The new indexer as of tickets 01 to 05 fetches or reads one block, writes it, and only then moves to the next. It is kept as a reference so the final comparison shows what threads, the queue and (ticket 16) fewer requests bought.
- **Where it lives:** git tag `benchmark/single-threaded-baseline`, with `tools/bench_single_threaded.py`, which prints one JSON line per run. The report is regenerated from that tag; the tag is never moved.
- **How `bench` runs it:** it checks the tag out into a temporary `git worktree`, creates a scratch database, migrates it with the tag's own migrations (so later schema changes cannot break it), runs the tool there on the same blocks, and parses the JSON line.
- **Numbers already taken** (2026-11-03, local PostgreSQL 16, this container) are in `docs/benchmarks/single-threaded-baseline.md`: about 210 blocks/s offline (replay of 4,484 blocks) and 2.2 to 2.5 blocks/s live with the default rate limits. The final report repeats the runs on the day, because live figures depend on the network.
- **What is compared:** offline, all three on the same replay cache; live, the baseline and the revamped pipeline on the same heights with the same endpoint limits. The old pipeline stays labelled as in the Spec below.
- **In the hermetic test (I11)** the baseline is a stub script chosen with `--baseline-cmd`, so the test needs neither the tag nor git history.

## Spec
- **The real run:** about 1,000 consecutive Terra blocks; it uses the network and runs by hand, never in CI.
- **The report** states that the old pipeline's time includes 2 HTTP decode calls per transaction, and that the new indexer's figure comes from the replay cache, so the two are labelled rather than presented as like-for-like.

## Acceptance criteria
- [ ] The 5-block hermetic run produces a report with throughput for the pipelines (the baseline through the stub) and a parity result.
- [ ] A parity mismatch is reported per height and makes the command exit non-zero.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I11 | integration | 5-block hermetic benchmark with fakes and a stub baseline; parity mismatch exits non-zero |
