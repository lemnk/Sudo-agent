from __future__ import annotations

from decimal import Decimal
from typing import Any, TypeAlias

JSONPrimitive: TypeAlias = str | int | bool | None | Decimal
JSONNumber: TypeAlias = str | int | Decimal
JSONValue: TypeAlias = (
    JSONPrimitive | JSONNumber | dict[str, "JSONValue"] | list["JSONValue"]
)

SigningKey: TypeAlias = Any  # one-line justification: optional dependency at runtime
VerifyKey: TypeAlias = Any  # one-line justification: optional dependency at runtime
