"""typed copies of messages: 35 tables, plus 2 side tables

Revision ID: 0002
Revises: 0001

Every typed table is keyed by messages.message_id (D2). Address values are kept as text in the
typed row; the links to the shared address table come with the addresses migration. Large blobs
(IBC proofs, client headers, wasm byte code) stay only in messages.raw.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_KEY = "message_id BIGINT PRIMARY KEY REFERENCES indexer.messages (message_id) ON DELETE CASCADE"
_PROOF_HEIGHT = """proof_height_revision_number NUMERIC, proof_height_revision_height NUMERIC"""
_PACKET = """sequence NUMERIC, source_port TEXT, source_channel TEXT, destination_port TEXT,
        destination_channel TEXT, data TEXT,
        timeout_height_revision_number NUMERIC, timeout_height_revision_height NUMERIC,
        timeout_timestamp NUMERIC"""

# (table, column definitions)
TABLES = [
    # bank
    ("cosmos_send_msg", "from_address TEXT, to_address TEXT, denom TEXT, amount NUMERIC, coins JSONB"),
    ("cosmos_multisend_msg", "input_count INTEGER, output_count INTEGER, inputs JSONB"),
    # authz
    ("cosmos_exec_msg", "grantee TEXT, msg_count INTEGER"),
    ("cosmos_grant_msg", """granter TEXT, grantee TEXT, authorization_type TEXT, expiration TIMESTAMPTZ,
        authorization_kind TEXT, msg TEXT, max_tokens JSONB"""),
    ("cosmos_revoke_msg", "granter TEXT, grantee TEXT, msg_type_url TEXT"),
    # staking, distribution, slashing
    ("cosmos_delegate_msg", "delegator_address TEXT, validator_address TEXT, denom TEXT, amount NUMERIC"),
    ("cosmos_undelegate_msg", "delegator_address TEXT, validator_address TEXT, denom TEXT, amount NUMERIC"),
    ("cosmos_beginredelegate_msg", """delegator_address TEXT, validator_src_address TEXT,
        validator_dst_address TEXT, denom TEXT, amount NUMERIC"""),
    ("cosmos_editvalidator_msg", """validator_address TEXT, moniker TEXT, identity TEXT, website TEXT,
        security_contact TEXT, details TEXT, commission_rate TEXT, min_self_delegation TEXT"""),
    ("cosmos_withdrawdelegatorreward_msg", "delegator_address TEXT, validator_address TEXT"),
    ("cosmos_withdrawvalidatorcommission_msg", "validator_address TEXT"),
    ("cosmos_unjail_msg", "validator_addr TEXT"),
    # gov
    ("cosmos_vote_msg", "proposal_id BIGINT, voter TEXT, option TEXT, metadata TEXT"),
    ("cosmos_vote_beta1_msg", "proposal_id BIGINT, voter TEXT, option TEXT"),
    # alliance
    ("alliance_delegate_msg", "delegator_address TEXT, validator_address TEXT, denom TEXT, amount NUMERIC"),
    ("alliance_undelegate_msg", "delegator_address TEXT, validator_address TEXT, denom TEXT, amount NUMERIC"),
    ("alliance_redelegate_msg", """delegator_address TEXT, validator_src_address TEXT,
        validator_dst_address TEXT, denom TEXT, amount NUMERIC"""),
    ("alliance_claimdelegationrewards_msg", "delegator_address TEXT, validator_address TEXT, denom TEXT"),
    # cosmwasm
    ("cosmwasm_executecontract_msg", "sender TEXT, contract TEXT, action TEXT, funds JSONB"),
    ("cosmwasm_instantiatecontract_msg", "sender TEXT, admin TEXT, code_id NUMERIC, label TEXT, funds JSONB"),
    ("cosmwasm_instantiatecontract2_msg", """sender TEXT, admin TEXT, code_id NUMERIC, label TEXT, funds JSONB,
        salt TEXT, fix_msg BOOLEAN"""),
    ("cosmwasm_storecode_msg", "sender TEXT, wasm_byte_code_size INTEGER, instantiate_permission JSONB"),
    ("cosmwasm_migratecontract_msg", "sender TEXT, contract TEXT, code_id NUMERIC, action TEXT"),
    # ibc
    ("ibc_transfer_msg", """sender TEXT, receiver TEXT, source_port TEXT, source_channel TEXT,
        token_denom TEXT, token_amount NUMERIC, timeout_height_revision_number NUMERIC,
        timeout_height_revision_height NUMERIC, timeout_timestamp NUMERIC, memo TEXT"""),
    ("ibc_updateclient_msg", "client_id TEXT, signer TEXT"),
    ("ibc_createclient_msg", """client_state_type TEXT, client_chain_id TEXT,
        trust_level_numerator NUMERIC, trust_level_denominator NUMERIC,
        latest_height_revision_number NUMERIC, latest_height_revision_height NUMERIC,
        frozen_height_revision_number NUMERIC, frozen_height_revision_height NUMERIC, signer TEXT"""),
    ("ibc_openconnectiontry_msg", f"""client_id TEXT, previous_connection_id TEXT, counterparty_client_id TEXT,
        counterparty_connection_id TEXT, counterparty_versions JSONB, {_PROOF_HEIGHT}, signer TEXT"""),
    ("ibc_openconnectionconfirm_msg", f"connection_id TEXT, {_PROOF_HEIGHT}, signer TEXT"),
    ("ibc_channelopeninit_msg", """port_id TEXT, channel_state TEXT, channel_ordering TEXT,
        counterparty_port_id TEXT, counterparty_channel_id TEXT, connection_hops JSONB, version TEXT, signer TEXT"""),
    ("ibc_channelopentry_msg", f"""port_id TEXT, previous_channel_id TEXT, channel_state TEXT, channel_ordering TEXT,
        counterparty_port_id TEXT, counterparty_channel_id TEXT, connection_hops JSONB, version TEXT,
        counterparty_version TEXT, {_PROOF_HEIGHT}, signer TEXT"""),
    ("ibc_channelopenack_msg", f"""port_id TEXT, channel_id TEXT, counterparty_channel_id TEXT,
        counterparty_version TEXT, {_PROOF_HEIGHT}, signer TEXT"""),
    ("ibc_channelopenconfirm_msg", f"port_id TEXT, channel_id TEXT, {_PROOF_HEIGHT}, signer TEXT"),
    ("ibc_recvpacket_msg", f"{_PACKET}, {_PROOF_HEIGHT}, signer TEXT"),
    ("ibc_acknowledgement_msg", f"{_PACKET}, acknowledgement TEXT, {_PROOF_HEIGHT}, signer TEXT"),
    ("ibc_timeout_msg", f"{_PACKET}, next_sequence_recv NUMERIC, {_PROOF_HEIGHT}, signer TEXT"),
]

# Side tables: several rows per message.
SIDE_TABLES = [
    ("cosmos_multisend_outputs", """output_index INTEGER NOT NULL, address TEXT, denom TEXT, amount NUMERIC,
        coins JSONB, PRIMARY KEY (message_id, output_index)"""),
    ("cosmos_grant_allowlist", "position INTEGER NOT NULL, address TEXT, PRIMARY KEY (message_id, position)"),
]


def upgrade() -> None:
    for table, columns in TABLES:
        op.execute(f"CREATE TABLE indexer.{table} ({_KEY}, {columns})")
    for table, columns in SIDE_TABLES:
        op.execute(f"CREATE TABLE indexer.{table} (message_id BIGINT NOT NULL "
                   f"REFERENCES indexer.messages (message_id) ON DELETE CASCADE, {columns})")


def downgrade() -> None:
    for table, _ in SIDE_TABLES + TABLES[::-1]:
        op.execute(f"DROP TABLE indexer.{table}")
