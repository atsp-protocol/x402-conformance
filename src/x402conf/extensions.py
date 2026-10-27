"""Offline checks for the six extension specs XC-75 names.

Each check is normative, names a line in the vendored snapshot of
x402-foundation/x402 at 0e6e8c55d86b4f14234fb6e49a4052074fb93e57, and has a
control that passes and a faulty build it rejects. Nothing here dials a
network or a facilitator. The offer and receipt digests are checked against
corpus/fixtures/offer-receipt-eip712.json, which was produced outside this
package.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

from . import eip712

SNAPSHOT = "0e6e8c55d86b4f14234fb6e49a4052074fb93e57"
# The address the extension specs' own examples call Canonical Permit2.
PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_DEC = re.compile(r"^[0-9]+$")
_CAIP = re.compile(r"^eip155:[0-9]+$")
_CODE = re.compile(r"^[a-z0-9_]{1,32}$")

# The spec fixes the EIP-712 domain chainId at 1 for both artifacts. That is the
# signing domain, not the payment network. Payment networks in these checks are
# testnet CAIP-2 ids only.
_OFFER_DOMAIN = {"name": "x402 offer", "version": "1", "chainId": 1}
_RECEIPT_DOMAIN = {"name": "x402 receipt", "version": "1", "chainId": 1}
_OFFER_FIELDS = (
    ("version", "uint256"), ("resourceUrl", "string"), ("scheme", "string"), ("network", "string"),
    ("asset", "string"), ("payTo", "string"), ("amount", "string"), ("validUntil", "uint256"))
_RECEIPT_FIELDS = (
    ("version", "uint256"), ("network", "string"), ("resourceUrl", "string"), ("payer", "string"),
    ("issuedAt", "uint256"), ("transaction", "string"))


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def anchor_text(anchor: Mapping[str, Any]) -> str:
    path = os.path.join(_root(), "docs", "spec-snapshots", anchor["upstream_commit"], anchor["spec_file"])
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    start, end = int(anchor["line_start"]), int(anchor["line_end"])
    return "\n".join(lines[start - 1:end])


def anchor_holds(anchor: Mapping[str, Any]) -> bool:
    got = hashlib.sha256(anchor_text(anchor).encode()).hexdigest()
    return got == str(anchor["quoted_text_sha256"])


def _same(addr: object, other: object) -> bool:
    return isinstance(addr, str) and isinstance(other, str) and addr.lower() == other.lower()


def _digest(domain: Mapping[str, Any], primary: str, fields: tuple[tuple[str, str], ...],
            message: Mapping[str, Any]) -> bytes:
    return eip712.keccak256(b"\x19\x01" + eip712.domain_separator(domain)
                            + eip712.hash_struct(primary, fields, message))


def _offer_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The transmitted payload. validUntil is 0 only when the sender omitted it."""
    msg = {name: payload[name] for name, _ in _OFFER_FIELDS if name != "validUntil"}
    msg["validUntil"] = 0 if "validUntil" not in payload or payload["validUntil"] in (None, "") else payload["validUntil"]
    return msg


def _receipt_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The transmitted payload. transaction is empty only when the sender omitted it."""
    msg = {name: payload[name] for name, _ in _RECEIPT_FIELDS if name != "transaction"}
    msg["transaction"] = "" if "transaction" not in payload or payload["transaction"] is None else payload["transaction"]
    return msg


def offer_digest(payload: Mapping[str, Any]) -> bytes:
    return _digest(_OFFER_DOMAIN, "Offer", _OFFER_FIELDS, _offer_message(payload))


def receipt_digest(payload: Mapping[str, Any]) -> bytes:
    return _digest(_RECEIPT_DOMAIN, "Receipt", _RECEIPT_FIELDS, _receipt_message(payload))


def check_eip2612(info: Mapping[str, Any]) -> list[str]:
    """The facilitator requires the spender to be Canonical Permit2."""
    problems = []
    if not _same(info.get("spender"), PERMIT2):
        problems.append("spender")
    sig = info.get("signature")
    if not isinstance(sig, str) or not re.fullmatch(r"0x[0-9a-fA-F]{130}", sig):
        problems.append("signature")
    for field in ("from", "asset"):
        if not isinstance(info.get(field), str) or not _ADDR.fullmatch(info[field]):
            problems.append(field)
    for field in ("amount", "nonce", "deadline"):
        if not isinstance(info.get(field), str) or not _DEC.fullmatch(info[field]):
            problems.append(field)
    return problems


def check_erc20(info: Mapping[str, Any]) -> list[str]:
    """The facilitator requires the extension spender to be Canonical Permit2."""
    problems = []
    if not _same(info.get("spender"), PERMIT2):
        problems.append("spender")
    raw = info.get("signedTransaction")
    if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", raw) or len(raw) < 4:
        problems.append("signedTransaction")
    for field in ("from", "asset"):
        if not isinstance(info.get(field), str) or not _ADDR.fullmatch(info[field]):
            problems.append(field)
    if not isinstance(info.get("amount"), str) or not _DEC.fullmatch(info["amount"]):
        problems.append("amount")
    return problems


def check_offer(doc: Mapping[str, Any]) -> list[str]:
    """Hash the transmitted payload. The signer must be the payload's payTo. The network must be eip155."""
    payload = doc.get("payload")
    if not isinstance(payload, Mapping):
        return ["payload"]
    if not isinstance(payload.get("network"), str) or not _CAIP.fullmatch(payload["network"]):
        return ["network"]
    problems = []
    try:
        digest = offer_digest(payload)
    except (KeyError, TypeError, ValueError):
        return ["digest"]
    signer = eip712.recover(digest, str(doc.get("signature") or ""))
    if signer is None or not _same(signer, payload.get("payTo")):
        problems.append("signer")
    return problems


def check_receipt(doc: Mapping[str, Any], authorized: set[str]) -> list[str]:
    """Hash the transmitted payload. The signer must be one of the addresses authorized for the resource."""
    payload = doc.get("payload")
    if not isinstance(payload, Mapping):
        return ["payload"]
    if not isinstance(payload.get("network"), str) or not _CAIP.fullmatch(payload["network"]):
        return ["network"]
    problems = []
    try:
        digest = receipt_digest(payload)
    except (KeyError, TypeError, ValueError):
        return ["digest"]
    signer = eip712.recover(digest, str(doc.get("signature") or ""))
    allowed = {a.lower() for a in authorized}
    if signer is None or signer.lower() not in allowed:
        problems.append("signer")
    return problems


def declared_app(required: Mapping[str, Any] | None) -> str | None:
    block = (required or {}).get("builder-code")
    if not isinstance(block, Mapping):
        return None
    info = block.get("info")
    if not isinstance(info, Mapping) or "a" not in info:
        return None
    value = info.get("a")
    return value if isinstance(value, str) else None


def check_builder(required: Mapping[str, Any] | None, payload: Mapping[str, Any] | None) -> list[str]:
    """Reject an echoed app code that is not exactly the code the resource server declared."""
    echoed = (payload or {}).get("builder-code")
    if not isinstance(echoed, Mapping) or "a" not in echoed:
        return []
    got = echoed.get("a")
    if not isinstance(got, str) or not _CODE.fullmatch(got) or got != declared_app(required):
        return ["extension_echo_mismatch"]
    return []


def check_http_signatures(info: Mapping[str, Any]) -> list[str]:
    """registrationUrl, signatureSchemes and tags are required."""
    problems = []
    url = info.get("registrationUrl")
    parsed = urllib.parse.urlparse(url) if isinstance(url, str) else None
    if parsed is None or parsed.scheme != "https" or not parsed.netloc:
        problems.append("registrationUrl")
    schemes = info.get("signatureSchemes")
    if not isinstance(schemes, list) or not schemes or not all(isinstance(s, str) and s for s in schemes):
        problems.append("signatureSchemes")
    tags = info.get("tags")
    if not isinstance(tags, list) or not tags or not all(isinstance(s, str) and s for s in tags):
        problems.append("tags")
    return problems


def auth_indexes(accepts_len: int, requirements: list[Mapping[str, Any]]) -> set[int]:
    """Indexes into accepts that require authentication. An index past the array is ignored."""
    found: set[int] = set()
    for entry in requirements:
        for i in entry.get("acceptIndexes") or []:
            if type(i) is int and 0 <= i < accepts_len:
                found.add(i)
    return found


def grade_auth(resolver: Callable[[int, list[Mapping[str, Any]]], set[int]],
               accepts_len: int, requirements: list[Mapping[str, Any]]) -> list[str]:
    if resolver(accepts_len, requirements) != auth_indexes(accepts_len, requirements):
        return ["acceptIndexes"]
    return []


def vectors() -> dict[str, Any]:
    path = os.path.join(_root(), "corpus", "fixtures", "offer-receipt-eip712.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("offer-receipt fixture is not an object")
    return data


def offer_control() -> bool:
    row = vectors()["offer"]
    return check_offer({"payload": row["payload"], "signature": row["signature"]}) == []


def offer_faulty() -> bool:
    row = vectors()["offer"]
    payload = dict(row["payload"])
    payload["network"] = "base-sepolia"
    return check_offer({"payload": payload, "signature": row["signature"]}) == ["network"]


def faulty_auth_keeps_out_of_range(accepts_len: int, requirements: list[Mapping[str, Any]]) -> set[int]:
    """A client that treats an out-of-range acceptIndexes entry as applying."""
    found: set[int] = set()
    for entry in requirements:
        for i in entry.get("acceptIndexes") or []:
            if type(i) is int:
                found.add(i)
    return found


_SIG65 = "0x" + ("11" * 64) + "1b"
_EIP2612_OK = {
    "from": "0x857b06519E91e3A54538791bDbb0E22373e36b66",
    "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "spender": PERMIT2,
    "amount": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
    "nonce": "0",
    "deadline": "1740672154",
    "signature": _SIG65,
    "version": "1",
}
_ERC20_OK = {
    "from": "0x857b06519E91e3A54538791bDbb0E22373e36b66",
    "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "spender": PERMIT2,
    "amount": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
    "signedTransaction": "0x02",
    "version": "1",
}
_HTTP_OK = {
    "registrationUrl": "https://network.example.com/signature-agents",
    "signatureSchemes": ["ed25519"],
    "tags": ["web-bot-auth"],
}
_BUILDER_REQUIRED = {"builder-code": {"info": {"a": "my_app"}}}
_BUILDER_ECHO = {"builder-code": {"a": "my_app", "s": "my_client"}}


def _anchor(spec_file: str, start: int, end: int, digest: str) -> dict[str, Any]:
    return {"spec_file": spec_file, "upstream_commit": SNAPSHOT, "line_start": start, "line_end": end,
            "quoted_text_sha256": digest}


# Six extensions. profile, anchor, and a control/faulty pair. Not part of spec.CATALOG:
# the TypeScript catalogue is kept identical to that dict, and this task's scope does not
# include ts/src/catalog.ts.
EXTENSIONS: dict[str, dict[str, Any]] = {
    "eip2612GasSponsoring": {
        "id": "P11",
        "profile": "normative",
        "basis": "eip2612 gas sponsoring: the facilitator MUST verify that spender matches Canonical Permit2",
        "anchor": _anchor("specs/extensions/eip2612_gas_sponsoring.md", 163, 163,
                          "07a07c45d0e498e97d70c9648af7d32c48060b247cccafe1beb1d10ffea9b397"),
        "control": lambda: check_eip2612(_EIP2612_OK) == [],
        "faulty": lambda: check_eip2612({**_EIP2612_OK, "spender": _EIP2612_OK["asset"]}) == ["spender"],
    },
    "erc20ApprovalGasSponsoring": {
        "id": "P12",
        "profile": "normative",
        "basis": "erc20 gas sponsoring: the facilitator MUST verify that spender matches Canonical Permit2",
        "anchor": _anchor("specs/extensions/erc20_gas_sponsoring.md", 201, 201,
                          "de4b8c46c496da3c4a236bcf1254858e1620f282d5232f17e1068f70819a69e4"),
        "control": lambda: check_erc20(_ERC20_OK) == [],
        "faulty": lambda: check_erc20({**_ERC20_OK, "spender": _ERC20_OK["from"]}) == ["spender"],
    },
    "offer-and-receipt": {
        "id": "P13",
        "profile": "normative",
        "basis": "offer-and-receipt: the verifier hashes the transmitted payload and does not rebuild it from context",
        "anchor": _anchor("specs/extensions/extension-offer-and-receipt.md", 223, 223,
                          "7c08295ceee3e9cc718cbb057ca4593ea488bfbc5c0b73fa05066bf337be05ac"),
        "control": offer_control,
        "faulty": offer_faulty,
    },
    "builder-code": {
        "id": "P14",
        "profile": "normative",
        "basis": "builder-code: the resource server MUST reject an echoed app code that is not the one it declared",
        "anchor": _anchor("specs/extensions/builder_code.md", 319, 319,
                          "bf655b4929bf0aa4783a0f3b218b14cf4180bba5fa9af35c64c3da104c0b5e9d"),
        "control": lambda: check_builder(_BUILDER_REQUIRED, _BUILDER_ECHO) == [],
        "faulty": lambda: check_builder({}, {"builder-code": {"a": "my_app"}}) == ["extension_echo_mismatch"],
    },
    "http-message-signatures": {
        "id": "P15",
        "profile": "normative",
        "basis": "http-message-signatures: registrationUrl, signatureSchemes and tags are required",
        "anchor": _anchor("specs/extensions/http-message-signatures.md", 53, 55,
                          "7fb27f7ee823f9e5c3c7b152850b5e117e320a377060140fb064266052aeba7a"),
        "control": lambda: check_http_signatures(_HTTP_OK) == [],
        "faulty": lambda: "signatureSchemes" in check_http_signatures(
            {k: v for k, v in _HTTP_OK.items() if k != "signatureSchemes"}),
    },
    "auth-hints": {
        "id": "P16",
        "profile": "normative",
        "basis": "auth-hints: a client MUST ignore an acceptIndexes entry that is outside accepts",
        "anchor": _anchor("specs/extensions/extension-auth-hints.md", 153, 153,
                          "d162fc3e7dc4960119f043c837333136b1e3da04ff81939621f01d7e32e06273"),
        "control": lambda: grade_auth(auth_indexes, 2, [{"acceptIndexes": [1, 9]}]) == [],
        "faulty": lambda: grade_auth(faulty_auth_keeps_out_of_range, 2, [{"acceptIndexes": [1, 9]}]) == ["acceptIndexes"],
    },
}
