# 15 · Decode raw transaction bytes locally

**Slice:** block files that carry only raw transaction bytes (the base64 protobuf in `block.data.txs`, as in all 38 Migaloo test blocks) are decoded in-process, with generated protobuf classes, into the same JSON a node's REST API returns, so every Migaloo test block can be indexed without a network or a public node (D26).

**Acceptance test (E2E):** `E1[raw_bytes_block]`: delete any saved decoded files, index all of `test_blocks*/` from files, then query `transaction(hash: "4D1669CC9502324F6F15E76B5EFCB7EE40ADEB7FBD688F174CBE9D28B04E50EE")`. This is transaction 1 of block 1216594, which has no saved decoded fixture. The query returns its 2 `MsgWithdrawDelegatorReward` messages, compared with an expected-JSON file. All 38 blocks and 48 transactions are stored.

**Depends on:** 01 · **Decisions:** D6, D21, D26

## Scope
- **In:**
  - generated Python protobuf classes for every message type in `type.json` plus the transaction envelope (`TxRaw`, `TxBody`, `AuthInfo`, signer info, public keys), from pinned versions of the Cosmos SDK, IBC, CosmWasm and Alliance proto modules;
  - a type registry mapping each type URL to its class, so `Any` fields (messages, public keys, nested `MsgExec` messages) expand;
  - `indexer/decode.py`;
  - the `python -m indexer decode <files>` command;
  - automatic decoding in the files source;
  - a short `docs/` note on regenerating the classes.
- **Out:**
  - decoding the `data` field of transaction results (still not stored);
  - changing the live REST path (still decoded by the node, D6);
  - changing the old pipeline's HTTP decoding.

## Spec
- **Input:** the base64 string from `block.data.txs`. Parse it as `TxRaw`, then decode `body_bytes` into `TxBody` and `auth_info_bytes` into `AuthInfo`, and keep `signatures` as base64.
- **Output shape:** `{"tx": {"body": …, "auth_info": …, "signatures": […]}}`, identical to the node's `/cosmos/tx/v1beta1/decode` response:
  - original snake_case field names;
  - 64-bit integers as strings;
  - enums as their names;
  - bytes as base64;
  - fields with default values included;
  - each `Any` expanded as `{"@type": url, …fields}`.
- **Files:** `decode` writes `<height>.decoded.json` next to the block file. The files source uses that file when present; otherwise it decodes in memory and continues. It doesn't write files unless the command is run.
- **Unknown type URL:** raises a bad-data error naming the URL (D21). The block goes to `failed_blocks` once ticket 06 exists, and before that it fails the run with a clear message.
- **Regeneration:** `buf generate`, with the module versions recorded in a lock file. Choose versions matching the chain versions of the test blocks (heights 1.19M–7.57M span several Migaloo upgrades, so check that the decoded output matches for blocks from each era). The generated code is committed, so installing the indexer needs only the `protobuf` runtime.

## Acceptance criteria
- [ ] Decoding block 7027410's 3 raw transactions locally gives JSON equal to the saved node fixture (`tests/fixtures/decoded/7027410.json`).
- [ ] All 38 Migaloo test blocks decode and index with no network access; 48 transactions are stored.
- [ ] A transaction with an unregistered type URL fails with an error naming the URL, and no partial block is written.

## Tests in this ticket
| ID | Layer | Cases |
|---|---|---|
| E1 | e2e | `raw_bytes_block` |
| U12 | unit | block 7027410's 3 transactions equal the node's JSON; an unregistered type URL is rejected as bad data |
