"""cosmos.authz.v1beta1"""
from .spec import Handler, count, values


def _allowlist(message: dict) -> list:
    return [("cosmos_grant_allowlist", {"position": i, "address": a})
            for i, a in enumerate(values(message, "grant.authorization.allow_list[]"))]


EXEC = Handler(
    name="cosmos_exec_msg", type_url="/cosmos.authz.v1beta1.MsgExec", table="cosmos_exec_msg",
    columns={"grantee": "grantee", "msg_count": count("msgs")},
    # the inner messages stay inside messages.raw; they are not split into their own rows
    addresses=(("grantee", "grantee"),),
)

GRANT = Handler(
    name="cosmos_grant_msg", type_url="/cosmos.authz.v1beta1.MsgGrant", table="cosmos_grant_msg",
    columns={
        "granter": "granter", "grantee": "grantee",
        "authorization_type": "grant.authorization.@type",
        "expiration": "grant.expiration",
        "authorization_kind": "grant.authorization.authorization_type",   # staking authorizations
        "msg": "grant.authorization.msg",                                 # generic authorizations
        "max_tokens": "grant.authorization.max_tokens",
    },
    addresses=(("granter", "granter"), ("grantee", "grantee"), ("allowed", "grant.authorization.allow_list[]")),
    children=_allowlist, side_tables=("cosmos_grant_allowlist",),
)

REVOKE = Handler(
    name="cosmos_revoke_msg", type_url="/cosmos.authz.v1beta1.MsgRevoke", table="cosmos_revoke_msg",
    columns={"granter": "granter", "grantee": "grantee", "msg_type_url": "msg_type_url"},
    addresses=(("granter", "granter"), ("grantee", "grantee")),
)

HANDLERS = [EXEC, GRANT, REVOKE]
