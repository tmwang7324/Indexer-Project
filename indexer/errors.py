class BadDataError(Exception):
    """The source data is malformed or inconsistent (D21): retrying will not help."""


class TransientError(Exception):
    """A fetch or database problem that may go away: timeouts, 429/5xx, no endpoint available (D21)."""


class CountMismatchError(BadDataError):
    """What the writer stored disagrees with what the source said (D14). The block is rolled back."""

    def __init__(self, chain_id: str, height: int, mismatches: list):
        self.mismatches = mismatches
        super().__init__(f"block {chain_id}/{height}: " + "; ".join(str(m) for m in mismatches))


class OutageError(Exception):
    """Too many blocks in a row were given up on after transient errors: the node or the database is down,
    and recording every remaining height as failed would only fill failed_blocks. The run stops."""
