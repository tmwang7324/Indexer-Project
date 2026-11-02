# 11 · GraphQL paging, filters and batching

**Slice:** the full read API from section 5.5 of `REVAMP.md`:
- `blocks(range, first, after)`;
- `transactions(filter: {heightRange, messageType, address}, first, after)`;
- `address(value) { messages(first, after) }`.

Paging is cursor-based, ordered by `(height, tx index, msg_index)`. Related objects are fetched in batches, so a page doesn't trigger one query per row.

**Acceptance test (E2E):** `E1[blocks_range, cursor_paging]`: over the indexed curated sample, walk `transactions(first: 5)` page by page to the end. Every transaction appears exactly once and in order. The final page has `hasNextPage: false`. The concatenated pages equal the expected-JSON file.

**Depends on:** 03, 04 · **Decisions:** D15

## Scope
- **In:**
  - Relay-style connections (`edges`, `node`, `pageInfo`), with opaque cursors encoding the sort key;
  - filters;
  - Strawberry DataLoaders for transaction → messages, message → addresses, and transaction → block;
  - binding to 127.0.0.1 only.
- **Out:** authentication and query-cost limits (not needed while localhost-only, D15).

## Spec
- **Page size:** `first` is capped (e.g. 100) and defaults to 20; `after` is the cursor of the last edge seen.
- **Batching check:** a test counts the SQL statements a page query issues. For a page of 20 transactions with their messages and addresses, it must be a small constant (e.g. ≤ 4), not 20 × something.

## Acceptance criteria
- [ ] Paging returns every item once, in order, for page sizes 1, 5 and 100.
- [ ] Filters by height range, message type and address return exactly the expected items.
- [ ] A page of 20 transactions issues at most the constant number of SQL statements.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| E1 | e2e | `blocks_range`, `cursor_paging` (plus a statement-count assertion on one page) |
