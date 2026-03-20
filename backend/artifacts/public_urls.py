"""Helpers for stable public artifact URLs."""

from __future__ import annotations

import os

DEFAULT_BIOAPEX_PUBLIC_BASE_URL = "http://localhost:8002"


def bioapex_public_base_url() -> str:
    return os.getenv("BIOAPEX_PUBLIC_BASE_URL", DEFAULT_BIOAPEX_PUBLIC_BASE_URL).rstrip("/")


def public_raw_file_url(relative_path: str) -> str:
    return f"{bioapex_public_base_url()}/api/files/raw?path={relative_path.strip()}"
