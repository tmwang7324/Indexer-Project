# 05 · Record from live nodes

**Slice:** fetch blocks from public REST/RPC nodes, rotating endpoints and respecting per-endpoint rate limits, and optionally record every response into the replay cache while indexing.

**Acceptance test (Integration):** `I8`: start a **local fake node** (a small HTTP server in the test process that serves the curated sample, with one endpoint scripted to return 429 and then fail) and run `python -m indexer run --source rest --record <tmp>` against it. The blocks are indexed, the second endpoint is used while the first is down, the request rate stays under the limit, and the recorded cache matches the served bytes. Replaying that cache then gives the same database rows.

**Depends on:** 04 · **Decisions:** D5

## Scope
- **In:**
  - REST source: `/cosmos/tx/v1beta1/txs/block/{h}` (with pagination) and RPC `/block_results?height={h}`;
  - endpoint list from configuration;
  - rotation with backoff;
  - a token-bucket rate limiter per endpoint;
  - a request timeout on every call;
  - recording into the replay cache.
- **Out:** retry and error classification across workers (09). Here a block whose fetch fails after rotation is an error.

## Spec
- **Endpoints** default to publicnode and Polkachu for Terra, overridable by environment variable.
- **Rotation:** an endpoint that fails (timeout, 429, 5xx) is skipped for a cool-down period, then tried again.
- **Rate limiter:** shared by all threads behind a lock (D7), and tested with a fake clock.
- **Recording** never alters the bytes. A recorded block that is already cached is not written again.
- **No test calls a real node (D25).** The fake node is the only HTTP server tests use.

## Acceptance criteria
- [x] Indexing from the fake node equals indexing from the replay cache (same rows).
- [x] While endpoint A returns 429, requests go to endpoint B, and A is used again after its cool-down.
- [x] The measured request rate never exceeds the configured limit.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I8 | integration | fake node: rotation, rate limit, record then replay |
| U7 | unit | burst up to capacity; refill over time (fake clock) |
| U9 | unit | failing endpoint skipped, retried after cool-down |
