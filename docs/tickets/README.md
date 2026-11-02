# Revamp tickets

The plan in `REVAMP.md`, broken into **vertical slices**. Each ticket delivers something that works from input to output, and each is accepted by an **integration** or **end-to-end** test (the "Acceptance test" line in each ticket). Unit and component tests come with the ticket that needs them. Test IDs (U1, C2, I4, E1, ...) refer to the catalog in `REVAMP.md` section 8.2; decisions (D1–D25) to section 7. Testing follows `docs/TESTING_RULEBOOK.md`.

## Order

```
01 Tracer bullet ──┬─> 15 Decode raw bytes locally
                   ├─> 02 Typed messages ──> 03 Addresses ──┐
                   │                                         ├─> 11 GraphQL paging & filters
                   ├─> 04 Terra from replay cache ──┬────────┘
                   │                                ├─> 05 Record from live nodes
                   │                                └─> 06 Verification ──> 07 Checkpoint & resume
                   │                                                           └─> 08 Thread pool ──> 09 Worker errors ──> 10 Catch up, then follow
                   ├─> 12 Legacy coexistence ──> 14 Benchmark command
                   └─> 13 Compose for everything   (after 10 and 11)
```

| # | Ticket | Acceptance | Depends on |
|---|---|---|---|
| 01 | [Tracer bullet: a Migaloo block, queried through GraphQL](01-tracer-bullet.md) | E2E | none |
| 02 | [Typed messages for all 35 types](02-typed-messages.md) | E2E | 01 |
| 03 | [Addresses and address activity](03-addresses.md) | E2E | 02 |
| 04 | [Terra blocks from the replay cache, with outcomes and events](04-terra-replay-outcomes.md) | E2E | 01 |
| 05 | [Record from live nodes](05-record-from-live-nodes.md) | Integration | 04 |
| 06 | [In-transaction verification and `failed_blocks`](06-verification.md) | Integration | 04 |
| 07 | [Checkpoint and resume](07-checkpoint-resume.md) | Integration | 06 |
| 08 | [Thread pool with identical results](08-thread-pool.md) | Integration | 07 |
| 09 | [Worker error handling and orderly shutdown](09-worker-errors.md) | Integration | 08 |
| 10 | [Catch up, then follow the head](10-catch-up-then-follow.md) | Integration | 05, 09 |
| 11 | [GraphQL paging, filters and batching](11-graphql-paging.md) | E2E | 03, 04 |
| 12 | [Legacy pipeline coexistence](12-legacy-coexistence.md) | Integration | 01 |
| 13 | [Compose for everything](13-compose-everything.md) | E2E | 10, 11, 12 |
| 14 | [Old-vs-new benchmark command](14-benchmark.md) | Integration | 04, 12 |
| 15 | [Decode raw transaction bytes locally](15-decode-raw-bytes.md) | E2E | 01 |

## Shared conventions

**Layout**
```
indexer/            the new service (package)
  sources/          files.py, replay.py, rest.py
  parse.py          one parse per block → Block / Transaction / Message objects
  decode.py         raw transaction bytes → node-identical JSON (D26)
  proto/            generated protobuf classes (committed; regenerate with buf)
  handlers/         one module per message type; each returns its typed row
  writer.py         one database transaction per block; inserts take a cursor and never commit
  verify.py         count checks (D14) and the sampled verify command
  checkpoint.py     contiguous-height checkpoint
  run.py            CLI entry point: python -m indexer ...
api/                FastAPI + Strawberry GraphQL (read-only, localhost)
migrations/         Alembic, hand-written SQL in op.execute() (D17)
tests/              legacy tests stay here unchanged (marker: legacy)
tests/indexer/      unit/ component/ integration/ e2e/ + conftest.py
```

**CLI** (grows ticket by ticket)
```
python -m indexer run --source files:<dir> | replay:<dir> | rest [--record <dir>] [--from-height N] [--workers N]
python -m indexer verify --sample N [--source ...]
python -m indexer decode <block files>
```

**Database:** the new indexer owns the `indexer` schema; the old pipeline uses `legacy` (D9). Settings come from environment variables (`INDEXER_DB_HOST`, `INDEXER_DB_PORT`, `INDEXER_DB_NAME`, `INDEXER_DB_USER`, `INDEXER_DB_PASSWORD`) (D13).

**Definition of done (every ticket)**
- The acceptance test and all tests listed in the ticket pass in CI, along with every earlier test (D25).
- Coverage floors hold: 90% branch on critical modules, 80% overall (D23).
- New tests follow the rulebook's pre-merge checklist.
- `REVAMP.md` is updated if the ticket changed a decision.

## Traceability

**Every catalog test has an owner** (a ticket that adds cases to an existing test is listed after the slash):

| Test | Ticket | Test | Ticket | Test | Ticket |
|---|---|---|---|---|---|
| U1 | 01 / 04 | U9 | 05 | I1 | 01 / 06 |
| U2 | 01 | U10 | 06 | I2 | 08 |
| U3 | 04 | U11 | 04 | I3 | 08 |
| U4 | 03 | C1 | 01 | I4 | 09 |
| U5 | 02 | C2 | 01 / 02 / 03 / 04 / 07 | I5 | 09 |
| U6 | 07 | C3 | 04 | I6 | 07 / 08 |
| U7 | 05 | C4 | 06 | I7 | 09 |
| U8 | 09 | C5 | 06 | E1 | 01 / 02 / 03 / 04 / 11 / 15 |
| I8 | 05 | I9 | 10 | I10 | 12 |
| I11 | 14 | E2 | 13 | U12 | 15 |

**Every decision has a home:** D1 all · D2 01, 02, 03 · D3 10 · D4 04 · D5 04, 05 · D6 04, 15 · D7 07, 08 · D8 12 · D9 01, 12, 14 · D10 14 · D11 12 · D12 01, 03 · D13 01, 12, 13 · D14 06 · D15 01, 11, 13 · D16 10 · D17 01 · D18 01 · D19 01 · D20 01 · D21 09, 15 · D22 08, 09 · D23 01 · D24 04 · D25 01 · D26 15
