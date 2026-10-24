class InterpretationError(Exception):
    """A surface-agnostic lifecycle failure (bad request, conflict,
    not-found, auth), carrying an HTTP-shaped status for the surface's
    own view layer to translate directly."""

    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)
