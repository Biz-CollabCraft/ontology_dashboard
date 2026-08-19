"""Project domain exceptions."""

from __future__ import annotations


class ProjectError(RuntimeError):
    """Project use-case failure translated to HTTP at the composition boundary."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ProjectContextError(ValueError):
    """Raised when a workspace cannot be resolved to a valid Project context."""


__all__ = ["ProjectContextError", "ProjectError"]
