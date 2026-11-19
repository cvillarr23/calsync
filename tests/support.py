"""Fakes and sample data shared by tests in several packages."""

PYTHON_DEF = {
    "id": "sneaky",
    "version": 1,
    "name": "Sneaky",
    "kind": "python",
    "entrypoint": "os:system",
}


class FakeRunner:
    def __init__(self, events=None, error=None):
        self.events = list(events or [])
        self.error = error
        self.calls = []

    async def __call__(self, definition, params, window_start, window_end):
        self.calls.append((definition.id, dict(params), window_start, window_end))
        if self.error:
            raise self.error
        return list(self.events)


class RecordingTarget:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def apply(self, db, source, matched, now):
        self.calls.append([event.uid for event in matched])
        if self.error:
            raise self.error
