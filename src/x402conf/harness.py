"""The checks.

Live checks (S1-S4) read a facilitator's public GET /supported and nothing else: no signing, no payment, no POST.
Offline checks (F1-F9) drive a facilitator implementation in-process through /verify and /settle semantics and test
the safety properties a resource server depends on. F7 and F8 advance the double's simulated chain between retries of
the same /settle body; F9 puts a broken transport (a 503, a non-JSON page, a truncated body) between the resource
server and the facilitator. On devnet they run only against a facilitator its operator
points the suite at."""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from . import spec as S
from .mock import Chain, Vectors
from .types import CheckResult, Facilitator, Json, Severity

MAX_BYTES = 1 << 20
UA = "x402-conformance/1.2.1 (+https://github.com/atsp-protocol/x402-conformance)"
Opener = Callable[..., Any]


def result(check: str, ok: bool, detail: Any, severity: Severity = "error") -> CheckResult:
    return {"check": check, "pass": bool(ok), "severity": severity, "detail": detail}


# ---------------- live, GET only ----------------
def fetch_supported(base: str, timeout: float = 10, opener: Opener | None = None) -> Json:
    url = base.rstrip("/") + "/supported"
    req = urllib.request.Request(url, method="GET", headers={"accept": "application/json", "user-agent": UA})
    t0 = time.time()
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
        body: bytes = r.read(MAX_BYTES + 1)
        status = int(r.status)
    if len(body) > MAX_BYTES:
        raise ValueError("response larger than 1 MiB")
    return {"url": url, "status": status, "ms": int((time.time() - t0) * 1000), "raw": body, "json": json.loads(body)}


def check_supported(doc: Json) -> list[CheckResult]:
    out: list[CheckResult] = []
    kinds, ext, signers = doc.get("kinds"), doc.get("extensions"), doc.get("signers")
    shape = isinstance(kinds, list) and isinstance(ext, list) and isinstance(signers, dict)
    out.append(result("S1 SupportedResponse shape: kinds[], extensions[], signers{} (V2 7.3.1)", shape,
                      {"kinds": type(kinds).__name__, "extensions": type(ext).__name__, "signers": type(signers).__name__}))
    klist: list[Json] = [k for k in kinds if isinstance(k, dict)] if isinstance(kinds, list) else []
    v2 = [k for k in klist if k.get("x402Version") == S.X402_VERSION]
    v1 = [k for k in klist if k.get("x402Version") == 1]
    bad_net = [k.get("network") for k in v2 if not S.CAIP2.match(str(k.get("network", "")))]
    out.append(result("S2 every V2 kind names its network in CAIP-2 (V2 11.1)", not bad_net,
                      {"v2_kinds": len(v2), "v1_kinds": len(v1), "non_caip2": bad_net[:10]}))
    sol = [k for k in v2 if str(k.get("network", "")).startswith("solana:")]
    v1names = [k.get("network") for k in v2 if k.get("network") in S.SOLANA_V1_NAMES]
    unknown = [k.get("network") for k in sol if k.get("network") not in (S.SOLANA_MAINNET, S.SOLANA_DEVNET)]
    out.append(result("S3 Solana V2 kinds use the published CAIP-2 IDs, not V1 names", not v1names and not unknown,
                      {"solana_v2_kinds": [[k.get("scheme"), k.get("network")] for k in sol],
                       "v1_names_in_v2": v1names, "unrecognised_solana_ids": unknown}))
    def signers_for(network: str) -> list[Any]:
        """Signers whose CAIP-2 pattern (V2 7.3.1) matches network: the exact ID or a namespace wildcard such as solana:*."""
        found: list[Any] = []
        for pat, addrs in (signers.items() if isinstance(signers, dict) else []):
            hit = pat == network or (pat.endswith(":*") and network.startswith(pat[:-1]))
            if hit and isinstance(addrs, list):
                found += addrs
        return found
    exact = [k for k in sol if k.get("scheme") == "exact"]
    probs: list[Json] = []
    for k in exact:
        fp = (k.get("extra") or {}).get("feePayer")
        if not S.is_solana_pubkey(fp):
            probs.append({"network": k.get("network"), "problem": "extra.feePayer missing or not a 32-byte base58 key"})
        elif fp not in signers_for(str(k.get("network", ""))):
            probs.append({"network": k.get("network"), "feePayer": fp,
                          "problem": "feePayer not listed under any signers pattern matching the network"})
    out.append(result("S4 Solana exact kinds advertise a valid extra.feePayer that is a listed signer (SVM exact)",
                      not probs, {"solana_exact_kinds": len(exact), "problems": probs},
                      severity="error" if exact else "info"))
    return out


def run_live(base: str, *, timeout: float = 10, opener: Opener | None = None) -> Json:
    try:
        r = fetch_supported(base, timeout=timeout, opener=opener)
    except Exception as e:  # noqa: BLE001  a network or JSON failure is itself a result
        return {"target": base, "mode": "live-GET-only", "error": repr(e)[:200], "checks": []}
    ok_body = r["status"] == 200 and isinstance(r["json"], dict)
    return {"target": base, "mode": "live-GET-only", "http": r["status"], "ms": r["ms"],
            "checks": check_supported(r["json"]) if ok_body else [],
            "kinds_total": len(r["json"].get("kinds") or []) if ok_body else None, "raw": r["raw"]}


# ---------------- offline safety checks ----------------
def _success(resp: Any) -> bool:
    return isinstance(resp, dict) and resp.get("success") is True


def _reason(resp: Any) -> Any:
    return resp.get("errorReason") if isinstance(resp, dict) else None


def _tx(resp: Any) -> Any:
    return resp.get("transaction") if isinstance(resp, dict) else None


def _chain(fac: Facilitator) -> Chain | None:
    ch = getattr(fac, "chain", None)
    return ch if isinstance(ch, Chain) else None


def check_safety(fac: Facilitator, mk: Vectors,
                 guard: Callable[[Facilitator], ResourceServerGuard] | None = None) -> list[CheckResult]:
    make_guard = guard or ResourceServerGuard
    out: list[CheckResult] = []
    req, good = mk("req"), mk("good")
    try:
        v: Any = fac.verify(mk("malformed"), req)
        ok = isinstance(v, dict) and v.get("isValid") is False
    except Exception:  # noqa: BLE001  raising is closed, not open
        ok, v = True, "raised"
    out.append(result("F1 malformed payload: /verify returns isValid=false (fails closed)", ok, {"got": v}))
    v = fac.verify(mk("dust"), req)
    out.append(result("F2 amount below PaymentRequirements.amount is rejected (SVM exact 1.1)",
                      isinstance(v, dict) and v.get("isValid") is False, {"got": v}))
    a, b = fac.settle(good, req), fac.settle(good, req)
    out.append(result("F3 the same payload settled twice succeeds at most once (duplicate_settlement)",
                      _success(a) + _success(b) <= 1, {"first": a, "second": b}))
    c = fac.settle(mk("same_memo_new_tx"), req)
    out.append(result("F4 replay of a used memo/nonce in a new transaction is rejected", not _success(c), {"got": c}))
    d = fac.settle(mk("unfinalized"), req)
    pend_ok = not _success(d) and (not isinstance(d, dict) or d.get("errorReason") != S.SETTLEMENT_PENDING
                                   or bool(d.get("transaction")))
    out.append(result("F5 unconfirmed settlement is not success; settlement_pending carries a transaction (V2 9)",
                      pend_ok, {"got": d}))
    rs = make_guard(fac)
    e = rs.settle_and_credit(mk("fresh"), req, simulate="timeout")
    f = rs.settle_and_credit(mk("fresh2"), req, simulate="garbage")
    out.append(result("F6 facilitator timeout or malformed response: resource server does not credit (fail closed)",
                      e is False and f is False, {"timeout_credit": e, "garbage_credit": f}))
    out.append(_f7(fac, mk, req))
    out.append(_f8(fac, mk, req))
    out.append(_f9(fac, mk, req, make_guard))
    return out


F7 = "F7 a pending settlement retried with the same body reaches its final result, credited exactly once (V2 9)"
F8 = "F8 a failure confirmed on chain after settlement_pending is terminal, never stuck pending (V2 9)"
F9 = "F9 a 503, non-JSON or truncated /settle answer is never credited, and a retry then credits exactly once"


def _f7(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult:
    ch, p = _chain(fac), mk("pending_ok")
    if ch is None:
        return result(F7, False, {"error": "facilitator double exposes no simulated chain to advance"})
    rs = ResourceServerGuard(fac)
    first = fac.settle(p, req)
    if _reason(first) != S.SETTLEMENT_PENDING:
        # Nothing pending to retry. F5 judges a facilitator that never says settlement_pending.
        return result(F7, True, {"first": first, "note": "first answer was not settlement_pending; see F5"})
    credit_while_pending = rs.settle_and_credit(p, req)
    ch.set(p["tx"], Chain.CONFIRMED)
    retry = fac.settle(p, req)
    credits = [credit_while_pending]
    credits.append(rs.credit(retry))
    credits += [rs.settle_and_credit(p, req) for _ in range(2)]
    ok = (_success(retry) and _tx(retry) == _tx(first) == p["tx"] and not credit_while_pending
          and sum(credits) == 1)
    return result(F7, ok, {"first": first, "retry_after_confirm": retry, "credits": credits})


def _f8(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult:
    ch, p = _chain(fac), mk("pending_fail")
    if ch is None:
        return result(F8, False, {"error": "facilitator double exposes no simulated chain to advance"})
    rs = ResourceServerGuard(fac)
    first = fac.settle(p, req)
    if _reason(first) != S.SETTLEMENT_PENDING:
        return result(F8, True, {"first": first, "note": "first answer was not settlement_pending; see F5"})
    ch.set(p["tx"], Chain.FAILED)
    retries = [fac.settle(p, req) for _ in range(3)]
    credits = [rs.credit(r) for r in retries]
    ok = all(isinstance(r, dict) and r.get("success") is False and _reason(r) not in (None, S.SETTLEMENT_PENDING)
             for r in retries) and not any(credits)
    return result(F8, ok, {"first": first, "retries_after_chain_failure": retries, "credits": credits})


def _f9(fac: Facilitator, mk: Vectors, req: Json, make_guard: Callable[[Facilitator], ResourceServerGuard]) -> CheckResult:
    ch, p = _chain(fac), mk("transport_retry")
    if ch is None:
        return result(F9, False, {"error": "facilitator double exposes no simulated chain to advance"})
    rs = make_guard(fac)
    broken = {m: rs.settle_and_credit(p, req, simulate=m) for m in ("http503", "non_json", "truncated")}
    ch.set(p["tx"], Chain.CONFIRMED)
    retries = [rs.settle_and_credit(p, req) for _ in range(2)]
    ok = not any(broken.values()) and retries == [True, False]
    return result(F9, ok, {"broken_transport_credit": broken, "retries_after": retries})


class ResourceServerGuard:
    """The credit rule the suite checks and lean/X402Conformance/Settlement.lean models: credit exactly once, only on
    an HTTP 200 whose body parses as JSON with success=true and a transaction, keyed by the transaction; never on an
    exception, timeout, non-200 status, non-JSON or truncated body. A payment whose answer was lost stays retryable.

    simulate puts a broken transport between the guard and the facilitator: "timeout" and "garbage" (an HTML 502) and
    "http503" and "non_json" never reach the facilitator; "truncated" reaches it and cuts its answer in half."""

    def __init__(self, fac: Facilitator) -> None:
        self.fac = fac
        self.credited: set[str] = set()

    def _exchange(self, payload: Any, req: Json, simulate: str | None) -> tuple[int, bytes]:
        if simulate == "timeout":
            raise TimeoutError("facilitator did not answer")
        if simulate == "garbage":
            return 502, b"<html>502</html>"
        if simulate == "non_json":
            return 200, b"<html><body>Service temporarily unavailable</body></html>"
        if simulate == "http503":
            # A proxy answering 503 while replaying a cached body that still reads as success.
            tx = payload.get("tx") if isinstance(payload, dict) else ""
            return 503, json.dumps({"success": True, "transaction": tx, "network": req.get("network")}).encode()
        body = json.dumps(self.fac.settle(payload, req)).encode()
        return 200, (body[: len(body) // 2] if simulate == "truncated" else body)

    def _accept_status(self, status: int) -> bool:
        return status == 200

    def _transport_error(self, payload: Any) -> None:
        """Hook for the faulty guards. The reference keeps the payment retryable."""

    def _abandoned(self, payload: Any) -> bool:
        return False

    def credit(self, resp: Any) -> bool:
        if not (isinstance(resp, dict) and resp.get("success") is True and isinstance(resp.get("transaction"), str)
                and resp["transaction"]):
            return False
        if resp["transaction"] in self.credited:
            return False
        self.credited.add(resp["transaction"])
        return True

    def settle_and_credit(self, payload: Any, req: Json, simulate: str | None = None) -> bool:
        if self._abandoned(payload):
            return False
        try:
            status, body = self._exchange(payload, req, simulate)
            if not self._accept_status(status):
                raise ValueError(f"HTTP {status}")
            resp: Any = json.loads(body)
        except Exception:  # noqa: BLE001
            self._transport_error(payload)
            return False
        return self.credit(resp)


class FaultyGuard(ResourceServerGuard):
    """Resource-server faults for F9. trust_any_status credits whatever a non-200 body says; give_up_after_error
    treats a lost answer as a failed payment and never retries it."""

    def __init__(self, fac: Facilitator, *, trust_any_status: bool = False, give_up_after_error: bool = False) -> None:
        super().__init__(fac)
        self.trust_any_status, self.give_up_after_error = trust_any_status, give_up_after_error
        self.given_up: set[str] = set()

    def _accept_status(self, status: int) -> bool:
        return self.trust_any_status or super()._accept_status(status)

    def _transport_error(self, payload: Any) -> None:
        if self.give_up_after_error and isinstance(payload, dict):
            self.given_up.add(str(payload.get("tx")))

    def _abandoned(self, payload: Any) -> bool:
        return isinstance(payload, dict) and str(payload.get("tx")) in self.given_up


GUARD_FAULTS: dict[str, Callable[[Facilitator], ResourceServerGuard]] = {
    "guard_trust_any_status": lambda f: FaultyGuard(f, trust_any_status=True),
    "guard_give_up_after_error": lambda f: FaultyGuard(f, give_up_after_error=True),
}
