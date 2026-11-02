# Slim Testing Rulebook

A reusable guide for building test suites that stay small, fast and trustworthy. The examples come from the indexer revamp (`REVAMP.md`, section 8), where these rules cut a first draft of about 130 test functions to 24 with the same coverage of behaviour.

**The one question behind every rule:** *if this test failed, what would I learn that another test hasn't already told me?* If the answer is "nothing", merge it into a parametrized case or delete it.

---

## 1. The four layers

| Layer | Proves | Real | Faked | Speed |
|---|---|---|---|---|
| **Unit** | A pure function's logic | nothing | everything outside the function | milliseconds |
| **Component** | One component works with its own real dependency | that dependency (e.g. the database) | other components | tens of milliseconds |
| **Integration** | Components work *together*: transactions, threads, retries, crashes | database, pools, threads | the outside world (network, nodes) | seconds |
| **End-to-end** | The system works as a user sees it | everything you own | only third parties, replaced by recordings | seconds to minutes |

**Choosing the layer:** put each behaviour in the **lowest** layer that can prove it.

- Can it be proved with inputs and outputs alone? → **unit**.
- Does it need the real database (or file system, or queue), but only one component? → **component**.
- Does it only show up when components meet (one transaction across several steps, concurrency, failure and recovery)? → **integration**.
- Is it about what a user or client observes? → **end-to-end**.

*Example:* address classification (`terra1…` is a user, `…valoper…` is a validator) is pure logic, so it lives in unit tests only. "A count mismatch rolls back the whole block" needs the writer and verifier together inside one database transaction, so it's integration.

---

## 2. The rules

### Rule 1: Test each behaviour once, at the lowest layer that can prove it
- **Why:** the same assertion at three layers triples the maintenance and makes one bug fail many tests.
- **How:** higher layers check only what is *new* at that layer: composition, transactions, concurrency, user-visible output.
- **Anti-pattern:** re-checking address types in every integration test "just in case".

### Rule 2: Parametrize data instead of copying tests
- **Why:** 35 near-identical functions hide which cases differ and drift apart over time.
- **How:** one test function plus a table of cases with readable ids.

```python
@pytest.mark.parametrize("case", HANDLER_CASES, ids=lambda c: c.type)
def test_handler_maps_message(case):
    assert HANDLERS[case.type](case.message) == case.expected_row
```

- *Example:* 35 handler tests became 1 test with 35 cases; 8 insert functions × 4 checks (32 tests) became 1 idempotency test with 8 cases.

### Rule 3: Write invariants once and check them everywhere
- **Why:** when each test asserts its own partial list of "things that must be true", gaps creep in.
- **How:** one invariant checker, called at the end of every integration test. A stress test then needs no assertions of its own: random scenario + checker.

```python
def check_invariants(db, pool):
    assert db.heights_stored_once_or_failed()     # never both, never twice
    assert db.no_partial_blocks()
    assert db.checkpoint() == db.highest_contiguous_height()
    assert pool.all_connections_returned()
    assert all_worker_threads_exited()
```

### Rule 4: Don't test the database, the framework or the libraries
- **Why:** PostgreSQL already guarantees that JSONB round-trips and foreign keys reject orphans. Testing that tests *them*, not you.
- **How:** test that *your* schema is defined (a migration test: upgrade, downgrade, upgrade) and that *your* code uses it correctly (integration tests).
- **Keep** a test of library behaviour only when you depend on a surprising detail, e.g. `INSERT … ON CONFLICT DO NOTHING RETURNING id` returns **no row** on conflict.

### Rule 5: Let one broad test replace many narrow ones, if its failure is precise
- **Why:** a single comparison can exercise dozens of paths.
- **How:** compare whole outputs and make the failure message show the exact difference.
- *Example:* "8 worker threads produce exactly the same database rows as 1 worker" covers every insert path in both modes; on failure it prints the rows that differ.
- **Limit:** if a broad test's failure only says "something is different somewhere", split it.

### Rule 6: Do expensive setup once, then make many assertions on its output
- **Why:** re-indexing for every GraphQL query multiplies the slowest step.
- **How:** a module- or session-scoped fixture runs the expensive step once, and each check is its own parametrized case against the shared result.

### Rule 7: Keep the suite hermetic, and keep benchmarks out of it
- **Why:** a test that calls a live service fails when that service is slow, rate-limited or gone, and then nobody trusts red builds.
- **How:** record real responses once and replay them; run a local fake server for HTTP-level behaviour. Benchmarks and anything needing the network are separate commands that write reports, not tests.

### Rule 8: Make concurrency deterministic
- **Why:** timing-dependent tests pass or fail at random.
- **How:**
  - **Gates:** fakes expose a `threading.Event` per item, so a test forces an exact order (hold block 103, let 105 commit).
  - **Hooks:** production code takes optional callbacks at the critical points (e.g. `before_commit(height)`) that tests use to pause or crash; production passes none.
  - **Hard timeouts** on every threaded test (`pytest-timeout`), so a deadlock fails instead of hanging.
  - **One seeded stress test** with random delays and faults, plus the invariant checker; print the seed so any failure replays exactly.

### Rule 9: Isolate by what the code under test does with transactions
- **Component tests:** wrap each test in a transaction and roll it back. Fast, nothing to clean up. This requires that the code under test **never commits by itself**: insert functions take a cursor; only the top-level unit of work commits.
- **Integration and end-to-end tests:** the code commits from several connections or threads, so truncate the tables after each test.
- **Fail loudly** when the test database is missing. A skipped test that looks green is worse than a red one.

### Rule 10: Real data where it matters, synthetic where it's rare
- Commit a **small curated sample** of real data, hand-picked to cover the edge cases (empty input, multi-item, a failure, an unusual format).
- Write **hand-made fixtures** for cases the sample doesn't contain.
- **Expected-output (golden) files** are regenerated only on purpose (a flag) and reviewed in the diff, never updated automatically.

### Rule 11: Coverage is a floor, not a goal
- Tier it: e.g. 90% branch coverage for correctness-critical modules, 80% overall, enforced so the run fails below it.
- High coverage with weak assertions proves nothing. That's what mutation testing (`mutmut`) is for: it breaks the code on purpose and reports tests that still pass.

---

## 3. Slimming review (run every few months, or when the suite feels slow)

1. `pytest --durations=10`: are the slowest tests slow for a reason?
2. `pytest --cov --cov-report=term-missing`: which lines does no test run? Add a case, or delete dead code.
3. **Duplicates across layers** (Rule 1): grep for the same assertion in more than one layer.
4. **Copy-pasted tests** (Rule 2): several functions with the same body and different data → parametrize.
5. **Library tests** (Rule 4): does this test fail if *our* code is wrong?
6. **Tests that never fail:** run `mutmut` on the critical modules; a test that survives every mutation checks nothing.
7. **Network or wall-clock dependencies** (Rules 7, 8): any `sleep`, live URL or `datetime.now()` in a test is a flake waiting to happen.

---

## 4. Questions to settle when starting a new suite

Decide these up front, one at a time, and write the answers down:

1. **Framework?** (pytest: markers per layer, fixtures, parametrize; it also runs old unittest suites unchanged.)
2. **Where does the test database come from?** (A pinned container on its own port, failing loudly when absent.)
3. **How are database tests isolated?** (Rollback for component tests, truncate for integration and end-to-end.)
4. **What happens when a worker errors?** Classify errors (transient → retry; bad data → record and continue; bug → stop everything), then test each class.
5. **How are concurrent tests made deterministic?** (Gates + hooks + timeouts + one seeded stress test.)
6. **Coverage floors?** (Tiered, enforced.)
7. **What test data is committed?** (A curated real sample + hand-written fixtures + reviewed golden files.)
8. **Where and when does each layer run?** If everything runs on every push, the suite must stay hermetic and fast.

---

## 5. Pre-merge checklist for a new test

- [ ] It's in the lowest layer that can prove the behaviour.
- [ ] It isn't asserting something another test already proves.
- [ ] Repeated shapes are parametrized, with readable case ids.
- [ ] Integration tests end with the shared invariant checker.
- [ ] No network, no `sleep`, no real clock; concurrency is gated, and the test has a timeout.
- [ ] Its failure message says exactly what differs.
- [ ] It fails when the code it covers is broken (try it once).
