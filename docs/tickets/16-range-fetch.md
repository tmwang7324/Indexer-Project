# 16 · Fewer requests per block: header ranges and batched results

**Slice:** when fetching live, learn which blocks are empty from CometBFT `/blockchain` (up to 20 block headers per request) and build those blocks without any per-block request. For the blocks that do have transactions, fetch `txs/block` as before but get their `block_results` in JSON-RPC batches. On Terra most blocks are empty, so this cuts the requests per block from 2 to about 0.4 and lifts the rate-limit ceiling of a backfill from about 5 blocks/s to about 25.

**Acceptance test (Integration):** `I12`: run `python -m indexer run --source rest` against the fake node over a window of consecutive heights that mixes empty and non-empty blocks. The database rows equal those from the plain per-block path, the number of requests the node saw is exactly `1 + N + ceil(N / 10)` for `N` non-empty blocks, and a recorded cache replays to the same rows.

**Depends on:** 05 · **Decisions:** D4 and D5 (both amended by D27), D7, D14

## Why
Measured on 2026-11-02, from `terra-rpc.publicnode.com` and 4,484 recent `phoenix-1` blocks:
- 72% of blocks are empty (0.62 transactions per block overall, 2.25 per non-empty block).
- The ceiling of the REST source is `Σ(rate) / requests per block`: with the default 2 endpoints × 5 requests/s and 2 requests per block that is 5 blocks/s, and a throw-away experiment with several blocks in flight reached it (2.1 → 4.0 → 5.2 blocks/s at 1, 4 and 8 blocks in flight; see `docs/IMPLEMENTATION_LOG.md`, wave 2). More concurrency cannot go faster than that; fewer requests per block can.
- `/blockchain?minHeight=a&maxHeight=b` returns, per block, `block_id` and the full `header` plus `num_txs`. An empty block's whole row (chain, height, hash, time, zero transactions) is in it. The hash and time equal those of the full block.
- Requests per 20 blocks drop from 40 to `1 + N + ceil(N/10)`; at 28% non-empty that is about 7.5, or 0.38 per block.

## Scope
- **In:**
  - a header-range fetch (`/blockchain`) with windows aligned to the start height;
  - building an empty block from its header entry;
  - batched `block_results` for the non-empty blocks of a window;
  - the cross-check between the header's `num_txs` and the `txs/block` response;
  - recording and replaying the new responses;
  - a `--no-ranges` switch and an automatic fall-back to the per-block path;
  - the fake node and curated-sample changes the tests need.
- **Out:** following the head (ticket 10 asks for one new block every ~5.8 s, so there is nothing to batch); parallel writes (ticket 08); an adaptive rate limiter; any change to the REST `txs/block` call, which has no batch form.

## Spec
Facts about the endpoints, checked on 2026-11-02 (re-check before relying on them):
- **`/blockchain`** returns at most 20 entries, **highest first** (descending), and for a wider range it returns only the *highest* 20. So the source asks for windows of at most 20 heights, `[start, start + 19]`, and sorts the reply. A range past the chain head is clamped to the head. `num_txs` is a string, `block_id.hash` is already uppercase hex. publicnode and Polkachu both support it.
- **JSON-RPC batch** (POST of an array) is limited to **10 requests** on publicnode (`batch request exceeds maximum (10)`). The limit is configurable, `INDEXER_RPC_BATCH`, default 10; larger sets are split into chunks.

Behaviour:
- **Windows.** Heights are planned in windows of 20 starting at `--from-height` (the last window ends at `--to-height`, or the head). One `/blockchain` request per window, made once even when several fetchers need it (a memoised future per window). A window is dropped from memory once its last height is consumed. The planner is shared by every caller of `block(height)`, one thread today and the worker threads of ticket 08 later, so it must be thread-safe: `block(height)` stays per height and consults the plan.
- **Empty block** (`num_txs == "0"`): built from the header entry alone, `tx_num = 0`, no per-block request. It is written like any other block, so the writer, the invariant checker and the API need no change.
- **Non-empty block:** `txs/block` (all pages) as today. Its `block_results` come from a batch request covering the non-empty heights of the window, in chunks of at most `INDEXER_RPC_BATCH`; one memoised future per chunk. A JSON-RPC error inside a batch element (for example a pruned height) is bad data for that height only.
- **Cross-check.** For a non-empty block the header's `num_txs` must equal the number of transactions in `txs/block`; if not, bad data ("the two responses disagree"), same class as ticket 04's count rule. Because an empty block now has no `block_results` to compare, this check plus `data_hash` being the hash of an empty input stand in for it.
- **Rate limit.** One token per HTTP request, so a batch costs one token. If a provider is found to count a batch per element, the cost becomes a setting; 429s already rotate the endpoint.
- **Fall-back.** `--no-ranges` (or `INDEXER_RANGES=0`) uses ticket 05's per-block path. If every endpoint answers `/blockchain` with a "not found / method not allowed" error, log one warning and use the per-block path for the rest of the run. A height missing from a reply (pruned, or past the head) is fetched with the per-block path, which gives the precise error.
- **Recording (D5).** `--record` stores what was fetched, per height:
  - `<height>.meta.json.gz`: the header entry of an empty block (and of a non-empty one, for the cross-check on replay);
  - `<height>.txs*.json.gz` and `<height>.results.json.gz` for non-empty blocks as today.

  Entries that arrive inside a multi-height reply (a `/blockchain` window, a batch) are cached per height, re-serialised as JSON. This is the one exception to "the bytes are stored unchanged"; single-height replies stay byte-identical. An empty block has only a `.meta` file. The replay source treats a height with a `.meta` and no `.txs` as an empty block, and still reads old caches that hold `.txs` and `.results` for empty blocks.
- **`verify` (ticket 06):** `verify --sample` fetches with the per-block path, so it checks this shortcut against the full responses.
- **Decision D27 (proposed, to confirm before building):** `block_results` is fetched only for blocks that have transactions, and `/blockchain` replaces the per-block requests for empty ones. See `REVAMP.md`.

## Acceptance criteria
- [ ] Indexing a window from the fake node gives the same rows as the per-block path (`--no-ranges`) and as replaying the recording.
- [ ] The fake node sees exactly `1 + N + ceil(N / 10)` requests for a window with `N` non-empty blocks, and none per empty block.
- [ ] A header whose `num_txs` disagrees with `txs/block` fails the block as bad data, and nothing is written.
- [ ] Called from several threads at once, the plan is built once per window (one `/blockchain` request each), the per-node rate limit holds, and the stored rows are unchanged.
- [ ] `--no-ranges`, and an endpoint without `/blockchain`, give the old behaviour.
- [ ] *(manual, not a test)* On the live head, requests per block and blocks/s are measured before and after with the default limits and written into `REVAMP.md` section 9. Expected: about 0.4 requests per block and a ceiling near 25 blocks/s.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| U13 | unit | `test_range_plan`: a real captured `/blockchain` reply parses (descending order, string `num_txs`, hex hash) and an empty entry becomes the same `Block` as the full responses give; windows are aligned and truncated at the end height; a batch of 23 splits into 10 + 10 + 3; a missing height falls back |
| I12 | integration | `test_range_fetch`: fake node with mixed empty and non-empty blocks: same rows as the per-block path, exact request count, `num_txs` disagreement, `--no-ranges` and unsupported endpoint, record then replay including empty blocks, four threads calling `block(height)` at once with the rate limit |
| U11 | unit | adds: a per-height `.meta` file round-trips; a height with a `.meta` and no `.txs` is an empty block |

**Test data and tools:**
- one real `/blockchain` reply (20 entries, captured once and committed) for U13;
- the fake node serves `/blockchain` and JSON-RPC batches by composing them from the cached blocks, in the same shape as the real reply, with the 20-entry, highest-first and 10-per-batch rules built in;
- `tools/curate_sample.py` gets a `--run` choice that contains at least 2 empty and 2 non-empty consecutive blocks (today's run has no empty block).
