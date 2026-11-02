"""cosmwasm.wasm.v1. The embedded contract message stays in messages.raw; the typed row keeps its action name."""
from .spec import Handler, decoded_size, first_key, num

EXECUTE = Handler(
    name="cosmwasm_executecontract_msg", type_url="/cosmwasm.wasm.v1.MsgExecuteContract",
    table="cosmwasm_executecontract_msg",
    columns={"sender": "sender", "contract": "contract", "action": first_key("msg"), "funds": "funds"},
    addresses=(("sender", "sender"), ("contract", "contract")),
)

INSTANTIATE = Handler(
    name="cosmwasm_instantiatecontract_msg", type_url="/cosmwasm.wasm.v1.MsgInstantiateContract",
    table="cosmwasm_instantiatecontract_msg",
    columns={"sender": "sender", "admin": "admin", "code_id": num("code_id"), "label": "label", "funds": "funds"},
    addresses=(("sender", "sender"), ("admin", "admin")),
)

INSTANTIATE2 = Handler(
    name="cosmwasm_msg_instantiate_contract2", type_url="/cosmwasm.wasm.v1.MsgInstantiateContract2",
    table="cosmwasm_instantiatecontract2_msg",
    columns={"sender": "sender", "admin": "admin", "code_id": num("code_id"), "label": "label", "funds": "funds",
             "salt": "salt", "fix_msg": "fix_msg"},
    addresses=(("sender", "sender"), ("admin", "admin")),
)

STORE_CODE = Handler(
    name="cosmwasm_storecode_msg", type_url="/cosmwasm.wasm.v1.MsgStoreCode", table="cosmwasm_storecode_msg",
    columns={"sender": "sender", "wasm_byte_code_size": decoded_size("wasm_byte_code"),
             "instantiate_permission": "instantiate_permission"},
    addresses=(("sender", "sender"),),
)

MIGRATE = Handler(
    name="cosmos_migrate_contract", type_url="/cosmwasm.wasm.v1.MsgMigrateContract",
    table="cosmwasm_migratecontract_msg",
    columns={"sender": "sender", "contract": "contract", "code_id": num("code_id"), "action": first_key("msg")},
    addresses=(("sender", "sender"), ("contract", "contract")),
)

HANDLERS = [EXECUTE, INSTANTIATE, INSTANTIATE2, STORE_CODE, MIGRATE]
