"""cosmos.gov and alliance"""
from .spec import Handler, num

VOTE = Handler(
    name="cosmos_vote_msg", type_url="/cosmos.gov.v1.MsgVote", table="cosmos_vote_msg",
    columns={"proposal_id": "proposal_id", "voter": "voter", "option": "option", "metadata": "metadata"},
    addresses=(("voter", "voter"),),
)

VOTE_BETA1 = Handler(
    name="cosmos_vote_beta1_msg", type_url="/cosmos.gov.v1beta1.MsgVote", table="cosmos_vote_beta1_msg",
    columns={"proposal_id": "proposal_id", "voter": "voter", "option": "option"},
    addresses=(("voter", "voter"),),
)

_ADDRESSES = (("delegator", "delegator_address"), ("validator", "validator_address"))
_COLUMNS = {
    "delegator_address": "delegator_address", "validator_address": "validator_address",
    "denom": "amount.denom", "amount": num("amount.amount"),
}

ALLIANCE_DELEGATE = Handler(
    name="alliance_delegate_msg", type_url="/alliance.alliance.MsgDelegate", table="alliance_delegate_msg",
    columns=_COLUMNS, addresses=_ADDRESSES)

ALLIANCE_UNDELEGATE = Handler(
    name="alliance_undelegate_msg", type_url="/alliance.alliance.MsgUndelegate", table="alliance_undelegate_msg",
    columns=_COLUMNS, addresses=_ADDRESSES)

ALLIANCE_REDELEGATE = Handler(
    name="alliance_redelegate_msg", type_url="/alliance.alliance.MsgRedelegate", table="alliance_redelegate_msg",
    columns={
        "delegator_address": "delegator_address",
        "validator_src_address": "validator_src_address", "validator_dst_address": "validator_dst_address",
        "denom": "amount.denom", "amount": num("amount.amount"),
    },
    addresses=(("delegator", "delegator_address"), ("validator_src", "validator_src_address"),
               ("validator_dst", "validator_dst_address")),
)

ALLIANCE_CLAIM = Handler(
    name="alliance_claimdelegationrewards_msg", type_url="/alliance.alliance.MsgClaimDelegationRewards",
    table="alliance_claimdelegationrewards_msg",
    columns={"delegator_address": "delegator_address", "validator_address": "validator_address", "denom": "denom"},
    addresses=_ADDRESSES,
)

HANDLERS = [VOTE, VOTE_BETA1, ALLIANCE_DELEGATE, ALLIANCE_UNDELEGATE, ALLIANCE_REDELEGATE, ALLIANCE_CLAIM]
