from __future__ import annotations


class ReportConflictError(RuntimeError):
    pass


class ReportNotFoundError(KeyError):
    pass


__all__ = ["ReportConflictError", "ReportNotFoundError"]
