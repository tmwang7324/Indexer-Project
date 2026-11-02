# 03 · Addresses and address activity

**Slice:** addresses in messages are stored once, classified, and linked to their messages with a role, so GraphQL can answer "everything involving address X" with one indexed lookup.

**Acceptance test (E2E):** `E1[address_activity]`: index the Migaloo fixtures, then `address(value: "migaloo1fc4kjfau480nr503yl0r8ml7vvn07d2r7ztjky") { type messages { ... } }` returns type `user` and the vote message with role `voter`.

**Depends on:** 02 · **Decisions:** D2, D12

## Scope
- **In:**
  - a migration adding `address` (unique on the value) and `message_addresses(message_id, address_id, role)`;
  - address extraction: each handler declares its address fields and their roles (no keyword guessing on key names);
  - `classify_address` ported for any bech32 prefix;
  - the API's `Address` type and `address(value)` query.
- **Out:** paging (11).

## Spec
- **Address fields:** each handler lists them explicitly, e.g. `MsgSend: from_address → sender, to_address → receiver`. This replaces the old substring rule (`'send' in key`, ...), which missed nested fields (section 3 of `REVAMP.md`).
- **Classification by length after the last `1`:** 38 → `user`; more than 38 → `contract`; containing `valoper` → `validator`; empty → `blank`; anything else → `Unknown`, logged. This must work for both the `terra` and `migaloo` prefixes.
- **Inserts:** addresses are inserted per block, de-duplicated, using `ON CONFLICT` plus a lookup; `created_at` is in UTC.

## Acceptance criteria
- [ ] The same address used in several messages is stored once.
- [ ] Every address field listed by a handler produces a `message_addresses` row with the right role.
- [ ] The address query returns the classification and the linked messages.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| E1 | e2e | `address_activity` |
| C2 | component | address (inserted twice → one row, same id) |
| U4 | unit | user, contract, validator, blank, unknown, prefix containing `1` |
