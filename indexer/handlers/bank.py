"""cosmos.bank.v1beta1"""
from .spec import Handler, count, get, num, values

SEND = Handler(
    name="cosmos_send_msg", type_url="/cosmos.bank.v1beta1.MsgSend", table="cosmos_send_msg",
    columns={
        "from_address": "from_address", "to_address": "to_address",
        "denom": "amount.0.denom", "amount": num("amount.0.amount"),   # first coin; all coins in `coins`
        "coins": "amount",
    },
    addresses=(("sender", "from_address"), ("receiver", "to_address")),
)


def _multisend_outputs(message: dict) -> list:
    rows = []
    for i, out in enumerate(values(message, "outputs[]")):
        rows.append(("cosmos_multisend_outputs", {
            "output_index": i, "address": out.get("address"),
            "denom": get(out, "coins.0.denom"), "amount": get(out, "coins.0.amount"),
            "coins": out.get("coins"),
        }))
    return rows


MULTISEND = Handler(
    name="cosmos_multisend_msg", type_url="/cosmos.bank.v1beta1.MsgMultiSend", table="cosmos_multisend_msg",
    columns={"input_count": count("inputs"), "output_count": count("outputs"), "inputs": "inputs"},
    addresses=(("input", "inputs[].address"), ("output", "outputs[].address")),
    children=_multisend_outputs, side_tables=("cosmos_multisend_outputs",),
)

HANDLERS = [SEND, MULTISEND]
