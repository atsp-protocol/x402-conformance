"""The checks.

Live checks (S0-S4) read a facilitator's public GET /supported and nothing else: no signing, no payment, no POST.
Offline checks (F1-F14) drive a facilitator implementation in-process through /verify and /settle semantics and test
the safety properties a resource server depends on. F7 and F8 advance the double's simulated chain between retries of
the same /settle body; F9 puts a broken transport (a 503, a non-JSON page, a truncated body) between the resource
server and the facilitator. On devnet they run only against a facilitator its operator
points the suite at."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from . import __version__
from . import spec as S
from .mock import Chain, Vectors
from .types import CheckResult, Facilitator, Json, Severity

MAX_BYTES = 1 << 20
UA = f"x402-conformance/{__version__} (+https://github.com/atsp-protocol/x402-conformance)"
# Which entry point is running (the CLI, the Action, pytest, Docker ...). It goes into the User-Agent and the report and
# nowhere else: no machine or user id, no telemetry. Unknown values fall back to "cli-py".
VIA_ENV = "X402CONF_VIA"
VIAS = ("cli-ts", "cli-py", "action", "testing", "vitest", "jest", "node-test", "mcp", "ai-sdk", "langchain", "pytest",
        "docker", "gitlab", "library")


def via(env: Mapping[str, str] | None = None) -> str:
    v = (os.environ if env is None else env).get(VIA_ENV, "")
    return v if v in VIAS else "cli-py"


def user_agent(env: Mapping[str, str] | None = None) -> str:
    return f"x402-conformance/{__version__} (+https://github.com/atsp-protocol/x402-conformance; via={via(env)})"
Opener = Callable[..., Any]
# Optional facilitator credentials, from the environment only. The value is sent as the Authorization header to targets
# whose host is exactly AUTH_HOST_ENV, never to any other host, and is never written to output, evidence or errors.
AUTH_ENV = "X402C_FACILITATOR_AUTHORIZATION"
AUTH_HOST_ENV = "X402C_FACILITATOR_AUTH_HOST"


class UsageError(ValueError):
    """A configuration error the CLI reports with exit code 2."""


def result(check: str, ok: bool, detail: Any, severity: Severity = "error") -> CheckResult:
    """One check outcome. Evidence v2 labels it with the check's profile (normative, security-profile or resilience)
    and its spec basis from spec.CATALOG, so a reader can tell a spec violation from a hardening finding."""
    entry = S.CATALOG.get(check.split()[0], {})
    return {"check": check, "pass": bool(ok), "severity": severity, "detail": detail,
            "profile": str(entry.get("profile", "normative")), "basis": str(entry.get("basis", ""))}


# ---------------- live, GET only ----------------
def auth_header(url: str, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The Authorization header for url, or nothing. Raises UsageError when a credential is set without a host to scope
    it to, so a key meant for one facilitator is never sent to the others."""
    e = os.environ if env is None else env
    value, host = e.get(AUTH_ENV, ""), e.get(AUTH_HOST_ENV, "").strip().lower()
    if not value:
        return {}
    if not host:
        raise UsageError(f"{AUTH_ENV} is set but {AUTH_HOST_ENV} is not; set it to the one facilitator host the "
                         "credential belongs to")
    return {"authorization": value} if (urllib.parse.urlsplit(url).hostname or "").lower() == host else {}


def _redact(text: str, env: Mapping[str, str] | None = None) -> str:
    v = (os.environ if env is None else env).get(AUTH_ENV, "")
    return text.replace(v, "[redacted]") if len(v) >= 4 else text


def fetch_supported(base: str, timeout: float = 10, opener: Opener | None = None,
                    env: Mapping[str, str] | None = None) -> Json:
    url = base.rstrip("/") + "/supported"
    headers = {"accept": "application/json", "user-agent": user_agent(env), **auth_header(url, env)}
    req = urllib.request.Request(url, method="GET", headers=headers)
    t0 = time.time()
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
        body: bytes = r.read(MAX_BYTES + 1)
        status = int(r.status)
    if len(body) > MAX_BYTES:
        raise ValueError("response larger than 1 MiB")
    return {"url": url, "status": status, "ms": int((time.time() - t0) * 1000), "raw": body, "json": json.loads(body)}


S0 = "S0 GET /supported answers HTTP 200 with a JSON object"
S1 = "S1 SupportedResponse shape: kinds[], extensions[], signers{} (V2 7.3.1; V1 7.3: kinds[])"
S4 = "S4 Solana exact kinds advertise a valid extra.feePayer, listed as a signer (SVM exact; V2 7.3.1)"


def check_supported(doc: Json) -> list[CheckResult]:
    out: list[CheckResult] = []
    kinds, ext, signers = doc.get("kinds"), doc.get("extensions"), doc.get("signers")
    klist: list[Json] = [k for k in kinds if isinstance(k, dict)] if isinstance(kinds, list) else []
    v2 = [k for k in klist if k.get("x402Version") == S.X402_VERSION]
    v1 = [k for k in klist if k.get("x402Version") == 1]
    # V1 (7.3) defines /supported as kinds[] only; extensions and signers arrived with V2 (7.3.1). A facilitator that
    # advertises only V1 kinds is graded as V1. One V2 kind makes the whole response a V2 response.
    v1_only = isinstance(kinds, list) and bool(klist) and not v2 and len(v1) == len(klist)
    if v1_only:
        shape = all(isinstance(k.get("scheme"), str) and isinstance(k.get("network"), str) for k in klist)
        graded = "v1"
    else:
        shape = isinstance(kinds, list) and isinstance(ext, list) and isinstance(signers, dict)
        graded = "v2"
    out.append(result(S1, shape, {"graded_as": graded, "kinds": type(kinds).__name__,
                                  "extensions": type(ext).__name__, "signers": type(signers).__name__}))
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
            probs.append({"network": k.get("network"), "basis": "spec",
                          "problem": "extra.feePayer missing or not a 32-byte base58 key"})
        elif fp not in signers_for(str(k.get("network", ""))):
            probs.append({"network": k.get("network"), "feePayer": fp, "basis": "inferred",
                          "problem": "feePayer not listed under any signers pattern matching the network"})
    # A missing or malformed feePayer breaks the SVM exact scheme ("extra.feePayer: The sponsor's public key"), so it is an
    # error. The spec does not say the fee payer must appear in signers; that rule is inferred from V2 7.3.1 ("public
    # signer addresses"), so on its own it is a warning.
    spec_probs = [p for p in probs if p["basis"] == "spec"]
    sev: Severity = "info" if not exact else ("error" if spec_probs else "warning")
    out.append(result(S4, not probs, {"solana_exact_kinds": len(exact), "problems": probs}, severity=sev))
    return out


def run_live(base: str, *, timeout: float = 10, opener: Opener | None = None,
             env: Mapping[str, str] | None = None) -> Json:
    auth_header(base, env)  # a credential without a host is a usage error, before any request is made
    try:
        r = fetch_supported(base, timeout=timeout, opener=opener, env=env)
    except Exception as e:  # noqa: BLE001  a network or JSON failure is itself a result
        status = getattr(e, "code", None)
        err = _redact(repr(e)[:200], env)
        detail: Json = {"error": err, "http": status}
        if status in (401, 403):
            detail["hint"] = f"the facilitator wants credentials; see {AUTH_ENV} and {AUTH_HOST_ENV} in the README"
        return {"target": base, "mode": "live-GET-only", "error": err, "http": status,
                "checks": [result(S0, False, detail)]}
    if r["status"] != 200 or not isinstance(r["json"], dict):
        return {"target": base, "mode": "live-GET-only", "http": r["status"], "ms": r["ms"], "raw": r["raw"],
                "checks": [result(S0, False, {"http": r["status"], "body_type": type(r["json"]).__name__})]}
    return {"target": base, "mode": "live-GET-only", "http": r["status"], "ms": r["ms"],
            "checks": check_supported(r["json"]), "kinds_total": len(r["json"].get("kinds") or []), "raw": r["raw"]}


# ---------------- resource servers, GET only: the 402 answer ----------------
P1 = "P1 an unpaid GET answers HTTP 402 (V2 HTTP transport)"
P2 = "P2 the PaymentRequired object is present and decodes (V2: base64 JSON in PAYMENT-REQUIRED; V1: JSON body)"
P3 = "P3 PaymentRequired has x402Version, resource and a non-empty accepts[] (V2 5.1.2; V1 5.1)"
P4 = "P4 every accepts[] entry has the required fields with valid types (V2 5.1.2; V1 5.1)"
P5 = "P5 scheme-specific extra fields are present (EVM exact: name and version; SVM exact: feePayer)"
P6 = "P6 the PAYMENT-REQUIRED header fits common client limits (warning above 8 KB, error above 16 KB)"
P7 = "P7 an accepts[] entry whose payment flow is not authorization declares extra.paymentFlow (V2 6.1)"
HEADER_WARN, HEADER_ERROR = 8 * 1024, 16 * 1024
# Scheme and network families whose default payment flow is not `authorization` (V2 6.1 and the scheme specs).
NON_AUTHORIZATION_DEFAULTS: tuple[tuple[str, str], ...] = (("upto", "solana:"),)
_DIGITS = re.compile(r"^[0-9]+\Z")  # \Z: "1000\n" is not an amount (in Python $ would match it)


def fetch_402(url: str, timeout: float = 15, opener: Opener | None = None) -> Json:
    """One unpaid GET. A 402 arrives as an HTTPError from urllib; its status, headers and body are the result."""
    req = urllib.request.Request(url, method="GET", headers={"accept": "application/json",
                                                                       "user-agent": user_agent()})
    t0 = time.time()
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            status, headers, body = int(r.status), dict(r.headers.items()), r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        status, headers, body = int(e.code), dict(e.headers.items()) if e.headers else {}, e.read(MAX_BYTES + 1)
    return {"status": status, "headers": {k.lower(): v for k, v in headers.items()}, "body": body[:MAX_BYTES],
            "ms": int((time.time() - t0) * 1000)}


def _decode_header(v: str) -> Any:
    pad = "=" * (-len(v) % 4)
    try:
        raw = base64.b64decode(v + pad, validate=True)
    except (binascii.Error, ValueError):
        raw = base64.urlsafe_b64decode(v + pad)
    return json.loads(raw)


def _accept_problems(a: Any, version: int) -> list[str]:
    if not isinstance(a, dict):
        return ["entry is not an object"]
    p: list[str] = []
    amount_key = "amount" if version == 2 else "maxAmountRequired"
    for k in ("scheme", "network", "asset", "payTo"):
        if not isinstance(a.get(k), str) or not a.get(k):
            p.append(f"{k} missing or not a non-empty string")
    amt = a.get(amount_key)
    if not (isinstance(amt, str) and _DIGITS.match(amt) and int(amt) > 0):
        p.append(f"{amount_key} must be a string of atomic units greater than 0")
    mts = a.get("maxTimeoutSeconds")
    # JSON has one number type: 60 and 60.0 are the same value, and JSON.parse in the TypeScript port cannot tell
    # them apart. So an integral float is an integer here too; 60.5, NaN and booleans are not.
    if not (isinstance(mts, int | float) and not isinstance(mts, bool) and float(mts).is_integer() and mts > 0):
        p.append("maxTimeoutSeconds must be a positive integer")
    if "extra" in a and a["extra"] is not None and not isinstance(a["extra"], dict):
        p.append("extra must be an object")
    if version == 2 and isinstance(a.get("network"), str) and not S.CAIP2.match(a["network"]):
        p.append("network is not CAIP-2")
    if version == 1:
        for k in ("resource", "description"):
            if not isinstance(a.get(k), str):
                p.append(f"{k} missing (required in V1)")
    return p


def _extra_problems(a: Json) -> list[str]:
    scheme, net, extra = a.get("scheme"), str(a.get("network", "")), a.get("extra") or {}
    if scheme != "exact" or not isinstance(extra, dict):
        return []
    if net.startswith("eip155:") or net in S.EVM_V1_NAMES:
        method = extra.get("assetTransferMethod", "eip3009")
        if method == "eip3009" and not (isinstance(extra.get("name"), str) and isinstance(extra.get("version"), str)):
            return ["EVM exact (eip3009) needs extra.name and extra.version, the token's EIP-712 domain"]
        if method not in ("eip3009", "permit2", "erc7710"):
            return [f"EVM exact extra.assetTransferMethod {method!r} is not eip3009, permit2 or erc7710"]
    if net.startswith("solana:") or net in S.SOLANA_V1_NAMES:
        if not S.is_solana_pubkey(extra.get("feePayer")):
            return ["SVM exact needs extra.feePayer, a 32-byte base58 key"]
    return []


def check_402(resp: Json) -> list[CheckResult]:
    out: list[CheckResult] = []
    status = resp["status"]
    out.append(result(P1, status == 402, {"http": status}))
    if status != 402:
        return out
    pr: Any = None
    where, err = None, None
    hv = resp["headers"].get("payment-required")
    if hv:
        where = "PAYMENT-REQUIRED header"
        try:
            pr = _decode_header(hv.strip())
        except Exception as e:  # noqa: BLE001
            err = f"header does not decode as base64 JSON: {type(e).__name__}"
    else:
        try:
            body = json.loads(resp["body"] or b"null")
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("x402Version") == 1:
            where, pr = "JSON body (V1)", body
        else:
            err = "no PAYMENT-REQUIRED header, and the body is not a V1 PaymentRequired"
    out.append(result(P2, isinstance(pr, dict), {"found_in": where, "error": err}))
    if hv:
        size = len(hv.encode("utf-8", "replace"))
        sev: Severity = "error" if size > HEADER_ERROR else "warning"
        out.append(result(P6, size <= HEADER_WARN, {"bytes": size, "warn_above": HEADER_WARN,
                                                    "error_above": HEADER_ERROR}, severity=sev))
    if not isinstance(pr, dict):
        return out
    version = pr.get("x402Version")
    accepts = pr.get("accepts")
    probs: list[str] = []
    if version not in (1, 2):
        probs.append(f"x402Version is {version!r}, not 1 or 2")
    if version == 2 and not (isinstance(pr.get("resource"), dict) and isinstance(pr["resource"].get("url"), str)):
        probs.append("resource.url missing (V2 ResourceInfo)")
    if version == 2 and where != "PAYMENT-REQUIRED header":
        probs.append("V2 carries PaymentRequired in the PAYMENT-REQUIRED header")
    if not (isinstance(accepts, list) and accepts):
        probs.append("accepts[] missing or empty")
    out.append(result(P3, not probs, {"x402Version": version, "problems": probs}))
    if version not in (1, 2) or not (isinstance(accepts, list) and accepts):
        return out
    entries = [{"index": i, "scheme": a.get("scheme") if isinstance(a, dict) else None,
                "network": a.get("network") if isinstance(a, dict) else None,
                "problems": _accept_problems(a, int(version))} for i, a in enumerate(accepts)]
    bad = [e for e in entries if e["problems"]]
    out.append(result(P4, not bad, {"accepts": len(entries), "problems": bad[:10]}))
    xb = [{"index": i, "network": a.get("network"), "problems": pp} for i, a in enumerate(accepts)
          if isinstance(a, dict) and (pp := _extra_problems(a))]
    out.append(result(P5, not xb, {"problems": xb[:10]}))
    if version == 2:
        flow = []
        for i, a in enumerate(accepts):
            if not isinstance(a, dict):
                continue
            extra: Json = a["extra"] if isinstance(a.get("extra"), dict) else {}
            pf = extra.get("paymentFlow")
            if pf is not None and not (isinstance(pf, str) and pf):
                flow.append({"index": i, "problem": "extra.paymentFlow is present but not a non-empty string"})
            elif pf is None and any(a.get("scheme") == sc and str(a.get("network", "")).startswith(net)
                                    for sc, net in NON_AUTHORIZATION_DEFAULTS):
                flow.append({"index": i, "problem": f"{a.get('scheme')} on {a.get('network')} defaults to a "
                             "non-authorization flow, so V2 6.1 requires extra.paymentFlow"})
        # A warning: the upto SVM scheme spec says paymentFlow may be omitted, while V2 6.1 says it MUST be present.
        out.append(result(P7, not flow, {"problems": flow[:10]}, severity="warning"))
    return out


def run_resource(url: str, *, timeout: float = 15, opener: Opener | None = None) -> Json:
    try:
        r = fetch_402(url, timeout=timeout, opener=opener)
    except Exception as e:  # noqa: BLE001
        return {"target": url, "mode": "resource-GET-only", "error": repr(e)[:200],
                "checks": [result(P1, False, {"error": repr(e)[:200]})]}
    return {"target": url, "mode": "resource-GET-only", "http": r["status"], "ms": r["ms"], "checks": check_402(r)}


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


# Amounts Python's int() turns into 10000 but that are not V2 atomic units (a string of ASCII digits, no sign,
# whitespace, separators or leading zeros). F1 requires each to be refused.
NONCANONICAL_AMOUNTS: tuple[str, ...] = (" 10000 ", "+10000", "10_000", "010000", "\uff11\uff10\uff10\uff10\uff10", "10000\n")


F10 = ("F10 a payload settled against one PaymentRequirements set is rejected when re-verified or re-settled "
       "against different requirements (cross-request replay)")


def _f10(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult:
    # A fresh transaction, settled honestly against the quoted requirements, then offered to the same verifier
    # under DIFFERENT requirements at the same price: only a requirements binding at the verifier boundary rejects it.
    p = dict(mk("good"), tx="tx-f10", memo="m-f10")
    first = fac.settle(p, req)
    if not _success(first):
        return result(F10, False, {"note": "first settle failed; nothing settled to replay", "got": first})
    other = dict(req, resource=str(req.get("resource") or "https://paid.example/resource") + "#substituted")
    v_against_other = fac.verify(p, other)
    s_against_other = fac.settle(p, other)
    rejected = (isinstance(v_against_other, dict) and v_against_other.get("isValid") is False
                and not _success(s_against_other))
    return result(F10, rejected, {"verify_against_other": v_against_other, "settle_against_other": s_against_other})


F11 = "F11 /verify is read-only: verifying twice commits nothing, and the payment still settles once (V2 7.1)"


def _f11(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult:
    # V2 7.1: /verify "MUST NOT commit payment state". Two verifies, then a settle: the settle must still succeed.
    p = dict(mk("good"), tx="tx-f11", memo="m-f11")
    v1, v2 = fac.verify(p, req), fac.verify(p, req)
    s = fac.settle(p, req)
    valid = all(isinstance(v, dict) and v.get("isValid") is True for v in (v1, v2))
    return result(F11, valid and _success(s), {"verify": [v1, v2], "settle": s})


F12 = ("F12 /verify answers invalid, with a reason, for a network the facilitator does not support or an asset that "
       "is not a token contract on the network")
# A CAIP-2 id no facilitator supports, and an address with no contract code: both are well formed, so only a
# facilitator that checks the kind it is asked to verify, rather than trusting the requirements, rejects them.
UNSUPPORTED_NETWORK = "x402conf:unsupported"
NO_CODE_ASSET = "x402confNoCodeAsset11111111111111111111111"


def _f12(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult:
    got: dict[str, Any] = {}
    for name, change in (("network", {"network": UNSUPPORTED_NETWORK}), ("asset", {"asset": NO_CODE_ASSET})):
        other = dict(req, **change)
        p = dict(mk("good"), tx=f"tx-f12-{name}", memo=f"m-f12-{name}", mint=other["asset"], dest=other["payTo"])
        try:
            got[name] = fac.verify(p, other)
        except Exception:  # noqa: BLE001  raising is not a structured answer
            got[name] = "raised"
    ok = all(isinstance(v, dict) and v.get("isValid") is False and bool(v.get("invalidReason")) for v in got.values())
    return result(F12, ok, {"unsupported_network": got["network"], "asset_without_code": got["asset"]})


F13 = ("F13 a payment whose on-chain asset differs from the requirement's asset is rejected, even when the amount "
       "and recipient match (V2 5.1.2)")


def _f13(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult:
    # The same amount to the same recipient, paid in a different mint. A verifier that compares only amount and
    # payTo lets the wrong asset settle the route.
    asset = str(req["asset"])
    other_asset = asset[:-1] + ("2" if asset[-1:] != "2" else "3")
    p = dict(mk("good"), tx="tx-f13", memo="m-f13", mint=other_asset)
    v = fac.verify(p, req)
    s = fac.settle(p, req)
    rejected = isinstance(v, dict) and v.get("isValid") is False and not _success(s)
    return result(F13, rejected, {"substituted_mint": other_asset, "verify": v, "settle": s})


F14 = ("F14 a payment whose authorized network differs from the requirement's network is rejected, even when "
       "the amount, recipient and asset match (facilitator-layer network substitution)")
# A real, well-formed CAIP-2 id that differs from the requirement's network: the authorization carries the network
# it was signed for, so presenting it against a route on another network is a cross-domain replay.
OTHER_NETWORK_EVM = "eip155:84532"
OTHER_NETWORK_SVM = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"


def _f14(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult:
    # The same amount, recipient and asset, carrying a different authorized network. A verifier that does not
    # bind the payment's network to the requirement lets a payment for one chain settle a route on another.
    # (The deeper cross-chain-signature replay, an EIP-3009 domain that omits chainId, needs a live signature
    # and is out of the offline doubles' reach; this check covers the facilitator-side binding.)
    other_net = OTHER_NETWORK_EVM if not str(req["network"]).startswith("eip155:") else OTHER_NETWORK_SVM
    p = dict(mk("good"), tx="tx-f14", memo="m-f14", net=other_net)
    v = fac.verify(p, req)
    s = fac.settle(p, req)
    rejected = isinstance(v, dict) and v.get("isValid") is False and not _success(s)
    return result(F14, rejected, {"authorized_network": other_net, "verify": v, "settle": s})


S5 = ("S5 every kind /supported advertises gets a structured /verify answer: valid, or invalid with a reason, never "
      "an error (V2 7.1, 7.3)")


def _s5(fac: Facilitator, mk: Vectors, req: Json) -> CheckResult | None:
    """Sends /verify once for each kind the facilitator advertises. A facilitator double with no supported() is not
    graded; the HTTP adapter reads GET /supported."""
    supported = getattr(fac, "supported", None)
    if not callable(supported):
        return None
    try:
        doc = supported()
    except Exception as e:  # noqa: BLE001  a /supported that fails grades nothing
        return result(S5, False, {"error": f"/supported failed: {type(e).__name__}: {e}"})
    kinds = [k for k in doc.get("kinds", []) if isinstance(k, dict)] if isinstance(doc, dict) else []
    if not kinds:
        return result(S5, False, {"error": "/supported advertises no kinds, so nothing was graded"})
    answers: list[Json] = []
    for i, k in enumerate(kinds):
        kind = {"x402Version": k.get("x402Version"), "scheme": k.get("scheme"), "network": k.get("network")}
        p = dict(mk("good"), tx=f"tx-s5-{i}", memo=f"m-s5-{i}")
        try:
            v: Any = fac.verify(p, dict(req, scheme=kind["scheme"], network=kind["network"]))
        except Exception as e:  # noqa: BLE001  an exception is the in-process form of a 5xx or a dropped answer
            if type(e).__name__ == "Refused":   # the devnet adapter sends devnet requirements only
                answers.append({"kind": kind, "not_sent": str(e)})
                continue
            v = f"raised {type(e).__name__}"
        ok = isinstance(v, dict) and (v.get("isValid") is True
                                      or (v.get("isValid") is False and bool(v.get("invalidReason"))))
        answers.append({"kind": kind, "answer": v, "structured": ok})
    graded = [a for a in answers if "structured" in a]
    bad = [a["kind"] for a in graded if not a["structured"]]
    error = ("no advertised kind could be sent, so nothing was graded" if not graded
             else f"{len(bad)} advertised kind(s) got no structured /verify answer" if bad else None)
    return result(S5, bool(graded) and not bad, {"kinds": answers, **({"error": error} if error else {})})


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
    # Non-canonical amounts that Python's int() accepts but V2 5.1.2 atomic units do not. Each must be refused.
    noncanonical: dict[str, Any] = {}
    for i, amt in enumerate(NONCANONICAL_AMOUNTS):
        bad = dict(good, tx=f"tx-f1-amt-{i}", memo=f"m-f1-amt-{i}", amount=amt)
        try:
            r: Any = fac.verify(bad, req)
        except Exception:  # noqa: BLE001  raising is closed, not open
            r = "raised"
        if not (r == "raised" or (isinstance(r, dict) and r.get("isValid") is False)):
            ok = False
            noncanonical[repr(amt)] = r
    out.append(result("F1 malformed payload: /verify returns isValid=false (fails closed)", ok,
                      {"got": v, **({"accepted_noncanonical_amounts": noncanonical} if noncanonical else {})}))
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
                                   or (bool(d.get("transaction")) and bool(d.get("network"))))
    out.append(result("F5 unconfirmed settlement is not success; settlement_pending carries a transaction and a "
                      "network (V2 9)", pend_ok, {"got": d}))
    rs = make_guard(fac)
    e = rs.settle_and_credit(mk("fresh"), req, simulate="timeout")
    f = rs.settle_and_credit(mk("fresh2"), req, simulate="garbage")
    out.append(result("F6 facilitator timeout or malformed response: resource server does not credit (fail closed)",
                      e is False and f is False, {"timeout_credit": e, "garbage_credit": f}))
    out.append(_f7(fac, mk, req))
    out.append(_f8(fac, mk, req))
    out.append(_f9(fac, mk, req, make_guard))
    out.append(_f10(fac, mk, req))
    out.append(_f11(fac, mk, req))
    out.append(_f12(fac, mk, req))
    out.append(_f13(fac, mk, req))
    out.append(_f14(fac, mk, req))
    s5 = _s5(fac, mk, req)
    if s5 is not None:
        out.append(s5)
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
    """Resource-server faults. trust_any_status (F9) credits whatever a non-200 body says; give_up_after_error (F9)
    treats a lost answer as a failed payment and never retries it; credit_on_error (F6) credits a timeout or an error
    page."""

    def __init__(self, fac: Facilitator, *, trust_any_status: bool = False, give_up_after_error: bool = False,
                 credit_on_error: bool = False) -> None:
        super().__init__(fac)
        self.trust_any_status, self.give_up_after_error = trust_any_status, give_up_after_error
        self.credit_on_error = credit_on_error
        self.given_up: set[str] = set()

    def settle_and_credit(self, payload: Any, req: Json, simulate: str | None = None) -> bool:
        if self.credit_on_error and simulate in ("timeout", "garbage"):
            return True   # the F6 fault: an answer that never came, or an error page, is taken as paid
        return super().settle_and_credit(payload, req, simulate)

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
    "guard_credit_on_error": lambda f: FaultyGuard(f, credit_on_error=True),
}
