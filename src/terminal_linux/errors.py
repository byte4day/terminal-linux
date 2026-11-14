from __future__ import annotations


class SessionError(RuntimeError):
    """A failure the CLI and MCP server report as JSON instead of a traceback.

    ``code`` is a short machine-readable reason (``not_running``, ``bad_args``,
    ``out_of_bounds``, ``not_found``, ``timeout``, ``session_error``).
    """

    def __init__(self, message: str, *, code: str = "session_error") -> None:
        super().__init__(message)
        self.code = code
