# 10 · Catch up, then follow the head

**Slice:** on first start the indexer begins 25,000 blocks below the chain head (configurable) and works upward. Once caught up, the same workers wait for new blocks and index them as they appear: one ascending stream with no gap (D16).

**Acceptance test (Integration):** `I9`: against the fake node from 05, with a **scripted head**: the head starts at height S + 20, and the test advances it by one block at a time. The indexer starts with `--from-height S`, stores S … S + 20, then each new block shortly after the head advances. The checkpoint equals the head, the invariant checker passes, and SIGTERM stops it cleanly.

**Depends on:** 05, 09 · **Decisions:** D3, D16

## Scope
- **In:**
  - start-height rule: the checkpoint + 1; otherwise `--from-height`; otherwise head − 25,000 (D3);
  - head polling via `blocks/latest` at a configurable interval;
  - the switch from catching up to following;
  - a log line with the lag (head − checkpoint).
- **Out:** reorg handling (CometBFT has instant finality, so blocks don't change once committed).

## Spec
- **Catch-up:** the producer hands out heights up to the last known head. When the queue is empty, it polls the head and adds new heights as they appear.
- **Polling:** the interval defaults to the block time (about 6 s on Terra), and is shortened in tests.
- **Retention edge case:** a height below the node's retention window (e.g. publicnode's ~2 months) returns an error. That's bad data from the node's side; it is recorded in `failed_blocks` with a clear message, not retried forever.

## Acceptance criteria
- [ ] Starting with no checkpoint and no `--from-height` begins at head − 25,000 (checked against the fake node's head).
- [ ] After catching up, each new head block is stored within a couple of polling intervals.
- [ ] A restart while following resumes from the checkpoint without gaps.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I9 | integration | catch up from S to S + 20, then follow 5 new blocks; restart while following |
