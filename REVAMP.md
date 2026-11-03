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
8. [Testing strategy](#8-testing-strategy)

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
- **Hard to answer "everything involving address X":** addresses are spread across 35 message tables (plus 2 side tables), each with its own `*_address_id` columns.

### Housekeeping
- The README clone URL points to the `Shikhar-G` fork.
- `load_transactions.sh`'s header contains a teammate's personal phone number. It is also in the git history.
- `types_script/functions.py` duplicates `create_connection` (and prints on every connect).

---

## 4. Where blocks come from now

*Checked from a cloud container on 2026-11-01. Public infrastructure changes, so re-check before relying on it.*

- **The test blocks are from Migaloo (`migaloo-1`), not Terra.** Their shape (`block_id` / `block` / `sdk_block`) is exactly what `GET /cosmos/base/tendermint/v1beta1/blocks/{height}` returns.
- **Migaloo looks unreachable.** Every node in the chain registry failed: publicnode REST 404, Kleomedes SSL error 525, Polkachu upstream failure, cosmos.directory 502.
  - **Re-checked 2026-11-02:** 18 REST endpoints (the registry's 3 plus 15 other plausible providers) all failed. Polkachu has delisted Migaloo (its Migaloo network and validator pages return 404 while the Terra ones work, and its public RPC list has Terra but not Migaloo). publicnode's home page lists Terra but not Migaloo, and its Migaloo RPC returns 404. Kleomedes fails TLS (525), and ping.pub's Migaloo explorer returns 404. The chain registry still marks Migaloo `live`, which looks out of date. No shutdown announcement turned up, so whether the chain still produces blocks is unknown: the public infrastructure is gone, and the chain may or may not be.
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

**Decisions:** Terra `phoenix-1`; one long-running Python service; **Strawberry + FastAPI** for GraphQL; protobuf decoding only for raw transaction bytes in block files (D6, revised by D26).

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
- **Decoding (D6, D26):** the REST source returns transactions and events already decoded to JSON, so the live path needs no protobuf. Block files that carry only raw transaction bytes (the Migaloo test blocks) are decoded **locally with generated protobuf classes**, by `python -m indexer decode` or automatically by the files source. The transaction hash is SHA-256 of the raw bytes either way. The HTTP `decode_tx` call and its endpoint list are removed from the new indexer. The base64-protobuf `data` field of each transaction result is not stored.

### 5.2 Reliability
- **Checkpoint = highest contiguous height (D7).** Worker threads finish blocks out of order, so a single "last height" would skip blocks after a crash (block 105 written, 103 not yet). Instead, the `blocks` row itself (written in the block's database transaction) marks a height as done, and `checkpoints(chain_id, contiguous_height)` stores the highest height below which every block is done. A restart resumes from `contiguous_height + 1` and skips heights that already have a `blocks` row; re-writing one is harmless because loads are idempotent.
- **`failed_blocks(chain_id, height, error, attempts, last_tried)`:** retry a few times with backoff, then record the block and move on instead of stopping.
- **Idempotent re-runs:** loading a block twice changes nothing. The current `RerunTest` carries over as an invariant.
- **Verification (D14):** before each block's database transaction commits, the writer checks counts against the source: transactions written = the block's transaction count, outcomes = `txs_results` count, messages = the sum of each transaction's messages. A mismatch rolls the block back and records it in `failed_blocks`. A separate `verify` command re-fetches a random sample of heights and compares them field by field. No extra processes or requests on the normal path.

### 5.3 Concurrency
- **Model (D7): one process, a pool of worker threads.** The work is I/O-bound, so the GIL is not a limit. Each thread has its own `requests.Session` (sessions are not safe to share across threads) and borrows a database connection from the pool for each block.
- **Backfill:** worker threads take heights from a shared queue. Each block is written in its own database transaction, so workers don't need to coordinate beyond the queue and the checkpoint (5.2).
- **Rate limiting:** one token bucket per endpoint, shared by all threads and protected by a lock, so adding threads cannot exceed a node's request rate.
- **Catch up, then follow (D16):** on first start the indexer begins 25,000 blocks below the head (D3) and works upward. Once it reaches the head, the same workers wait for new blocks by polling `blocks/latest`. It is one ascending stream from the start height, so there is never a gap between backfilled and followed blocks.
- **Measure before tuning.** Public endpoints rate-limit, so the bottleneck will probably be the network, not Python. Compare against the 0.45 blocks/s baseline in section 1.

### 5.4 Schema migration
- `height`, `tx_num`, `gas_limit` as `BIGINT`; amounts as `NUMERIC` (they can exceed 64 bits).
- Add `messages(message_id, tx_id, msg_index, type, raw JSONB)` with `UNIQUE(tx_id, msg_index)`, holding every message (D2).
- Per-type tables reference `messages.message_id` (primary key and foreign key) instead of `UNIQUE(tx_id, comment)`. Keep `comment` only if it's still wanted for display.
- Store every fee coin, in `transaction_fees(tx_id, denom, amount)` or as JSONB.
- Add `message_addresses(message_id, address_id, role)` so "all activity for an address" is one indexed lookup.
- Store each transaction's outcome (`code`, `codespace`, `gas_wanted`, `gas_used`, `log`) as columns, and its events as JSONB; block-level events are not stored (D4).
- Drop the redundant indexes.
- Ship it as **Alembic migrations (D17)**, written by hand as SQL in `op.execute()`, instead of editing `Txs.sql` in place. `Txs.sql` stays as the old pipeline's schema in `legacy` (D9).

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
The full testing strategy is in [section 8](#8-testing-strategy). In short: unit, component, integration and end-to-end layers for the new indexer; the existing 27 tests stay with the old pipeline, which is kept permanently (D8); benchmarks and failure tests use the replay cache (D5).

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
| D3 | How much history to backfill? | **25,000 blocks by default, configurable** (revised from ~100,000 after the D4 measurements). Follow the chain head, and backfill the last 25,000 blocks, about 1.7 days at ~5.8 s per block. The start height is a command-line option. | From the measured sample: about 8,300 transactions, ~2.1 GiB downloaded in 50,000 requests, and ~150-300 MB in Postgres. Local storage is not the limit; load on free public nodes is. Enough for steady-state throughput runs and kill-and-resume tests. Larger ranges stay available as an optional benchmark. Backfill runs first and then turns into head-following (D16), so there is no gap to handle. |
| D4 | Store transaction results? | **Outcome and transaction events.** Fetch `/block_results` for every block and store each transaction's `code`, `codespace`, `gas_wanted`, `gas_used` and `log`, plus its events as JSONB. Block-level events are skipped. | Failed transactions are flagged instead of being indexed as if they succeeded (a failed `MsgSend` no longer looks like a transfer), and CosmWasm contract activity can be queried from the events. Costs a second request per block; both responses together are about 90 KiB per block. The two responses must be matched by height and transaction position. **Proposed revision: D27 (ticket 16)** fetches results only for blocks that have transactions. |
| D5 | Save fetched blocks locally for replay? | **Record and replay.** The REST source can save each block's two raw responses, gzipped, and later runs can read from that cache instead of the network. | About 19 KiB per block on disk (roughly 470 MiB for 25,000 blocks). The 25,000 blocks are downloaded once, not on every run. Throughput numbers measure the indexer itself and are reproducible, and reliability tests inject failures through the cache. Network throughput is measured separately, on recording runs. The cache folder must be git-ignored. |
| D6 | Is protobuf decoding needed? | **No.** Transactions from `/cosmos/tx/v1beta1/txs/block/{h}` arrive as JSON with nested messages expanded, and `/block_results` events are plain strings on Terra's CometBFT 0.38.19 (checked 2026-11-02); the transaction hash is SHA-256 of the raw bytes. | No protobuf library or generated Terra types, and no `Decoder` abstraction. `decode_tx` and its 2 HTTP calls per transaction go away. The `data` field of transaction results (base64 protobuf, message return values) is not stored. ~~The Migaloo test blocks stay usable through the saved decoded fixtures.~~ **Partly reversed by D26:** raw transaction bytes in block files are decoded locally with protobuf. The live REST path is unchanged. |
| D7 | How should the indexer run work concurrently? | **Thread pool.** One process with N worker threads, using `requests` and a psycopg2 `ThreadedConnectionPool`. | Stays on `requests` and psycopg2 (no move to psycopg 3 or httpx), close to the existing code. Each thread gets its own `requests.Session`. Per-endpoint rate limits are token buckets shared across threads behind a lock. Blocks finish out of order, so the checkpoint is the highest contiguous height, not the last height written (5.2). The GraphQL API runs as a separate process and is not affected by this choice. |
| D8 | What happens to the existing pipeline? | **Keep both permanently.** `load_transactions.sh` and its scripts stay as a file-based loader next to the new service; nothing is deleted. | Two code paths exist for good, so the 27 existing tests keep running against the old scripts and the new service gets its own tests. The old scripts write the old table layout, while D2 and 5.4 change it, so how the two share (or don't share) a database is decided in D9. |
| D9 | How do the two pipelines share PostgreSQL? | **Separate schemas in the same database**, so the two can be compared for speed: the old pipeline's `Txs.sql` tables live in a `legacy` schema and the new indexer owns its own schema. | Neither pipeline can break the other's tables. The old scripts need one small change: a schema setting (e.g. `db_schema` in `info.json`) applied as the connection's `search_path`, and the same for the `psql` call that runs `Txs.sql` (via `PGOPTIONS`). GraphQL reads only the new schema; the legacy one stays queryable with SQL. The speed comparison needs both pipelines to load the same blocks (D10). |
| D10 | What workload does the speed comparison use? | **The same Terra blocks for both pipelines.** About 1,000 consecutive Terra blocks (~330 transactions), saved once as old-format files (`/cosmos/base/tendermint/v1beta1/blocks/{h}`, which includes `sdk_block`) for the old pipeline, while the new indexer reads the same heights from the replay cache. | One extra request per block when preparing the set. The old pipeline's time includes its 2 HTTP decode calls per transaction; the report states this rather than hiding it. Compared: blocks/s, tx/s, and that both schemas end up with the same blocks, transactions and messages. **Blocker found:** the old schema rejects every Terra block (`proposer_address` hard-coded to Migaloo's 53 characters, see section 3), and the line-5 fixer then damages the files, so the old validator must accept Terra before this benchmark can run. |
| D11 | What happens to the line-5 fixer? | **Fix only a known bad line 5.** The fixer stays, but deletes line 5 only when the schema error is about line 5's field (`block_id.part_set_header.total`); any other schema failure exits 8 without changing the file. The `sdk_block.header.proposer_address` rule is generalized to accept any chain's validator consensus address instead of exactly 53 characters. | Valid Terra blocks pass the old validator, which unblocks the D10 benchmark. A block that fails for another reason is reported and left intact, so repeated runs no longer delete a line each time. The fixer must read the error's path from jsonschema (`ValidationError.absolute_path`), and its tests gain two cases: an unrelated schema failure leaves the file unchanged, and a real Terra block passes. Applies to the old pipeline only; the new indexer reads JSON from nodes, not hand-edited files. |
| D12 | What role does Migaloo play? | **Fixtures only.** The 38 Migaloo test blocks and the decoded fixture stay as offline test data for both pipelines; the new indexer supports only `phoenix-1`. | `chain_id` stays part of every key (blocks, transactions, checkpoints), so adding a chain later is configuration rather than a redesign. Tests exercise two chains' data (Migaloo fixtures, Terra replay cache), which keeps the code from assuming one address prefix or address length, the same class of bug as the Migaloo-only `proposer_address` rule. |
| D13 | How is the project run locally? | **Docker Compose for everything.** One `docker-compose.yml` with `postgres`, `indexer` and `api` services, so `docker compose up` starts the whole project. The old pipeline (D8) runs as a one-off container whose image includes `psql` and `jq`. | Only Docker is needed on the host. Database settings come from environment variables rather than only `info.json`, because inside Compose the host is `postgres`, not `localhost`; the old scripts need a way to read the same settings (D9 already touches them for the schema). The replay cache (D5) is a mounted folder so it survives rebuilds, and PostgreSQL data lives in a named volume. The README's `docker run` instructions are replaced by the Compose ones when this is built. |
| D14 | How does the new indexer verify what it writes? | **In-transaction count checks plus a sampled `verify` command.** Counts are checked against the source before each block commits, and a mismatch rolls the block back into `failed_blocks`. `verify` re-fetches a random sample of heights and compares field by field. | Removes the old pipeline's per-transaction verification cost (2 extra processes and a second decode call per transaction) from the normal path. Count checks catch dropped or duplicated rows, the kind of bug fixed in section 2 (#2, #5), but not a wrong value in a field; the sampled command covers that, at a sample size you choose. Run against the replay cache (D5), it checks the indexer's own writes without adding load on public nodes; run against the network, it also catches a node that served different data. |
| D15 | Where is the GraphQL API reachable? | **localhost only.** The API binds to 127.0.0.1 (in Compose, its port is published only on the host's loopback interface). | No authentication needed. Query depth and complexity limits are not required at first, since only the machine's own user can reach the API; they become necessary if it is ever exposed. |
| D16 | Backfill and head-following: which comes first? | **Backfill first, then follow the head.** The indexer starts 25,000 blocks below the head and works upward; once caught up, the same workers poll for new blocks. | One ascending stream, so no gap to stitch together (D3's concern is gone), and the contiguous checkpoint (5.2) covers both phases. Data lags the chain until the catch-up finishes. To ever catch up, the indexer must run faster than the chain, about 0.17 blocks/s (one block per ~5.8 s); the old pipeline's 0.45 blocks/s is only about 2.6 times that. |
| D17 | How are schema changes for the new indexer managed? | **Alembic**, with each migration written by hand as SQL in `op.execute()` and a matching `downgrade()`. No SQLAlchemy model classes, so autogenerate is not used. | Adds SQLAlchemy and Alembic as dependencies (Alembic connects through SQLAlchemy using the existing psycopg2 driver), plus `alembic.ini` and `env.py`. The indexer and API keep using psycopg2 directly. The `alembic_version` table lives in the new indexer's schema, so the `legacy` schema and `Txs.sql` are untouched (D9). In Compose (D13), a one-off migrate step runs `alembic upgrade head` before the indexer and API start. Tests for the new indexer build their database by running the migrations, which also checks that every migration applies cleanly from empty. |
| D18 | Which test framework? | **pytest.** Layers are selected with markers (`unit`, `component`, `integration`, `e2e`, `legacy`); shared setup (migrated database, replay cache, fake sources) lives in fixtures; per-handler cases use `parametrize`. | pytest runs the existing unittest suite unchanged (checked: all 27 pass under `python3 -m pytest tests`), so the legacy tests need no rewrite and only gain a `legacy` marker. Adds pytest as a dev dependency (pytest-cov comes with the coverage decision). `python3 -m unittest discover -s tests` keeps working for the legacy tests. |
| D19 | Where do component and integration tests get PostgreSQL? | **A `postgres-test` service in Docker Compose** (D13): the same PostgreSQL 16 image as the real database, on its own port bound to 127.0.0.1, with its data on tmpfs so it is thrown away when stopped. | Start it with `docker compose up -d postgres-test`, then run `pytest`. Database-backed layers **fail loudly** if it isn't reachable, instead of skipping, so a missing database can't pass for green; unit tests never touch it. A session fixture runs `alembic upgrade head` once per test run. The legacy tests can point their `INDEXER_TEST_DB_*` settings at the same service. tmpfs keeps it fast, and nothing it holds survives a restart, which is the point. |
| D20 | How are database tests isolated from each other? | **By layer.** Component tests run inside a transaction that is rolled back after each test. Integration and end-to-end tests, which commit from several connections and threads, truncate the indexer's tables after each test. Migrations run once per session. | Shapes the code: each insert function takes a cursor and **never commits**; only the block-level writer controls `BEGIN`/`COMMIT`/`ROLLBACK`. That is what lets a component test wrap an insert in a transaction it rolls back, and it matches D14 (one transaction per block). The truncate covers every table in the indexer's schema except `alembic_version`, with `CASCADE`. Integration tests therefore can't run in parallel against the same database. |
| D21 | What happens when a worker thread hits an error? | **Classify; bugs stop everything.** Transient errors (timeouts, 429/5xx, a dropped database connection) retry the block with backoff, then record it in `failed_blocks`. Bad data (a D14 count mismatch, a malformed response) goes straight to `failed_blocks`. An unexpected exception stops the run: no new heights are handed out, in-flight blocks finish or roll back, all threads are joined, and the process exits non-zero. | Exceptions in threads don't propagate on their own: the coordinator must watch each worker's future, and on an unexpected error set a shared stop event that workers check between blocks. Python threads can't be killed, so every HTTP request and database statement needs a timeout, or shutdown could hang. A broken connection is discarded (`putconn(conn, close=True)`) rather than returned to the pool. A failed height blocks the contiguous checkpoint until it succeeds, so a restart retries it automatically. The test cases are listed in 8.2. |
| D22 | How are threaded tests made deterministic? | **Scripted orderings plus one stress test.** The fake block source has a gate per height (`threading.Event`) so a test forces an exact order, e.g. hold 103, let 105 commit, then inject the crash. One stress test runs the threaded indexer many times with random delays and failures and checks the invariants after each run. | Fetch gates alone can't order *commits*, so the writer takes optional hook callbacks (e.g. `before_commit(height)`) that tests use to pause a block just before it commits; production passes none. Every threaded test has a hard timeout (the `pytest-timeout` plugin), so a deadlock fails instead of hanging the suite. The stress test uses a seeded random generator and prints the seed, so any failure can be replayed exactly; it is marked `slow` and checks: every height stored exactly once or in `failed_blocks`, a correct contiguous checkpoint, all connections back in the pool, and all threads joined. |
| D23 | What coverage target? | **Tiered and enforced:** 90% branch coverage for the correctness-critical modules (writer, verifier, checkpoint, error handling, handlers) and 80% overall, measured with pytest-cov over the unit, component and integration layers. Every one of the 35 handlers has at least one test. | Below either floor, the test run fails. `--cov-fail-under` only checks the overall total, so the 90% tier is a second `coverage report --include=<critical modules> --fail-under=90` step. End-to-end tests run the indexer as a separate process and don't count towards coverage. Coverage is a floor that catches untested code, not proof of good tests. |
| D24 | What test data is committed? | **A curated sample of ~50 Terra blocks** (~1 MB gzipped, in replay-cache format), hand-picked so most handler types and the edge cases appear: empty blocks, multi-message transactions, a failed transaction, a multi-coin fee. Plus expected-JSON files for the end-to-end GraphQL queries, and the existing Migaloo blocks and fixture. | The 25,000-block replay cache stays local and git-ignored. Blocks are picked by scanning the local cache; recent Terra blocks may not contain every one of the 35 types (e.g. `MsgStoreCode` or IBC connection handshakes are rare), so a type missing from the sample gets a hand-written message fixture for its unit test. Expected-JSON files are regenerated deliberately (a flag on the test run) and reviewed in the diff, never updated automatically. |
| D25 | Where and when does each layer run? | **GitHub Actions, every layer on every push and pull request**: unit, component, integration, end-to-end, the seeded stress test and legacy, with the coverage floors (D23). Locally, one command per layer (`pytest -m unit`, ...). | CI runs PostgreSQL 16 as a service container, the counterpart of the Compose `postgres-test` service (D19). Because everything runs on every push, the whole suite must stay fast (target: under 5 minutes) and **hermetic**: no test may call a public node, so the stress test runs a fixed number of seeded rounds and the old-vs-new speed benchmark (D10), which needs the network, is a separate manual command, not a test. The legacy shell tests need `psql` and `jq` on the runner. |
| D26 | Decode raw transaction bytes in block files? | **Yes, locally with protobuf** (revises D6 and ticket 01's "out of scope"). A decode step turns the base64 protobuf in `block.data.txs` into the same JSON a node's REST API returns, using Python classes generated from the chain's `.proto` files (Cosmos SDK, IBC, CosmWasm, Alliance). `python -m indexer decode <files>` writes `<height>.decoded.json` next to a block, and the files source decodes automatically when a block has raw bytes and no decoded file. | Works offline and doesn't depend on public nodes, which matters because Migaloo's are gone. Adds the `protobuf` runtime as a dependency; the generated code is committed, so `buf` (or `grpcio-tools`) is needed only to regenerate it, with module versions pinned to match the chain versions of the test blocks. Output must match the node's JSON exactly (snake_case field names, 64-bit integers as strings, enum names, default values included, `Any` expanded with `@type`); U12 checks this against the fixture the node produced. A type URL with no generated class makes the transaction undecodable, which is bad data (D21). The live REST path stays decoded by the node, and the old pipeline keeps its HTTP decoding. Delivered in ticket 15. |
| D27 | Fetch `block_results` for every block? | **Proposed, to confirm before ticket 16 is built: only for blocks that have transactions.** Learn which blocks are empty from CometBFT `/blockchain` (up to 20 headers per request, with `num_txs`), build empty blocks from the header entry, and fetch `block_results` for the non-empty blocks in JSON-RPC batches of at most 10. | Revises D4 ("for every block"): an empty block has no transaction outcomes to store, and block-level events were already skipped, so nothing stored is lost. Measured 2026-11-02: 72% of 4,484 recent blocks are empty, so requests per block fall from 2 to about 0.4 and the rate-limit ceiling at the default limits from about 5 to about 25 blocks/s. The check "results count equals transaction count" (D14) is replaced, for empty blocks, by the header's `num_txs` and empty `data_hash`; for non-empty blocks `num_txs` must equal the `txs/block` count. D5 gets one exception: replies that cover several heights (a `/blockchain` window, a batch) are cached per height, re-serialised, instead of byte for byte. Following the head is unaffected (one block per ~5.8 s). Delivered in ticket 16. |

---

## 8. Testing strategy

*Agreed in review; the decisions are D18 to D25 in section 7.*

### 8.1 Layers

| Layer | What it tests | Real dependencies | Replaced by fakes | Runs |
|---|---|---|---|---|
| **Unit** | Pure functions, no I/O | none | everything outside the function | every change; whole layer in seconds |
| **Component** | One component with its own real dependency: **verification of blocks and transactions**, and **each individual insert into PostgreSQL** | PostgreSQL (migrated with Alembic, D17) | block source, other components | every change |
| **Integration** | **Verification and inserts together**, block by block, **synchronously and with the thread pool**, including **error handling in worker threads** | PostgreSQL, connection pool, worker threads | block source (a controllable fake over the replay cache) | every change |
| **End-to-end** | The whole system: replay cache → indexer → PostgreSQL → GraphQL over HTTP | everything except the network (the replay cache stands in for nodes) | public nodes | every change (D25) |

The existing 27 tests (`tests/`) cover the old pipeline and stay as a fifth group, **legacy**, because the old pipeline is kept (D8).

### 8.2 Test cases

32 test functions, about 120 cases once parametrized: the 24 from the slimming in 8.6, plus I8 to I11 and E2, which surfaced when the plan was sliced into tickets (`docs/tickets/`), U12, added with D26, and U13 and I12, added with ticket 16 (D27). Every database-backed test in the integration layer ends by calling one shared **invariant checker**:

> every height in the run is stored exactly once or is in `failed_blocks`, never both; no block is partly written; the checkpoint equals the highest contiguous stored height; every pooled connection is back in the pool; every worker thread has exited.

**Unit** (no I/O)

| ID | Test | Cases |
|---|---|---|
| U1 | `test_parse_block` | Terra block, Migaloo block, empty block, multi-message transaction |
| U2 | `test_tx_hash` | known Terra transaction → known hash |
| U3 | `test_match_outcomes` | counts agree; `block_results` has one fewer result (bad data) |
| U4 | `test_classify_address` | user, contract, validator, blank, unknown, prefix containing `1` |
| U5 | `test_handler_maps_message` | one case per handler (35), from the curated sample or a hand-written fixture (D24) |
| U6 | `test_contiguous_checkpoint` | nothing done; in order; a gap; the gap filled |
| U7 | `test_rate_limiter` | burst up to capacity; refill over time (fake clock) |
| U8 | `test_error_policy` | transient then success; transient past the limit; bad data, no retry; unexpected exception re-raised (D21) |
| U9 | `test_endpoint_rotation` | a failing endpoint is skipped, then retried later |
| U10 | `test_count_rules` | all match; missing tx; extra tx; missing outcome; wrong message count (D14) |
| U11 | `test_replay_cache_roundtrip` | write then read returns the same bytes (D5) |
| U12 | `test_decode_matches_node` | the 3 raw transactions of Migaloo block 7027410, decoded locally, equal the JSON the node returned (the saved fixture); a transaction with a type URL that has no generated class is rejected as bad data (D26) |
| U13 | `test_range_plan` | a real `/blockchain` reply parses and an empty entry equals the full block; windows are aligned and truncated; a batch splits into chunks of 10; a missing height falls back (D27) |

**Component** (one component, real PostgreSQL, rolled back after each test, D20)

| ID | Test | Cases |
|---|---|---|
| C1 | `test_migrations` | upgrade from empty, downgrade to empty, upgrade again (D17) |
| C2 | `test_insert_is_idempotent` | block, transaction, `messages` row, typed row, address, outcome and events, fee coins, checkpoint: inserted twice → exactly one row, equal to the expected row, and the same id returned both times |
| C3 | `test_amount_above_64_bits` | an amount of 2^64 + 1 is stored and read back exactly (`NUMERIC`, 5.4) |
| C4 | `test_count_check_in_transaction` | the verifier, against rows written in an open transaction: clean block passes; missing tx, duplicate tx, missing outcome and wrong message count are each reported (D14) |
| C5 | `test_verify_command_finds_field_difference` | one changed field in a block, a transaction, a message (sampled `verify`, D14) |

**Integration** (verification and inserts together, real PostgreSQL, threads; truncated after each test, D20)

| ID | Test | Cases |
|---|---|---|
| I1 | `test_block_commits_or_rolls_back` | valid block commits; count mismatch rolls the whole block back into `failed_blocks` |
| I2 | `test_threaded_matches_sync` | the curated sample indexed by 1 worker and by 8 workers gives identical database contents (ignoring generated ids) |
| I3 | `test_out_of_order_checkpoint` | gates hold 103, let 105 commit: checkpoint stays at 102, then moves to 105 when 103 lands (D22) |
| I4 | `test_worker_errors` | transient recovers; transient exhausted; dropped connection (`pg_terminate_backend`); bad data; unexpected exception stops the run with a non-zero exit; SIGTERM stops it in order (D21) |
| I5 | `test_commit_is_atomic_under_crash` | a crash injected through `before_commit` while another worker commits: that block is all there or not there at all |
| I6 | `test_resume_after_crash` | crash between out-of-order blocks, restart: every block stored once, no gaps |
| I7 | `test_stress` *(slow)* | seeded random delays and faults over the curated sample, a fixed number of rounds; seed printed on failure (D22) |
| I8 | `test_fake_node_record_replay` | a local fake node with one endpoint returning 429: rotation, rate limit, recording; replaying the recording gives the same rows |
| I9 | `test_catch_up_then_follow` | catch up from S to a scripted head, follow new blocks, restart while following (D16) |
| I10 | `test_legacy_coexistence` | the old pipeline loads into `legacy` while the `indexer` schema stays unchanged (D9) |
| I11 | `test_benchmark_command` | 5-block hermetic benchmark against fakes; a parity mismatch exits non-zero (D10) |
| I12 | `test_range_fetch` | fake node with empty and non-empty blocks: same rows as the per-block path, exact request count `1 + N + ceil(N/10)`, a `num_txs` disagreement is bad data, `--no-ranges` and an endpoint without `/blockchain`, record then replay including empty blocks, prefetch with the rate limit (D27) |

**End-to-end** (separate indexer process, replay cache instead of the network)

| ID | Test | Cases |
|---|---|---|
| E1 | `test_graphql` | one indexing run of the curated sample plus the Migaloo fixtures, then each query compared with its expected-JSON file: block range, transaction by hash, messages by type, activity for an address, a failed transaction's outcome, a transaction from a Migaloo block that had only raw bytes (D26), cursor paging |
| E2 | `test_compose_stack` | `docker compose up` on the replay sample, query the API through the published port, run the legacy loader (D13) |

**Legacy:** the existing 27 tests, unchanged, marked `legacy` (D8, D18).

**Not tests:** the old-vs-new speed comparison (D10) and throughput benchmarks need the network or long runs, so they are separate commands that write a report, outside the test suite (D25).

### 8.3 Fault injection
A fake block source wraps the replay cache and can, on chosen heights: time out, return 429 or 5xx, return malformed JSON, return a `/block_results` with a different transaction count, or respond slowly. On the database side: kill a connection mid-transaction (`pg_terminate_backend`) and force a unique violation.

### 8.4 Gaps in the current tests
- Nothing exists yet for the new indexer; all 27 current tests target the old pipeline.
- In the old pipeline: the `check_file` repair path (`functions.checkLine`) and `verify_block.py` have no tests; only 4 of the 35 handlers are exercised (`cosmos_exec_msg`, `ibc_updateclient_msg`, `ibc_acknowledgement_msg`, `cosmos_vote_msg`); the multisend and grant side tables have no tests.

### 8.5 Open questions
Settled one at a time, newest decision in section 7:
1. ~~Test framework~~: pytest (D18).
2. ~~Where component and integration tests get PostgreSQL~~: a Compose `postgres-test` service (D19).
3. ~~Isolation between tests that use the database~~: rollback for component tests, truncate for integration and end-to-end (D20).
4. ~~Error handling in worker threads~~: classify; bugs stop everything (D21).
5. ~~Making threaded tests deterministic~~: scripted gates plus one seeded stress test (D22).
6. ~~Coverage targets~~: 90% branch on critical modules, 80% overall, enforced (D23).
7. ~~Committed test data~~: ~50 curated Terra blocks plus expected-JSON files (D24).
8. ~~Where and when each layer runs~~: GitHub Actions, every layer on every push (D25).

### 8.6 How the suite was slimmed

A first draft of these layers came to about **130 test functions**; the list in 8.2 has **24** (about 100 cases) and covers the same behaviour. The rules used:

1. **Test each behaviour once, at the lowest layer that can prove it.** Address rules are proved in U4 and never re-asserted in integration tests; integration tests check what only appears when components meet (transactions, threads, crashes).
2. **Parametrize data instead of copying tests.** 35 handler tests became one test with 35 cases (U5); 8 insert functions × 4 checks (32 tests) became one idempotency test with 8 cases (C2).
3. **Check invariants once, in one place.** One invariant checker, called at the end of every integration test, replaces each test asserting its own partial list. The stress test (I7) is then just "random scenario + invariant checker".
4. **Don't test the database or the libraries.** "JSONB comes back unchanged" and "a foreign key to a missing row fails" test PostgreSQL, not this code; they were dropped. The migration test (C1) covers that the schema is defined, and I2 covers that it's used correctly.
5. **Let one broad test replace many narrow ones when it fails clearly.** I2 (threaded equals synchronous, row by row) covers every insert path in both modes; a failure shows exactly which rows differ.
6. **One end-to-end run, many assertions on its output.** E1 indexes once (shared fixture) and checks each query against its own expected file, instead of one slow indexing run per query.
7. **Keep benchmarks and network calls out of the suite.** They make every run slow and flaky; D25 needs the suite hermetic.
8. **Keep the suite slim:** `pytest --durations=10` shows the slowest tests, the coverage report (`--cov-report=term-missing`) shows untested lines, and a test that has never failed when the code around it was broken is a candidate for removal (mutation testing with `mutmut` finds those).

The rules are kept, in a reusable form, in [`docs/TESTING_RULEBOOK.md`](docs/TESTING_RULEBOOK.md). The plan is broken into vertical-slice tickets in [`docs/tickets/`](docs/tickets/README.md).

---

## 9. Implementation notes (tickets 01 to 05)

Where the first five tickets were built differently from, or beyond, what the tickets say. None of these changes a decision in section 7.

| Ticket | Note |
|---|---|
| 01 | `test_blocks/` holds 29 of the 38 Migaloo blocks (the rest are in `test_blocks2/` and `test_blocks3/`). Only block 7027410 has a decoded fixture, so a run over `test_blocks/` indexes 1 block and reports 28 skipped until ticket 15. The files source looks for `<block file>.decoded.json`, then `<height>.decoded.json`, then `tests/fixtures/decoded/<height>.json` (override the folder with `INDEXER_DECODED_DIR`). |
| 01 | Block time is stored as `timestamptz`, which has microsecond precision; the node reports nanoseconds. |
| 01 | The legacy DB tests cannot share a database with the new schema yet: the old scripts create unqualified tables, and when the database user is called `indexer` they land in the `indexer` schema (the user's own schema is first on the default `search_path`). CI and the README run `pytest -m legacy` against a separate database until ticket 12 moves the old pipeline to a `legacy` schema (D9). |
| 02 | There are 35 typed tables **plus** the 2 side tables (37 in total); the ticket text can be read either way. |
| 02 | Handlers are grouped by module family (`bank.py`, `staking.py`, `ibc.py`, ...) rather than one module per type, and are declarative: a table, a column-to-path map and the address fields. Each is still a pure function from message JSON to a `HandlerResult`. |
| 02 | Typed rows keep address values as plain text columns (so `details` is readable on its own); the shared `address` table and the links come with ticket 03. Large blobs (IBC proofs, client headers, wasm byte code) stay only in `messages.raw`; `MsgStoreCode` keeps `wasm_byte_code_size`. Multi-coin `MsgSend` keeps the first coin in columns and all coins in `coins`. |
| 02 | GraphQL `Message.details` is a JSON object (the typed row, camelCase keys) rather than a union of 35 GraphQL types. Until cursor paging (ticket 11), the list queries take a `limit` (default 100, at most 1000). |
| 03 | Empty address strings are not stored or linked (`classify_address("")` still returns `blank`). Roles: `sender`, `receiver`, `input`, `output`, `granter`, `grantee`, `allowed`, `delegator`, `validator`, `validator_src`, `validator_dst`, `voter`, `contract`, `admin`, `signer`. IBC `signer` addresses are linked, which the old pipeline did not do. |
| 04 | The curated sample has 50 real `phoenix-1` blocks (1.1 MB gzipped) chosen from about 4,500 recent blocks. It covers 16 message types (one of them, `MsgGrantAllowance`, has no handler), 5 failed transactions, empty blocks, multi-message transactions and 6 consecutive heights (for the fake node). **No multi-coin fee turned up**, so that case is covered by a hand-made component test. `manifest.json` records why each block is there. |
| 04 | Follow-up `txs/block` pages are cached as `<height>.txs.1.json.gz`, `<height>.txs.2.json.gz`, ... Gzip files are written with `mtime=0`, so the same bytes give the same file. |
| 04 | The fee is no longer read from `tx_info`: `transaction_fees` holds every coin, and transactions without an outcome (Migaloo files) have NULL outcome columns. |
| 05 | `--from-height` is required with `--source rest` until ticket 10 adds the default start (head minus 25,000); `--to-height` is new and defaults to the chain head. Endpoints come from `INDEXER_ENDPOINTS` (a JSON list, with a per-endpoint `rate` and `burst`) and the cool-down from `INDEXER_ENDPOINT_COOLDOWN`. Waiting for a cool-down is not counted as a fetch attempt. |
| 05 | Checked once by hand against the real publicnode endpoints on 2026-11-02 (10 blocks fetched, recorded and replayed). No test calls a real node (D25). |
