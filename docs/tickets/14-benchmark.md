# 14 · Old-vs-new benchmark command

**Slice:** one command prepares a set of Terra blocks for both pipelines, runs each into its own schema, and writes a report: blocks/s, tx/s, and whether both schemas hold the same blocks, transactions and messages (D10). It's a tool, not a test (D25), but the tool itself is tested.

**Acceptance test (Integration):** `I11`: run the benchmark command on a **5-block** slice of the curated sample, with both pipelines pointed at local fakes: the replay cache for the new indexer, and a fake decode endpoint (ticket 12's override) for the old one. The report file exists, lists both pipelines' throughput, and shows matching block, transaction and message counts.

**Depends on:** 04, 12 · **Decisions:** D9, D10

## Scope
- **In:**
  - `python -m indexer bench --heights A:B --prepare`, which:
    - records the new indexer's responses into the replay cache;
    - fetches `/cosmos/base/tendermint/v1beta1/blocks/{h}` (with `sdk_block`) as old-format files;
  - `python -m indexer bench --heights A:B`, which runs both pipelines and writes `bench/report-<date>.md` (git-ignored);
  - the parity check (counts per height, both schemas).
- **Out:** making the old pipeline faster; it is measured as it is.

## Spec
- **The real run:** about 1,000 consecutive Terra blocks; it uses the network and runs by hand, never in CI.
- **The report** states that the old pipeline's time includes 2 HTTP decode calls per transaction, and that the new indexer's figure comes from the replay cache, so the two are labelled rather than presented as like-for-like.

## Acceptance criteria
- [ ] The 5-block hermetic run produces a report with throughput for both pipelines and a parity result.
- [ ] A parity mismatch is reported per height and makes the command exit non-zero.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I11 | integration | 5-block hermetic benchmark with fakes; parity mismatch exits non-zero |
