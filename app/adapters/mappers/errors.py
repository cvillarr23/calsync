class FieldFailure(ValueError):
    """One field of one item couldn't be read; the item is dropped and the run goes on."""

    def __init__(self, field: str, msg: str) -> None:
        super().__init__(f"{field}: {msg}")
        self.field = field
        self.msg = msg
