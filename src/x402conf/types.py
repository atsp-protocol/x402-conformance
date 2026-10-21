"""Typed shapes used by the harness."""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict

Json = dict[str, Any]
Severity = Literal["error", "warning", "info"]


# "pass" is a Python keyword, so the functional TypedDict form is used.
CheckResult = TypedDict("CheckResult", {"check": str, "pass": bool, "severity": Severity, "detail": Any})


class Facilitator(Protocol):
    """The two state-related facilitator calls (x402 V2 sections 7.1 and 7.2), as a facilitator double or adapter."""

    def verify(self, payload: Any, requirements: Json) -> Any: ...

    def settle(self, payload: Any, requirements: Json) -> Any: ...
