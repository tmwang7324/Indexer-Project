"""cosmos.staking.v1beta1, cosmos.distribution.v1beta1, cosmos.slashing.v1beta1"""
from .spec import Handler, num

_DELEGATION_COLUMNS = {
    "delegator_address": "delegator_address", "validator_address": "validator_address",
    "denom": "amount.denom", "amount": num("amount.amount"),
}
_DELEGATION_ADDRESSES = (("delegator", "delegator_address"), ("validator", "validator_address"))

DELEGATE = Handler(
    name="cosmos_delegate_msg", type_url="/cosmos.staking.v1beta1.MsgDelegate", table="cosmos_delegate_msg",
    columns=_DELEGATION_COLUMNS, addresses=_DELEGATION_ADDRESSES)

UNDELEGATE = Handler(
    name="cosmos_undelegate_msg", type_url="/cosmos.staking.v1beta1.MsgUndelegate", table="cosmos_undelegate_msg",
    columns=_DELEGATION_COLUMNS, addresses=_DELEGATION_ADDRESSES)

BEGIN_REDELEGATE = Handler(
    name="cosmos_beginredelegate_msg", type_url="/cosmos.staking.v1beta1.MsgBeginRedelegate",
    table="cosmos_beginredelegate_msg",
    columns={
        "delegator_address": "delegator_address",
        "validator_src_address": "validator_src_address", "validator_dst_address": "validator_dst_address",
        "denom": "amount.denom", "amount": num("amount.amount"),
    },
    addresses=(("delegator", "delegator_address"), ("validator_src", "validator_src_address"),
               ("validator_dst", "validator_dst_address")),
)

EDIT_VALIDATOR = Handler(
    name="cosmos_editvalidator_msg", type_url="/cosmos.staking.v1beta1.MsgEditValidator",
    table="cosmos_editvalidator_msg",
    columns={
        "validator_address": "validator_address",
        "moniker": "description.moniker", "identity": "description.identity", "website": "description.website",
        "security_contact": "description.security_contact", "details": "description.details",
        "commission_rate": "commission_rate", "min_self_delegation": "min_self_delegation",
    },
    addresses=(("validator", "validator_address"),),
)

WITHDRAW_DELEGATOR_REWARD = Handler(
    name="cosmos_withdrawdelegatorreward_msg", type_url="/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward",
    table="cosmos_withdrawdelegatorreward_msg",
    columns={"delegator_address": "delegator_address", "validator_address": "validator_address"},
    addresses=_DELEGATION_ADDRESSES,
)

WITHDRAW_VALIDATOR_COMMISSION = Handler(
    name="cosmos_withdrawvalidatorcommission_msg",
    type_url="/cosmos.distribution.v1beta1.MsgWithdrawValidatorCommission",
    table="cosmos_withdrawvalidatorcommission_msg",
    columns={"validator_address": "validator_address"},
    addresses=(("validator", "validator_address"),),
)

UNJAIL = Handler(
    name="cosmos_unjail_msg", type_url="/cosmos.slashing.v1beta1.MsgUnjail", table="cosmos_unjail_msg",
    columns={"validator_addr": "validator_addr"},
    addresses=(("validator", "validator_addr"),),
)

HANDLERS = [DELEGATE, UNDELEGATE, BEGIN_REDELEGATE, EDIT_VALIDATOR, WITHDRAW_DELEGATOR_REWARD,
            WITHDRAW_VALIDATOR_COMMISSION, UNJAIL]
