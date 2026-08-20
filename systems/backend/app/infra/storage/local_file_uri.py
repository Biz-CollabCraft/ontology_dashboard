"""Pure local/file URI resolution for filesystem-backed Infra adapters."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse


def local_file_uri_path(uri: str) -> Path:
    """Resolve a local path or ``file://`` URI without touching the filesystem."""

    parsed = urlparse(uri)
    if parsed.scheme in {"", "file"}:
        value = unquote(parsed.path) if parsed.scheme == "file" else uri
        return Path(value)
    raise ValueError("local filesystem access only supports paths and file:// URIs")


__all__ = ["local_file_uri_path"]
