"""公共小工具。"""

from __future__ import annotations

import uuid

from .errors import DomainError


def new_id() -> str:
    return uuid.uuid4().hex


def require_basis(basis: str) -> str:
    """换人、续证、申诉、豁免与复核等决定都必须附带依据。"""
    if not basis or not basis.strip():
        raise DomainError("决定必须附带依据")
    return basis
