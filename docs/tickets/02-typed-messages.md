# 02 · Typed messages for all 35 types

**Slice:** every message gets a typed copy when a handler exists for its type, and GraphQL can list messages by type with their typed fields. Unknown types are still stored in `messages`, just without a typed copy (D2).

**Acceptance test (E2E):** `E1[messages_by_type]`: index the Migaloo fixtures, query `MsgVote` messages, and get `proposalId: 39, option: VOTE_OPTION_YES` for Polkachu's vote.

**Depends on:** 01 · **Decisions:** D2

## Scope
- **In:**
  - a migration adding the 35 typed tables, each keyed by `messages.message_id`, including the 2 side tables (grant allowlist, multisend outputs);
  - the handlers registry, loaded once from `type.json`; each handler is a pure function from message JSON to its typed row(s);
  - the API's `Message` type with a `type` field and a typed `details` field;
  - a `messages(type: ...)` query.
- **Out:** address columns in typed rows (03), paging (11).

## Spec
- **Porting the handlers:** the field mappings move from `types_script/*.py` into `indexer/handlers/`. They no longer open connections or build comments. `types_script/` is left untouched for the legacy pipeline (D8).
- **Writer:** for each message, insert the `messages` row, then the typed row if a handler exists. Both are in the block's transaction.
- **Unknown type:** a `messages` row only, plus a log line. No `new_type.txt`.
- **Nested messages:** a `MsgExec`'s inner messages are stored inside its raw JSON; they are not split into their own rows in this ticket.

## Acceptance criteria
- [ ] All 35 types in `type.json` have a handler and a test case.
- [ ] A block containing an unknown type stores it in `messages` and indexes the rest of the block.
- [ ] `messages(type: "/cosmos.gov.v1.MsgVote")` returns the typed vote fields.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| E1 | e2e | `messages_by_type` |
| C2 | component | typed row (one representative type) |
| U5 | unit | 35 cases, one per handler; types missing from the samples get a hand-written message fixture (D24) |
