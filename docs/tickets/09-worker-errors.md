# 09 · Worker error handling and orderly shutdown

**Slice:** errors in worker threads are classified. Transient errors retry and then go to `failed_blocks`; bad data goes to `failed_blocks`; an unexpected exception stops the whole run cleanly, with a non-zero exit. In no case is a block left partly written, a checkpoint moved too far, or a connection leaked.

**Acceptance test (Integration):** `I4`, all six cases, each ending with the invariant checker:

| Case | Scripted with | Expected |
|---|---|---|
| transient recovers | fake source times out twice on H | H stored once; no `failed_blocks` row |
| transient exhausted | H times out past the retry limit | `failed_blocks` row with attempts and last error; later heights stored; checkpoint stops at H − 1; a restart retries H and moves the checkpoint forward |
| dropped connection | `pg_terminate_backend` on the worker's connection mid-block | broken connection closed, not returned to the pool; block retried on a fresh one |
| bad data | `block_results` count mismatch on H | `failed_blocks` row; no retry; run continues |
| unexpected exception | a handler raises `KeyError` on H | no new heights handed out; in-flight blocks finish or roll back; all threads joined within the timeout; exit code non-zero; H and the traceback logged |
| SIGTERM | signal sent mid-run | the same orderly stop; its own exit code |

**Depends on:** 08 · **Decisions:** D21, D22

## Scope
- **In:**
  - error classes (`TransientError`, `BadDataError`, anything else is a bug);
  - retry with backoff and a maximum number of attempts;
  - a coordinator that watches each worker's future and sets a shared stop event;
  - signal handling;
  - timeouts on every HTTP request and database statement;
  - the seeded stress test.
- **Out:** head following (10).

## Spec
- **Classification:**
  - `requests` timeouts and connection errors, HTTP 429/5xx, `psycopg2.OperationalError` → transient;
  - `check_counts` mismatches and malformed JSON → bad data;
  - anything else → bug.
- **Stopping:** workers check the stop event between blocks. Python threads can't be killed, so shutdown relies on the timeouts.
- **Broken connections:** returned to the pool with `putconn(conn, close=True)`.
- **Exit codes:** 0 done; 1 stopped by an unexpected error; 2 stopped by a signal. Choosing other values is fine, as long as they are documented.

## Acceptance criteria
- [x] All six I4 cases pass with the invariant checker.
- [x] A crash injected through `before_commit` while another worker commits: that block is entirely present or entirely absent.
- [x] The stress test passes for its fixed number of seeded rounds, and prints the seed on failure.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| I4 | integration | the six cases above |
| I5 | integration | crash during another worker's commit |
| I7 | integration (`slow`) | seeded random delays and faults, fixed rounds |
| U8 | unit | transient then success; transient past the limit; bad data, no retry; unexpected exception re-raised |
