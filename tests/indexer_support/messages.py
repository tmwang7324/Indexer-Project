"""One sample message per handled type: 4 from the Migaloo fixtures, the rest hand-written (D24)."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "tests" / "indexer" / "data"

DECODED = json.loads((REPO / "tests" / "fixtures" / "decoded" / "7027410.json").read_text())
_MIGALOO = {m["@type"]: m for tx in DECODED for m in tx["tx"]["body"]["messages"]}
FROM_MIGALOO = ("/cosmos.authz.v1beta1.MsgExec", "/ibc.core.client.v1.MsgUpdateClient",
                "/ibc.core.channel.v1.MsgAcknowledgement", "/cosmos.gov.v1.MsgVote")

MESSAGES = {
    **json.loads((DATA / "handler_messages.json").read_text()),
    **{t: _MIGALOO[t] for t in FROM_MIGALOO},
}
