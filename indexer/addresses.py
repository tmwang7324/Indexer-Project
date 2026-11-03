"""Address classification, for any bech32 prefix (terra, migaloo, osmo, ...)."""
import logging

log = logging.getLogger(__name__)

USER_DATA_LENGTH = 38   # 20-byte account address, bech32 data part without separator


def classify_address(address: str) -> str:
    """'blank', 'validator', 'user', 'contract' or 'Unknown'.

    The bech32 separator is the LAST '1': the prefix may contain a '1' itself, the data part never does.
    Validator is checked before the length rules, because a valoper address is as long as a user address.
    """
    if address == "":
        return "blank"
    if "valoper" in address:
        return "validator"
    length_after_separator = len(address) - address.rfind("1") - 1
    if length_after_separator == USER_DATA_LENGTH:
        return "user"
    if length_after_separator > USER_DATA_LENGTH:
        return "contract"
    log.warning("could not classify address %r", address)
    return "Unknown"
