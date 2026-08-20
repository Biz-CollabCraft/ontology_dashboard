"""Pure local/file URI resolution for filesystem-backed Infra adapters."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse


def local_file_uri_path(uri: str) -> Path:
    """Resolve a local path or ``file://`` URI without touching the filesystem."""

    if len(uri) >= 3 and uri[0].isalpha() and uri[1] == ":" and uri[2] in {"/", "\\"}:
        return Path(uri)
    parsed = urlparse(uri)
    if parsed.scheme in {"", "file"}:
        value = unquote(parsed.path) if parsed.scheme == "file" else uri
        if parsed.scheme == "file" and len(value) >= 3 and value[0] == "/" and value[1].isalpha() and value[2] == ":":
            value = value[1:]
        return Path(value)
    raise ValueError("local filesystem access only supports paths and file:// URIs")


__all__ = ["local_file_uri_path"]
