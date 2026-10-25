"""R16a and R24 from outside the project's stack: the external modes the tier-1 queue runs against a public testnet
endpoint (XC-110). Python ports of ts/src/head-unpaid.ts and ts/src/header.ts, graded the same way.

Both reuse the unpaid GET that P1-P7 already sent, so neither sends its own. Nothing is paid or signed, no facilitator
is called, and every request goes through the run's pacer (at least 5 s apart off loopback, and --max-requests).

  R16a  one unpaid HEAD. It passes when the HEAD is answered 402 with a PAYMENT-REQUIRED offer, like GET, or refused
        with 405 and no PAYMENT-RESPONSE. HEAD is not a GET, so off loopback it is sent only with the operator's
        permission (--operator-permission REF, the convention of the devnet runner); without it R16a is skipped.
  R24   one unpaid GET per malformed PAYMENT-SIGNATURE value (five values). Each must get 402 or 400 with a structured
        error, never a 5xx, a dropped connection or the content."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .pacing import RequestBudgetExceeded, is_loopback
from .types import CheckResult, Json

R16A = ("R16a an unpaid HEAD on a paid route never reaches the handler: 402 with PAYMENT-REQUIRED like GET, "
        "or refused with 405")
R24 = ("R24 a malformed, non-base64 or non-object payment header gets 402 or 400 with a structured error, "
       "never a 5xx or an unhandled exception")
MAX_BYTES = 1 << 16


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


# The same five values as ts/src/header.ts MALFORMED_HEADERS, in the same order.
MALFORMED_HEADERS: dict[str, str] = {
    "not_base64": "%%%not-base64%%%",
    "base64_not_json": _b64("this is not json"),
    "json_array": _b64("[1,2,3]"),
    "json_string": _b64('"payment"'),
    "json_number": _b64("42"),
}
# Requests each check sends on top of the shared unpaid GET.
REQUESTS: dict[str, int] = {"R16a": 1, "R24": len(MALFORMED_HEADERS)}

Opener = Callable[..., Any]


def head_needs_permission(url: str, permission: str | None) -> bool:
    """True when the HEAD may not be sent: the target is off loopback and no operator permission was given."""
    return not is_loopback(url) and not (permission or "").strip()


def _send(url: str, method: str, headers: dict[str, str], timeout: float, opener: Opener | None) -> Json:
    from .harness import user_agent
    req = urllib.request.Request(url, method=method, headers={"accept": "application/json",
                                                              "user-agent": user_agent(), **headers})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            status, hdrs, body = int(r.status), dict(r.headers.items()), (r.read(MAX_BYTES) if method != "HEAD" else b"")
    except urllib.error.HTTPError as e:
        status, hdrs = int(e.code), dict(e.headers.items()) if e.headers else {}
        body = e.read(MAX_BYTES) if method != "HEAD" else b""
    return {"status": status, "headers": {k.lower(): v for k, v in hdrs.items()}, "body": body}


def _offers(header: str | None) -> int:
    if not header:
        return 0
    from .harness import _decode_header
    try:
        pr = _decode_header(header.strip())
    except Exception:  # noqa: BLE001
        return 0
    acc = pr.get("accepts") if isinstance(pr, dict) else None
    return len(acc) if isinstance(acc, list) else 0


def _structured(status: int, header: str | None, body: bytes) -> bool:
    if header:
        from .harness import _decode_header
        try:
            if isinstance(_decode_header(header.strip()), dict):
                return True
        except Exception:  # noqa: BLE001
            pass
    if status in (400, 402):
        try:
            j = json.loads(body or b"null")
        except ValueError:
            return False
        return isinstance(j, dict) and "error" in j
    return False


def unpaid_head(url: str, get_status: int, *, timeout: float = 15, opener: Opener | None = None) -> CheckResult:
    """R16a on a route whose unpaid GET was answered get_status. The caller checks the operator's permission."""
    from .harness import result
    if get_status != 402:
        return result(R16A, False, {"get_status": get_status, "error": "the route did not answer an unpaid GET with 402"})
    try:
        h = _send(url, "HEAD", {}, timeout, opener)
    except RequestBudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        return result(R16A, False, {"get_status": get_status, "head_status": None,
                                    "error": f"no answer to the unpaid HEAD: {repr(e)[:160]}"})
    status, pr = h["status"], h["headers"].get("payment-required")
    offers = _offers(pr)
    payment_response = bool(h["headers"].get("payment-response"))
    refused = status == 405 and not payment_response
    ok = (status == 402 and offers > 0) or refused
    detail: dict[str, Any] = {"get_status": get_status, "head_status": status, "head_payment_required": bool(pr),
                              "head_offers": offers}
    if status == 405:
        detail.update({"allow": h["headers"].get("allow"), "head_payment_response": payment_response})
    if refused:
        detail["note"] = "HEAD is refused with 405 before any handler runs, so it is never served for free"
    elif 200 <= status < 300:
        detail["error"] = "an unpaid HEAD reached the protected handler"
    elif not ok:
        detail["error"] = "the unpaid HEAD was neither answered 402 with a PAYMENT-REQUIRED offer nor refused with 405"
    return result(R16A, ok, detail)


def malformed_header(url: str, get_status: int, *, timeout: float = 15, opener: Opener | None = None) -> CheckResult:
    """R24 on a route whose unpaid GET was answered get_status: one GET per malformed PAYMENT-SIGNATURE value."""
    from .harness import result
    if get_status != 402:
        return result(R24, False, {"status": get_status,
                                   "error": "the route did not answer an unpaid request with 402, so nothing was graded"})
    cases: list[dict[str, Any]] = []
    for name, value in MALFORMED_HEADERS.items():
        t0 = time.time()
        try:
            r = _send(url, "GET", {"PAYMENT-SIGNATURE": value}, timeout, opener)
        except RequestBudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            cases.append({"header": name, "status": 0, "structured_error": False, "pass": False,
                          "error": f"no answer: {repr(e)[:160]}"})
            continue
        st = r["status"]
        structured = _structured(st, r["headers"].get("payment-required"), r["body"])
        ok = st in (400, 402) and structured
        case: dict[str, Any] = {"header": name, "status": st, "structured_error": structured, "pass": ok,
                                "ms": int((time.time() - t0) * 1000)}
        if not ok:
            case["body"] = r["body"][:200].decode("utf-8", "replace")
        cases.append(case)
    failed = [c for c in cases if not c["pass"]]
    worst = next((c for c in failed if c["status"] >= 500), None) or next(
        (c for c in failed if c["status"] == 0), None) or (failed[0] if failed else None)
    detail: dict[str, Any] = {"cases": cases, "facilitator_calls": None}
    if worst:
        detail["error"] = (f"a malformed header ({worst['header']}) got {worst['status']}" if worst["status"] >= 500
                           else f"a malformed header ({worst['header']}) got no answer: the connection was dropped"
                           if worst["status"] == 0 else
                           f"a malformed header ({worst['header']}) got {worst['status']} without a structured error")
    return result(R24, not failed, detail)
