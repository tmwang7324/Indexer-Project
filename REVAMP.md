# Indexer Revamp

This file records what was found in the 2024 indexer, what has been fixed, what is still open, and the plan for the revamp. The revamp aims at higher throughput, recovery from failures, and GraphQL retrieval.

## Contents
1. [Where things stand](#1-where-things-stand)
2. [Issues fixed](#2-issues-fixed)
3. [Issues still open](#3-issues-still-open)
4. [Where blocks come from now](#4-where-blocks-come-from-now)
5. [Revamp plan](#5-revamp-plan)
6. [Open decisions](#6-open-decisions)
7. [Decisions log](#7-decisions-log)

---

## 1. Where things stand

`load_transactions.sh` loops over a folder of block JSON files. For each block it runs `check_one_file.py` (schema validation), `loading_files.py` (`blocks` row) and `verify_block.py`. For each transaction in the block it then runs `loading_tx.py` and `verify_tx.py`. Transactions are decoded by POSTing to a public `/cosmos/tx/v1beta1/decode` endpoint. Each message goes to a handler in `types_script/`, chosen by its `@type` through `type.json`. Addresses are de-duplicated into a shared `address` table. `Txs.sql` defines 41 tables.

**Baseline throughput:** 38 test blocks (48 transactions) take 81 to 86 seconds, about **0.45 blocks/s or 0.6 tx/s**. This was measured in a cloud container against a local PostgreSQL 16, with live decoding.

**Commits from the bug-fix pass** (on `claude/quirky-feynman-v7wozd`, on top of `main` at `a4db1e3`):

| Commit | Contents |
|---|---|
| `5084694` | Fix data-corruption and crash bugs in the loading pipeline |
| `38dc3c8` | Restore the line-5 block fixer, export `$txt`, add tests for each bug |
| `e6ad903` | Local PostgreSQL setup instructions in the README |

**Tests:** `python3 -m unittest discover -s tests` runs 27 tests: 16 without a database, plus 11 that need PostgreSQL (see the README). Every test written for a bug fails on `a4db1e3` and passes after the fixes.

---

## 2. Issues fixed

| # | Where | Problem | Effect | Fix | Test |
|---|---|---|---|---|---|
| 1 | `functions.py` `decode_tx` | Base URLs joined to `cosmos/tx/...` without a `/`, and `url_array[retries]` used with `max_retries=10` and only 3 URLs | The two fallback endpoints produced invalid URLs (`...stakeflow.iocosmos/...`); a 4th retry raised `IndexError` instead of returning `None` | `rstrip('/') + '/cosmos/...'` and `url_array[retries % len(url_array)]`; also retry on 429 and 500 | `test_decode_tx.py` |
| 2 | `loading_tx.py` | After a `UniqueViolation`, the existing transaction was looked up with `WHERE block_id = ...` | On a **re-run**, every later transaction's messages were saved under the block's first transaction. Their comments differ, so `UNIQUE(tx_id, comment)` did not catch the duplicates. Never happens on a first run, which is why the tests passed | Look up by `tx_hash, chain_id, height` | `RerunTest` |
| 3 | `loading_tx.py`, `verify_tx.py` | Block looked up with `WHERE height = '...'` only | With two chains loaded, transactions can attach to the other chain's block | `WHERE chain_id = %s AND height = %s` (parameterized) | `ChainIdTest` |
| 4 | `address_load.py` | `length_after_1 >= 38` (contract) tested before `== 38` (user) | Every wallet labelled `contract`; the `user` branch could never run | Test `== 38` first, then `> 38`; take the separator as the **last** `1` (`rfind`); move the logic into `classify_address()` | `test_address_classification.py` |
| 5 | `loading_tx.py` | `continue` for an unknown message type skipped `i += 1` | Messages after an unknown one got the wrong number. Once a handler is added and the block re-indexed, their comment changes and they are inserted again | `for i, message in enumerate(messages, start=1)` | `MessageNumberingTest` |
| 6 | `load_transactions.sh` | `txt` never exported (the export was commented out in v1.3) | Any unknown message type crashed `loading_tx.py` in `new_type()` with `FileNotFoundError: 'None/new_type.txt'`; the rest of that transaction's messages were lost silently | `export txt` | `test_exports_log_folder_to_python_scripts` |
| 7 | `check_one_file.py` | Block fixer called `checkLine(file_name, 1)`: wrong number of arguments, `1` instead of `5`, and `file_name` instead of `file_path` | `TypeError`, exit 1 instead of 8, and the shell only stops on 8, so it went on to load the schema-invalid block | Restored as intended: remove line 5 of `file_path`, log the removed text, exit 8 | `CheckOneFileTest` |
| 8 | `loading_files.py` | `sys` used in the error handler but not imported | A bad block raised `NameError` instead of naming the block | `import sys` | `LoadingFilesTest` |
| 9 | `verify_tx.py` | Always exited 0; `if row is None` (but `fetchall()` returns `[]`); expected `fee_denom "0"` for a transaction with no fee while the loader stores `""` | Verification could never flag a failure; a missing row crashed with `IndexError`; no-fee transactions always "mismatched" | Exit 1 on any mismatch or missing row; `len(row) != 1`; same no-fee defaults as the loader | `VerifyTxTest` |
| 10 | `load_transactions.sh` | `psql -h localhost` hard-coded | `db_host` and `db_port` in `info.json` ignored | `-h "$DBHOST" -p "$DBPORT"` | `test_uses_port_from_info_json` |
| 11 | `load_transactions.sh` | `loading_tx.py`'s exit status never checked | Load failures were invisible | Check it; skip verification for that transaction; count failures | `test_loading_tx_failure_...` |
| 12 | `load_transactions.sh` | `"(Exit code $?)"` printed after a `[[ ]]` test | Printed the test's status, not the script's; `echo "..." 6` printed a literal 6 | Save `status=$?` straight after each command | `test_verify_tx_failure_...` |
| 13 | `load_transactions.sh` | `python` and `python3` branches duplicated and drifted apart | A failed block verification ended the run in one branch and only warned in the other | One path using `$PY` | (covered by the shell tests) |
| 14 | `functions.py` | `"^\d+$"` in normal strings | `SyntaxWarning` in every error log | Raw strings `r"^\d+$"` | (syntax check) |
| 15 | `address_load.py`, `loading_tx.py`, `verify_tx.py` | SQL built with f-strings | Breaks on a quote in the value; injection risk | Parameterized queries | (covered above) |
| 16 | repo | No `.gitignore`; 11 `__pycache__/*.pyc` files committed | Noise in the repo; `info.json` credentials easy to commit | `.gitignore` for `info.json`, bytecode and `log/` | n/a |

---

## 3. Issues still open

These were found but left alone, either because the revamp replaces the code or because they need a decision.

### Correctness
- **`check_file` repair path (`functions.checkLine`).** On invalid JSON it deletes line `len(lines) - 1`, the second-to-last line, which may not be the bad one. `checkLine` also has bugs: `N >= len(lines)` makes the last line impossible to target; `print(foundError, sys.stderr)` prints to stdout; and its bare `except:` also catches `SystemExit` from the `check_file` call it makes.
- **The line-5 fixer can damage good blocks.** If a block fails the schema for any other reason, each run deletes another line. Line 5 is normally `"total": 1,`, which the schema requires, so removing it cannot make a block valid on its own. Removed lines are logged to `error.log`.
- **Only the first fee coin is stored** (`fee.amount[0]`). Transactions that pay fees in several denoms lose the rest.
- **Address extraction only looks at a message's top-level keys** whose names contain `send`, `receiver`, `addr`, `grante`, `admin` or `voter`. Addresses in nested fields, such as the messages inside a `MsgExec`, are not linked.
- **`address.created_at` uses `datetime.now()`**, which is local time with no timezone, while other timestamps are UTC.
- **`verify_block.py` looks the block up by `block_hash` alone**, not by `(chain_id, height)`.
- **The old block schema only accepts Migaloo blocks.** `Validate_json` in `functions.py` requires `sdk_block.header.proposer_address` to be exactly 53 characters, the length of a `migaloovalcons1...` address. Terra's `terravalcons1...` addresses are 51, so every Terra block fails with exit 8 (checked on 3 consecutive blocks, 2026-11-02). The line-5 fixer then deletes line 5 (`"total": 1,`) of each valid Terra block file.
- **No transaction outcome:** the decode endpoint returns only the transaction body, so success/failure (`code`), `gas_used` and events are never stored.

### Reliability
- **Nothing is atomic.** The block row, each transaction and each message are committed separately, often on different connections. A crash leaves a half-loaded block.
- **No checkpoint.** A restart re-processes the whole folder.
- **One schema-invalid block stops the whole run** (`die` on exit 8).
- **Logs are deleted at the start of every run** (`output.log`, `error.log`, `output2.log`, `test.log`).
- **Handlers swallow `UniqueViolation`** without rolling back or closing their connection.

### Throughput (per transaction)
- 2 Python processes are started (`loading_tx.py` and `verify_tx.py`).
- The block file is read and parsed again in each of them.
- 2 HTTP decode calls are made for the same bytes (load and verify).
- A new database connection is opened for the transaction, for **every address** (`address_load.main`) and for **every message** (each handler).
- Handlers are found through `importlib` and `sys.path.append` on every message.

### Schema
- **Numbers stored as text:** `height`, `tx_num`, `fee_amount` and `gas_limit` are `VARCHAR`, so `height > 7000000` and `ORDER BY height` compare text (`'9' > '10'`).
- **Uniqueness depends on English sentences:** message tables are `UNIQUE(tx_id, comment)` (35 tables), and `comment` is text like "This is number 2 message in number 3 transaction".
- **Redundant indexes:** for example, `UNIQUE (chain_id, height)` already creates an index, and `blocks_chain_id_height` plus `blocks_chain_id_hash_height` duplicate it. `transactions` and `address` have the same problem.
- **Hard to answer "everything involving address X":** addresses are spread across about 37 message tables, each with its own `*_address_id` columns.

### Housekeeping
- The README clone URL points to the `Shikhar-G` fork.
- `load_transactions.sh`'s header contains a teammate's personal phone number. It is also in the git history.
- `types_script/functions.py` duplicates `create_connection` (and prints on every connect).

---

## 4. Where blocks come from now

*Checked from a cloud container on 2026-11-01. Public infrastructure changes, so re-check before relying on it.*

- **The test blocks are from Migaloo (`migaloo-1`), not Terra.** Their shape (`block_id` / `block` / `sdk_block`) is exactly what `GET /cosmos/base/tendermint/v1beta1/blocks/{height}` returns.
- **Migaloo looks unreachable.** Every node in the chain registry failed: publicnode REST 404, Kleomedes SSL error 525, Polkachu upstream failure, cosmos.directory 502.
- **Terra (`phoenix-1`) is live**, with the head at about 23,558,7xx on 2026-11-01. It returns the same block shape and uses the same module families: Cosmos SDK, CosmWasm, IBC and Alliance. The existing tables and handlers carry over almost unchanged, and the Terra decode endpoint already decoded the Migaloo test transactions.
- **History available from public nodes:**

  | Source | Range |
  |---|---|
  | `terra-rest.publicnode.com` | Height 22,711,258 onward (2026-09-06, about 2 months); older blocks are deleted as new ones arrive |
  | `terra-api.polkachu.com` | Height 15,601,678 onward, with gaps (22,000,000 returned "nil Block") |
  | From genesis | Needs a paid archive provider or your own node restored from a snapshot |

- **One request per block for decoded transactions:** `GET /cosmos/tx/v1beta1/txs/block/{height}` returns the raw block *and* every transaction decoded. This replaces 2 decode calls per transaction. Notes:
  - It pages its results, so blocks with many transactions need follow-up requests using `pagination.next_key`.
  - It does **not** include transaction results. Those come from one more request per block, CometBFT RPC `/block_results?height=H`, which returns `code`, `codespace`, `gas_wanted`, `gas_used`, `log` and `events` for each transaction (checked on `terra-rpc.publicnode.com`, 2026-11-02).
  - The transaction hash is still computed locally: SHA-256 of the raw bytes in `block.data.txs`, which are in the same order as the decoded `txs`.

**Measured on Terra, 2026-11-02** (150 blocks, one every 1,000 heights, back from the head):

| Measure | Value |
|---|---|
| Transactions per block | 0.33 (most blocks are empty) |
| Download per block (`txs/block` + `block_results`) | about 90 KiB |
| Same, gzip-compressed | about 19 KiB (4.8x smaller) |
| Stored per block (transaction JSON, outcome, transaction events, header) in Postgres, compression included | 5.8 KiB |

The stored figure leaves out the `messages` copy, the per-type tables and indexes; with those, estimate 6 to 12 KiB per block. Storage is therefore not the limit; download volume and the number of requests to free public nodes are.

---

## 5. Revamp plan

**Decisions:** Terra `phoenix-1`; one long-running Python service; **Strawberry + FastAPI** for GraphQL; no protobuf decoding (D6).

### 5.1 Ingestion service

Replace the shell loop and the per-transaction scripts with one Python process:

```
 BlockSource ──> Parser ──> Handlers ──> Writer ──> PostgreSQL
 (REST, files)   (once      (imported    (pool, one
                  per block)  once)       transaction
                                          per block)
```

- **BlockSource** has three implementations:
  - **REST:** `/cosmos/tx/v1beta1/txs/block/{h}` plus `/block_results?height={h}` (D4), rotating between several endpoints with backoff on 429 and 5xx, plus a per-endpoint rate limit.
  - **Replay cache (D5):** the REST source can record each block's two raw responses, gzipped, to a local folder (about 19 KiB per block, roughly 470 MiB for the 25,000-block backfill). Later runs read from the cache instead of the network.
  - **Files:** reads the existing folders of block files, for tests and the Migaloo fixtures.
- **Parser:** parse each block once into plain data objects (block, transactions, messages). Nothing reads the block file again.
- **Handlers:** load the registry from `type.json` once at startup. Every message is written to the `messages` table (D2). A handler, when one exists for the type, **returns the typed row** for its per-type table instead of opening a connection and writing. An unknown type is simply a `messages` row with no typed copy, which replaces `new_type.txt`.
- **Writer:**
  - One connection pool for the whole service: `psycopg2.pool.ThreadedConnectionPool`, sized to the number of worker threads (D7).
  - **One database transaction per block**, so a block is saved completely or not at all.
  - `INSERT ... ON CONFLICT DO NOTHING` instead of catching `UniqueViolation`.
  - Addresses are inserted in bulk per block, using a small in-memory cache of already-known addresses.
- **No protobuf (D6):** the REST source returns transactions and events already decoded to JSON, and the transaction hash is SHA-256 of the raw bytes in `block.data.txs`, so nothing needs protobuf. The HTTP `decode_tx` call and its endpoint list are removed. The base64-protobuf `data` field of each transaction result is not stored.

### 5.2 Reliability
- **Checkpoint = highest contiguous height (D7).** Worker threads finish blocks out of order, so a single "last height" would skip blocks after a crash (block 105 written, 103 not yet). Instead, the `blocks` row itself (written in the block's database transaction) marks a height as done, and `checkpoints(chain_id, contiguous_height)` stores the highest height below which every block is done. A restart resumes from `contiguous_height + 1` and skips heights that already have a `blocks` row; re-writing one is harmless because loads are idempotent.
- **`failed_blocks(chain_id, height, error, attempts, last_tried)`:** retry a few times with backoff, then record the block and move on instead of stopping.
- **Idempotent re-runs:** loading a block twice changes nothing. The current `RerunTest` carries over as an invariant.
- **Verification** becomes a check inside the write transaction (row counts per block) plus an optional sampled re-fetch, not 2 extra processes per transaction.

### 5.3 Concurrency
- **Model (D7): one process, a pool of worker threads.** The work is I/O-bound, so the GIL is not a limit. Each thread has its own `requests.Session` (sessions are not safe to share across threads) and borrows a database connection from the pool for each block.
- **Backfill:** worker threads take heights from a shared queue. Each block is written in its own database transaction, so workers don't need to coordinate beyond the queue and the checkpoint (5.2).
- **Rate limiting:** one token bucket per endpoint, shared by all threads and protected by a lock, so adding threads cannot exceed a node's request rate.
- **Head follower:** a single loop that polls `blocks/latest` and indexes new blocks in order.
- **Measure before tuning.** Public endpoints rate-limit, so the bottleneck will probably be the network, not Python. Compare against the 0.45 blocks/s baseline in section 1.

### 5.4 Schema migration
- `height`, `tx_num`, `gas_limit` as `BIGINT`; amounts as `NUMERIC` (they can exceed 64 bits).
- Add `messages(message_id, tx_id, msg_index, type, raw JSONB)` with `UNIQUE(tx_id, msg_index)`, holding every message (D2).
- Per-type tables reference `messages.message_id` (primary key and foreign key) instead of `UNIQUE(tx_id, comment)`. Keep `comment` only if it's still wanted for display.
- Store every fee coin, in `transaction_fees(tx_id, denom, amount)` or as JSONB.
- Add `message_addresses(message_id, address_id, role)` so "all activity for an address" is one indexed lookup.
- Store each transaction's outcome (`code`, `codespace`, `gas_wanted`, `gas_used`, `log`) as columns, and its events as JSONB; block-level events are not stored (D4).
- Drop the redundant indexes.
- Ship it as numbered migration files instead of editing `Txs.sql` in place.

### 5.5 GraphQL (Strawberry + FastAPI)
- **Types:** `Block`, `Transaction`, `Message` and `Address`. `Message` is backed by the `messages` table, so every message, including unknown types, can be paged over. Typed fields (vote option, send amount, ...) come from the per-type table when one exists for that message's type (D2).
- **Queries:**
  - `block(chainId, height)`, `blocks(range, first, after)`
  - `transaction(hash)`, `transactions(filter: {height range, messageType, address}, first, after)`
  - `address(value) { messages(first, after) }`
- **Paging:** cursor-based (`first` / `after`), ordered by `(height, tx index, msg_index)`.
- **N+1 queries:** Strawberry DataLoaders for transaction → messages, message → addresses, and transaction → block.
- **Read-only**, with its own connection pool and limits on query depth and complexity.

### 5.6 Testing
- Keep the current `unittest` suite running against the old scripts until each piece is replaced, then port the tests to the new modules.
- Fixture-based tests for each handler, using saved decoded transactions with no network.
- An end-to-end test: a file source with the test blocks → database → GraphQL query → expected JSON.
- **Benchmarks and failure tests use the replay cache (D5)**, so throughput numbers measure the indexer rather than node latency, runs are reproducible, and a fault-injecting wrapper around the cache can produce timeouts, 429s, malformed responses and crashes on demand.

---

## 6. Open decisions

1. ~~**Line-5 fixer**~~: decided in D11 (delete line 5 only when the schema error is about line 5's field).
2. ~~**Backfill range**~~: decided in D3 (25,000 blocks by default, configurable).
3. ~~**Transaction results**~~: decided in D4 (outcome and transaction events).
4. ~~**Migaloo**~~: decided in D12 (fixtures only).
5. ~~**Deployment**~~: decided in D13 (Docker Compose for everything).

---

## 7. Decisions log

**Process note:** implementation does not start when this review finishes; it waits for an explicit go-ahead.

Decisions agreed while reviewing this plan, newest last. Where a decision changes an earlier section, that section is updated too.

| # | Question | Decision | Consequences |
|---|---|---|---|
| D1 | What is the revamped indexer for? | **Portfolio project.** It runs on a laptop or one small server, follows the Terra chain head plus a bounded backfill, and shows correctness, measured throughput and clean design. | No production monitoring or alerting, and no paid archive node. Docker Compose is enough for deployment. Effort goes into correctness, tests, measured throughput and a clear GraphQL API, not into operations. |
| D2 | How should messages be stored? | **Hybrid.** Every message goes into one `messages` table (`message_id`, `tx_id`, `msg_index`, `type`, raw JSONB), and the existing per-type tables stay as typed copies of the types they cover. | Nothing is ever lost: an unknown type is still a `messages` row, just without a typed copy, so `new_type.txt` and the planned `unknown_messages` table are no longer needed. Per-type tables reference `messages.message_id` instead of `UNIQUE(tx_id, comment)`. `message_addresses` points at `messages.message_id`, so it needs no table-name column. GraphQL pages over one `Message` type and reads typed fields from the per-type table when one exists. Adding a type later only adds a typed copy, which can be back-filled from the stored JSON without re-fetching blocks. |
| D3 | How much history to backfill? | **25,000 blocks by default, configurable** (revised from ~100,000 after the D4 measurements). Follow the chain head, and backfill the last 25,000 blocks, about 1.7 days at ~5.8 s per block. The start height is a command-line option. | From the measured sample: about 8,300 transactions, ~2.1 GiB downloaded in 50,000 requests, and ~150-300 MB in Postgres. Local storage is not the limit; load on free public nodes is. Enough for steady-state throughput runs and kill-and-resume tests. Larger ranges stay available as an optional benchmark. Backfill and head-following run side by side, so the indexer must handle a gap between where the backfill stops and where the head follower started. |
| D4 | Store transaction results? | **Outcome and transaction events.** Fetch `/block_results` for every block and store each transaction's `code`, `codespace`, `gas_wanted`, `gas_used` and `log`, plus its events as JSONB. Block-level events are skipped. | Failed transactions are flagged instead of being indexed as if they succeeded (a failed `MsgSend` no longer looks like a transfer), and CosmWasm contract activity can be queried from the events. Costs a second request per block; both responses together are about 90 KiB per block. The two responses must be matched by height and transaction position. |
| D5 | Save fetched blocks locally for replay? | **Record and replay.** The REST source can save each block's two raw responses, gzipped, and later runs can read from that cache instead of the network. | About 19 KiB per block on disk (roughly 470 MiB for 25,000 blocks). The 25,000 blocks are downloaded once, not on every run. Throughput numbers measure the indexer itself and are reproducible, and reliability tests inject failures through the cache. Network throughput is measured separately, on recording runs. The cache folder must be git-ignored. |
| D6 | Is protobuf decoding needed? | **No.** Transactions from `/cosmos/tx/v1beta1/txs/block/{h}` arrive as JSON with nested messages expanded, and `/block_results` events are plain strings on Terra's CometBFT 0.38.19 (checked 2026-11-02); the transaction hash is SHA-256 of the raw bytes. | No protobuf library or generated Terra types, and no `Decoder` abstraction. `decode_tx` and its 2 HTTP calls per transaction go away. The `data` field of transaction results (base64 protobuf, message return values) is not stored. The Migaloo test blocks stay usable through the saved decoded fixtures. Revisit only if an RPC-only source or a CometBFT 0.34 node (base64 event attributes) is ever needed. |
| D7 | How should the indexer run work concurrently? | **Thread pool.** One process with N worker threads, using `requests` and a psycopg2 `ThreadedConnectionPool`. | Stays on `requests` and psycopg2 (no move to psycopg 3 or httpx), close to the existing code. Each thread gets its own `requests.Session`. Per-endpoint rate limits are token buckets shared across threads behind a lock. Blocks finish out of order, so the checkpoint is the highest contiguous height, not the last height written (5.2). The GraphQL API runs as a separate process and is not affected by this choice. |
| D8 | What happens to the existing pipeline? | **Keep both permanently.** `load_transactions.sh` and its scripts stay as a file-based loader next to the new service; nothing is deleted. | Two code paths exist for good, so the 27 existing tests keep running against the old scripts and the new service gets its own tests. The old scripts write the old table layout, while D2 and 5.4 change it, so how the two share (or don't share) a database is decided in D9. |
| D9 | How do the two pipelines share PostgreSQL? | **Separate schemas in the same database**, so the two can be compared for speed: the old pipeline's `Txs.sql` tables live in a `legacy` schema and the new indexer owns its own schema. | Neither pipeline can break the other's tables. The old scripts need one small change: a schema setting (e.g. `db_schema` in `info.json`) applied as the connection's `search_path`, and the same for the `psql` call that runs `Txs.sql` (via `PGOPTIONS`). GraphQL reads only the new schema; the legacy one stays queryable with SQL. The speed comparison needs both pipelines to load the same blocks (D10). |
| D10 | What workload does the speed comparison use? | **The same Terra blocks for both pipelines.** About 1,000 consecutive Terra blocks (~330 transactions), saved once as old-format files (`/cosmos/base/tendermint/v1beta1/blocks/{h}`, which includes `sdk_block`) for the old pipeline, while the new indexer reads the same heights from the replay cache. | One extra request per block when preparing the set. The old pipeline's time includes its 2 HTTP decode calls per transaction; the report states this rather than hiding it. Compared: blocks/s, tx/s, and that both schemas end up with the same blocks, transactions and messages. **Blocker found:** the old schema rejects every Terra block (`proposer_address` hard-coded to Migaloo's 53 characters, see section 3), and the line-5 fixer then damages the files, so the old validator must accept Terra before this benchmark can run. |
| D11 | What happens to the line-5 fixer? | **Fix only a known bad line 5.** The fixer stays, but deletes line 5 only when the schema error is about line 5's field (`block_id.part_set_header.total`); any other schema failure exits 8 without changing the file. The `sdk_block.header.proposer_address` rule is generalized to accept any chain's validator consensus address instead of exactly 53 characters. | Valid Terra blocks pass the old validator, which unblocks the D10 benchmark. A block that fails for another reason is reported and left intact, so repeated runs no longer delete a line each time. The fixer must read the error's path from jsonschema (`ValidationError.absolute_path`), and its tests gain two cases: an unrelated schema failure leaves the file unchanged, and a real Terra block passes. Applies to the old pipeline only; the new indexer reads JSON from nodes, not hand-edited files. |
| D12 | What role does Migaloo play? | **Fixtures only.** The 38 Migaloo test blocks and the decoded fixture stay as offline test data for both pipelines; the new indexer supports only `phoenix-1`. | `chain_id` stays part of every key (blocks, transactions, checkpoints), so adding a chain later is configuration rather than a redesign. Tests exercise two chains' data (Migaloo fixtures, Terra replay cache), which keeps the code from assuming one address prefix or address length, the same class of bug as the Migaloo-only `proposer_address` rule. |
| D13 | How is the project run locally? | **Docker Compose for everything.** One `docker-compose.yml` with `postgres`, `indexer` and `api` services, so `docker compose up` starts the whole project. The old pipeline (D8) runs as a one-off container whose image includes `psql` and `jq`. | Only Docker is needed on the host. Database settings come from environment variables rather than only `info.json`, because inside Compose the host is `postgres`, not `localhost`; the old scripts need a way to read the same settings (D9 already touches them for the schema). The replay cache (D5) is a mounted folder so it survives rebuilds, and PostgreSQL data lives in a named volume. The README's `docker run` instructions are replaced by the Compose ones when this is built. |
