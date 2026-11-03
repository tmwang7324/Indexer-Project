"""ibc.core and ibc.applications. Proofs and client headers are large; they stay only in messages.raw."""
from .spec import PACKET, PROOF_HEIGHT, Handler

TRANSFER = Handler(
    name="ibc_transfer_msg", type_url="/ibc.applications.transfer.v1.MsgTransfer", table="ibc_transfer_msg",
    columns={
        "sender": "sender", "receiver": "receiver",
        "source_port": "source_port", "source_channel": "source_channel",
        "token_denom": "token.denom", "token_amount": "token.amount",
        "timeout_height_revision_number": "timeout_height.revision_number",
        "timeout_height_revision_height": "timeout_height.revision_height",
        "timeout_timestamp": "timeout_timestamp", "memo": "memo",
    },
    addresses=(("sender", "sender"), ("receiver", "receiver")),
)

UPDATE_CLIENT = Handler(
    name="ibc_updateclient_msg", type_url="/ibc.core.client.v1.MsgUpdateClient", table="ibc_updateclient_msg",
    columns={"client_id": "client_id", "signer": "signer"},
    addresses=(("signer", "signer"),),
)

CREATE_CLIENT = Handler(
    name="ibc_createclient_msg", type_url="/ibc.core.client.v1.MsgCreateClient", table="ibc_createclient_msg",
    columns={
        "client_state_type": "client_state.@type", "client_chain_id": "client_state.chain_id",
        "trust_level_numerator": "client_state.trust_level.numerator",
        "trust_level_denominator": "client_state.trust_level.denominator",
        "latest_height_revision_number": "client_state.latest_height.revision_number",
        "latest_height_revision_height": "client_state.latest_height.revision_height",
        "frozen_height_revision_number": "client_state.frozen_height.revision_number",
        "frozen_height_revision_height": "client_state.frozen_height.revision_height",
        "signer": "signer",
    },
    addresses=(("signer", "signer"),),
)

CONNECTION_OPEN_TRY = Handler(
    name="ibc_openconnectiontry_msg", type_url="/ibc.core.connection.v1.MsgConnectionOpenTry",
    table="ibc_openconnectiontry_msg",
    columns={
        "client_id": "client_id", "previous_connection_id": "previous_connection_id",
        "counterparty_client_id": "counterparty.client_id",
        "counterparty_connection_id": "counterparty.connection_id",
        "counterparty_versions": "counterparty_versions", **PROOF_HEIGHT, "signer": "signer",
    },
    addresses=(("signer", "signer"),),
)

CONNECTION_OPEN_CONFIRM = Handler(
    name="ibc_openconnectionconfirm_msg", type_url="/ibc.core.connection.v1.MsgConnectionOpenConfirm",
    table="ibc_openconnectionconfirm_msg",
    columns={"connection_id": "connection_id", **PROOF_HEIGHT, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

_CHANNEL = {
    "channel_state": "channel.state", "channel_ordering": "channel.ordering",
    "counterparty_port_id": "channel.counterparty.port_id",
    "counterparty_channel_id": "channel.counterparty.channel_id",
    "connection_hops": "channel.connection_hops", "version": "channel.version",
}

CHANNEL_OPEN_INIT = Handler(
    name="ibc_core_channel_v1_msgchannelopeninit", type_url="/ibc.core.channel.v1.MsgChannelOpenInit",
    table="ibc_channelopeninit_msg",
    columns={"port_id": "port_id", **_CHANNEL, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

CHANNEL_OPEN_TRY = Handler(
    name="ibc_channelopentry_msg", type_url="/ibc.core.channel.v1.MsgChannelOpenTry", table="ibc_channelopentry_msg",
    columns={"port_id": "port_id", "previous_channel_id": "previous_channel_id", **_CHANNEL,
             "counterparty_version": "counterparty_version", **PROOF_HEIGHT, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

CHANNEL_OPEN_ACK = Handler(
    name="ibc_core_channel_v1_msgchannelopenack", type_url="/ibc.core.channel.v1.MsgChannelOpenAck",
    table="ibc_channelopenack_msg",
    columns={"port_id": "port_id", "channel_id": "channel_id",
             "counterparty_channel_id": "counterparty_channel_id",
             "counterparty_version": "counterparty_version", **PROOF_HEIGHT, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

CHANNEL_OPEN_CONFIRM = Handler(
    name="ibc_channelopenconfirm_msg", type_url="/ibc.core.channel.v1.MsgChannelOpenConfirm",
    table="ibc_channelopenconfirm_msg",
    columns={"port_id": "port_id", "channel_id": "channel_id", **PROOF_HEIGHT, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

RECV_PACKET = Handler(
    name="ibc_recvpacket_msg", type_url="/ibc.core.channel.v1.MsgRecvPacket", table="ibc_recvpacket_msg",
    columns={**PACKET, **PROOF_HEIGHT, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

ACKNOWLEDGEMENT = Handler(
    name="ibc_acknowledgement_msg", type_url="/ibc.core.channel.v1.MsgAcknowledgement",
    table="ibc_acknowledgement_msg",
    columns={**PACKET, "acknowledgement": "acknowledgement", **PROOF_HEIGHT, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

TIMEOUT = Handler(
    name="ibc_timeout_msg", type_url="/ibc.core.channel.v1.MsgTimeout", table="ibc_timeout_msg",
    columns={**PACKET, "next_sequence_recv": "next_sequence_recv", **PROOF_HEIGHT, "signer": "signer"},
    addresses=(("signer", "signer"),),
)

HANDLERS = [TRANSFER, UPDATE_CLIENT, CREATE_CLIENT, CONNECTION_OPEN_TRY, CONNECTION_OPEN_CONFIRM,
            CHANNEL_OPEN_INIT, CHANNEL_OPEN_TRY, CHANNEL_OPEN_ACK, CHANNEL_OPEN_CONFIRM,
            RECV_PACKET, ACKNOWLEDGEMENT, TIMEOUT]
