"""In-process facilitator doubles for the offline checks. Nothing here touches a network. The only key is F14a's
throwaway signer, generated per run in memory (eip712.throwaway_key) and never funded or written anywhere."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from importlib import resources
from typing import Any

from . import eip712
from . import spec as S
from .types import Json

Vectors = Callable[[str], Any]


def load_fixture(name: str = "devnet") -> Json:
    data: Json = json.loads(resources.files("x402conf").joinpath(f"fixtures/{name}.json").read_text("utf-8"))
    return data


def requirements_hash(req: Json) -> str:
    """The binding a verifier can actually enforce: a stable hash of the exact PaymentRequirements a payload was
    verified against. The exact scheme binds amount, asset and payTo on chain, the memo binds nonce uniqueness,
    and the authorization's domain binds the network it was signed for (chainId); no scheme field binds the
    protected resource, so the resource binding lives at the verifier boundary."""
    return hashlib.sha256(json.dumps(req, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


_ATOMIC = re.compile(r"(?:0|[1-9][0-9]{0,77})")   # ASCII digits only, no sign, no whitespace, no leading zeros
UINT256_MAX = 2**256 - 1


def atomic_units(x: Any, *, allow_int: bool = False) -> int | None:
    """Strict atomic-unit parser. V2 5.1.2 carries `amount` as a string of atomic token units; the decoded stand-in
    payloads may also carry a plain JSON integer (allow_int). Anything else, including what Python's int() would
    accept (" 10 ", "+10", "1_0", "010", non-ASCII digits, booleans, floats), is None, so callers fail closed instead
    of raising or accepting a non-canonical amount."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int) and allow_int:
        v = x
    elif isinstance(x, str) and _ATOMIC.fullmatch(x):
        v = int(x)
    else:
        return None
    return v if 0 <= v <= UINT256_MAX else None


def _lenient_units(x: Any, *, allow_int: bool = False) -> int | None:
    """The fault the lenient_amounts double reproduces: Python's int(), with its exceptions caught."""
    try:
        return int(x)
    except (TypeError, ValueError, OverflowError):
        return None


def vectors(fixture: Json | None = None) -> Vectors:
    fx = fixture or load_fixture()
    req: Json = fx["requirements"]
    table: dict[str, Any] = {"req": req}
    for k, v in fx["vectors"].items():
        table[k] = dict(v, mint=req["asset"], dest=req["payTo"], net=req["network"]) if v.get("tx") else dict(v)
    return lambda k: copy.deepcopy(table[k])


# Two EVM testnets and one token deployed at the same address on both (as CREATE2 deployments are), so an EIP-3009
# authorization whose EIP-712 domain omits chainId hashes, and verifies, identically on each. F14a signs on the first
# and replays on the second. Testnet ids only; the address is synthetic and nothing is ever sent to either chain.
EVM_NETWORK_A = "eip155:84532"       # Base Sepolia
EVM_NETWORK_B = "eip155:11155111"    # Ethereum Sepolia
SAME_ADDRESS_TOKEN = "0x402c00000000000000000000000000000000f14a"
EVM_TOKEN_DOMAIN: Json = {"name": "USDC", "version": "2"}


def evm_chain_id(network: str) -> int | None:
    """The EIP-155 chain id of an eip155 CAIP-2 network, or None."""
    m = re.fullmatch(r"eip155:([1-9][0-9]{0,18})", network)
    return int(m.group(1)) if m else None


def _fail(reason: str, req: Json, tx: str = "") -> Json:
    return {"success": False, "errorReason": reason, "transaction": tx, "network": req.get("network")}


class Chain:
    """A simulated ledger the offline checks can advance. By default a payload's own `finalized` flag decides its
    status; set() overrides it per transaction, so the same /settle body can be retried as the chain moves on."""

    PENDING, CONFIRMED, FAILED = "pending", "confirmed", "failed"

    def __init__(self) -> None:
        self.overrides: dict[str, str] = {}

    def set(self, tx: str, status: str) -> None:
        self.overrides[tx] = status

    def status(self, p: Json) -> str:
        return self.overrides.get(p["tx"], self.CONFIRMED if p.get("finalized") else self.PENDING)


class Reference:
    """Behaves as the spec asks: exact outcome checks, a duplicate-settlement cache, memo uniqueness, finality.

    A payment is recorded as settled only once its outcome is final. settlement_pending is non-terminal (V2 section 9),
    so a retry of the same body while it is pending is settled again and returns the eventual outcome: the same
    transaction on success, invalid_transaction_state once the chain reports a failure. A failure is terminal and stays
    terminal. A retry after a final success is a true duplicate and gets duplicate_settlement."""

    def __init__(self) -> None:
        self.chain = Chain()
        self.settled: set[str] = set()       # transactions whose success was final and reported
        self.failed: set[str] = set()        # transactions the chain reported as failed
        self.memo_tx: dict[str, str] = {}    # memo -> the transaction that holds it, in flight or settled
        self.req_hash: dict[str, str] = {}   # transaction -> the requirements hash it was verified under
        fx = load_fixture()["requirements"]
        self.networks: set[str] = {fx["network"]}              # the networks /supported advertises
        self.tokens: set[tuple[str, str]] = {(fx["network"], fx["asset"])}   # (network, asset) with token code
        for net in (EVM_NETWORK_A, EVM_NETWORK_B):
            self.networks.add(net)
            self.tokens.add((net, SAME_ADDRESS_TOKEN))

    def supported(self) -> Json:
        """GET /supported: one exact V2 kind for each network this facilitator verifies (V2 7.3)."""
        return {"kinds": [{"x402Version": 2, "scheme": "exact", "network": n} for n in sorted(self.networks)],
                "extensions": [], "signers": {}}

    def _payment_matches(self, p: Any, req: Json) -> Json | None:
        """Fail-closed conformance of the payload to the CURRENT requirements. None means it matches."""
        if not isinstance(req, dict) or any(k not in req for k in ("asset", "payTo", "amount", "network")):
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        if not isinstance(p, dict) or not p.get("tx") or not p.get("memo"):
            return {"isValid": False, "invalidReason": "invalid_payload"}
        if p.get("mint") != req["asset"] or p.get("dest") != req["payTo"]:
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        kind = self._kind(req)
        if kind is not None:
            return kind
        if p.get("net") != req["network"]:
            # the authorization carries the network it was signed for; a payment authorized for another
            # network (a cross-chain / EIP-3009 cross-domain replay) is not valid here even when amount,
            # asset and payTo match.
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        required = self._units(req["amount"])
        if required is None or required <= 0:
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        paid = self._units(p.get("amount"), allow_int=True)
        if paid is None:
            return {"isValid": False, "invalidReason": "invalid_payload"}
        if paid < required:
            return {"isValid": False, "invalidReason": "insufficient_funds"}
        if "authorization" in p or evm_chain_id(str(req["network"])) is not None:
            return self._evm_authorization(p, req, required)
        return None

    def _domain_bound(self, domain: Json, chain_id: int) -> bool:
        """EIP-712 binds a signature to a chain only through the domain's chainId. A domain without one is valid on
        every chain that has the same verifying contract, so the reference requires it, and requires it to be the
        requirement's chain."""
        return isinstance(domain.get("chainId"), int) and not isinstance(domain.get("chainId"), bool) \
            and domain["chainId"] == chain_id

    def _evm_authorization(self, p: Json, req: Json, required: int) -> Json | None:
        """An EIP-3009 TransferWithAuthorization (EVM exact): the signed domain is bound to the requirement's chain
        and token, the signature recovers to `from`, and the signed recipient and value match the requirement."""
        bad = {"isValid": False, "invalidReason": "invalid_exact_evm_payload_signature"}
        a = p.get("authorization")
        chain_id = evm_chain_id(str(req["network"]))
        if not isinstance(a, dict) or chain_id is None:
            return {"isValid": False, "invalidReason": "invalid_payload"}
        domain, msg, sig = a.get("domain"), a.get("message"), a.get("signature")
        if not isinstance(domain, dict) or not isinstance(msg, dict) or not isinstance(sig, str):
            return {"isValid": False, "invalidReason": "invalid_payload"}
        if not self._domain_bound(domain, chain_id):
            return bad
        if str(domain.get("verifyingContract", "")).lower() != str(req["asset"]).lower():
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        try:
            signer = eip712.recover(eip712.transfer_digest(domain, msg), sig)
        except (KeyError, TypeError, ValueError):
            return {"isValid": False, "invalidReason": "invalid_payload"}
        if signer is None or signer.lower() != str(msg.get("from", "")).lower():
            return bad
        if str(msg.get("to", "")).lower() != str(req["payTo"]).lower():
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        value = atomic_units(str(msg.get("value")))
        if value is None or value < required:
            return {"isValid": False, "invalidReason": "insufficient_funds"}
        return None

    def _units(self, x: Any, *, allow_int: bool = False) -> int | None:
        return atomic_units(x, allow_int=allow_int)

    def _kind(self, req: Json) -> Json | None:
        """A network this facilitator supports, and an asset that is a token contract on it. None means both hold."""
        if req["network"] not in self.networks:
            return {"isValid": False, "invalidReason": "unsupported_network"}
        if (req["network"], req["asset"]) not in self.tokens:
            return {"isValid": False, "invalidReason": "invalid_asset"}
        return None

    def verify(self, p: Any, req: Json) -> Json:
        mismatch = self._payment_matches(p, req)
        if mismatch is not None:
            return mismatch
        prev = self.req_hash.get(p["tx"])
        if prev is not None and prev != requirements_hash(req):
            # the transaction was already verified against a different requirements set: cross-request replay
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        return {"isValid": True}

    def _dup(self, p: Json) -> bool:
        return p["tx"] in self.settled or self.memo_tx.get(p["memo"], p["tx"]) != p["tx"]

    def _status(self, p: Json) -> str:
        return self.chain.status(p)

    def _on_pending(self, p: Json) -> None:
        """Hook for the faulty doubles. The reference records nothing final while a payment is pending."""

    def settle(self, p: Any, req: Json) -> Json:
        v = self.verify(p, req)
        if not v["isValid"]:
            return _fail(v["invalidReason"], req)
        self.req_hash.setdefault(p["tx"], requirements_hash(req))
        if self._dup(p):
            return _fail(S.DUPLICATE_SETTLEMENT, req)
        if p["tx"] in self.failed:
            return _fail(S.INVALID_TRANSACTION_STATE, req, p["tx"])
        self.memo_tx[p["memo"]] = p["tx"]
        status = self._status(p)
        if status == Chain.PENDING:
            self._on_pending(p)
            return _fail(S.SETTLEMENT_PENDING, req, p["tx"])
        if status == Chain.FAILED:
            self.failed.add(p["tx"])
            self.memo_tx.pop(p["memo"], None)   # a failed transaction consumed nothing on chain
            return _fail(S.INVALID_TRANSACTION_STATE, req, p["tx"])
        self.settled.add(p["tx"])
        return {"success": True, "transaction": p["tx"], "network": req["network"]}


# A network only a faulty double advertises: S5 sends /verify for it like any other advertised kind.
ADVERTISED_ONLY = "x402conf:advertised-only"


class Faulty(Reference):
    """Each flag reproduces one failure the suite must catch. no_dup_cache is a stateless facilitator with no
    in-flight cache at all (the race described in the SVM spec's Duplicate Settlement Mitigation section).
    burn_on_pending marks a payment as seen before it is final, so a retry of a pending settlement is answered with
    duplicate_settlement and never reaches its outcome. stuck_pending keeps answering settlement_pending after the
    chain has reported the transaction as failed."""

    def __init__(self, *, open_on_malformed: bool = False, accept_dust: bool = False, no_dup_cache: bool = False,
                 no_memo_check: bool = False, success_before_final: bool = False, burn_on_pending: bool = False,
                 stuck_pending: bool = False, cross_request_replay: bool = False,
                 lenient_amounts: bool = False, pending_without_tx: bool = False,
                 verify_commits: bool = False, trust_kind: bool = False, advertise_unhandled: bool = False,
                 reasonless_invalid: bool = False, trust_asset: bool = False,
                 trust_network: bool = False, chainless_domain: bool = False,
                 http_500_non_object: bool = False, http_500_empty: bool = False,
                 http_500_no_authorization: bool = False) -> None:
        super().__init__()
        self.open_on_malformed, self.accept_dust = open_on_malformed, accept_dust
        self.no_dup_cache, self.no_memo_check = no_dup_cache, no_memo_check
        self.success_before_final = success_before_final
        self.burn_on_pending, self.stuck_pending = burn_on_pending, stuck_pending
        self.cross_request_replay = cross_request_replay
        self.lenient_amounts = lenient_amounts
        self.pending_without_tx, self.verify_commits = pending_without_tx, verify_commits
        self.trust_kind = trust_kind
        self.advertise_unhandled, self.reasonless_invalid = advertise_unhandled, reasonless_invalid
        self.trust_asset, self.trust_network = trust_asset, trust_network
        self.chainless_domain = chainless_domain
        self.http_500_non_object = http_500_non_object
        self.http_500_empty = http_500_empty
        self.http_500_no_authorization = http_500_no_authorization
        self.burned: set[str] = set()

    def supported(self) -> Json:
        doc = super().supported()
        if self.advertise_unhandled or self.reasonless_invalid:
            # the fault: /supported names a kind that /verify has no answer for
            doc["kinds"].append({"x402Version": 2, "scheme": "exact", "network": ADVERTISED_ONLY})
        return doc

    def verify(self, p: Any, req: Json) -> Json:
        # The in-process form of HTTP 500: the library raises instead of returning invalid_payload.
        if self.http_500_non_object and not isinstance(p, dict):
            raise RuntimeError("non-object payload")
        if self.http_500_empty and isinstance(p, dict) and not p:
            raise RuntimeError("empty object payload")
        if (self.http_500_no_authorization and isinstance(p, dict) and p
                and "authorization" not in p and not p.get("tx")):
            raise RuntimeError("authorization-less payload")
        if isinstance(req, dict) and req.get("network") == ADVERTISED_ONLY:
            if self.advertise_unhandled:
                raise KeyError(f"no verifier registered for {ADVERTISED_ONLY}")   # in HTTP terms, a 500
            if self.reasonless_invalid:
                return {"isValid": False}
        v = self._verify(p, req)
        if self.verify_commits and v.get("isValid") and isinstance(p, dict):
            # the fault: /verify records the payment as settled, so the settle that follows is a "duplicate"
            self.settled.add(p["tx"])
        return v

    def _verify(self, p: Any, req: Json) -> Json:
        if self.open_on_malformed and (not isinstance(p, dict) or not p.get("tx")):
            return {"isValid": True}
        if self.accept_dust and isinstance(p, dict) and p.get("tx"):
            return {"isValid": True}
        mismatch = self._payment_matches(p, req)
        if mismatch is not None:
            return mismatch
        if self.cross_request_replay:
            return {"isValid": True}   # the fault: no requirements binding at the verifier boundary
        prev = self.req_hash.get(p["tx"])
        if prev is not None and prev != requirements_hash(req):
            return {"isValid": False, "invalidReason": "invalid_payment_requirements"}
        return {"isValid": True}

    def _payment_matches(self, p: Any, req: Json) -> Json | None:
        if isinstance(p, dict) and isinstance(req, dict):
            if self.trust_asset and "asset" in req:
                p = dict(p, mint=req["asset"])      # the fault: the paid asset is taken from the requirement on trust
            if self.trust_network and "network" in req:
                p = dict(p, net=req["network"])     # the fault: the authorization network is taken on trust
        return super()._payment_matches(p, req)

    def _domain_bound(self, domain: Json, chain_id: int) -> bool:
        if self.chainless_domain and "chainId" not in domain:
            return True   # the fault: a domain with no chainId is accepted, so its signature is valid on every chain
        return super()._domain_bound(domain, chain_id)

    def _kind(self, req: Json) -> Json | None:
        # the fault: the network and asset are taken from the requirements on trust
        return None if self.trust_kind else super()._kind(req)

    def _units(self, x: Any, *, allow_int: bool = False) -> int | None:
        if self.lenient_amounts:
            return _lenient_units(x, allow_int=allow_int)
        return super()._units(x, allow_int=allow_int)

    def settle(self, p: Any, req: Json) -> Json:
        if self.open_on_malformed and (not isinstance(p, dict) or not p.get("tx")):
            return _fail("invalid_payload", req)   # a lenient verify; settle cannot proceed without a transaction
        r = super().settle(p, req)
        if self.pending_without_tx and r.get("errorReason") == S.SETTLEMENT_PENDING:
            # the fault: settlement_pending with no broadcast hash or network to reconcile against
            r = {"success": False, "errorReason": S.SETTLEMENT_PENDING}
        return r

    def _dup(self, p: Json) -> bool:
        if self.no_dup_cache:
            return False
        if self.burn_on_pending and p["tx"] in self.burned:
            return True
        if self.no_memo_check:
            return p["tx"] in self.settled
        return super()._dup(p)

    def _status(self, p: Json) -> str:
        s = super()._status(p)
        if self.success_before_final and s == Chain.PENDING:
            return Chain.CONFIRMED
        if self.stuck_pending and s == Chain.FAILED:
            return Chain.PENDING
        return s

    def _on_pending(self, p: Json) -> None:
        if self.burn_on_pending:
            self.burned.add(p["tx"])


FAULTS: dict[str, Callable[[], Reference]] = {
    "reference": Reference,
    "open_on_malformed": lambda: Faulty(open_on_malformed=True),
    "accept_dust": lambda: Faulty(accept_dust=True),
    "no_dup_cache": lambda: Faulty(no_dup_cache=True),
    "no_memo_check": lambda: Faulty(no_memo_check=True),
    "success_before_final": lambda: Faulty(success_before_final=True),
    "burn_on_pending": lambda: Faulty(burn_on_pending=True),
    "stuck_pending": lambda: Faulty(stuck_pending=True),
    "cross_request_replay": lambda: Faulty(cross_request_replay=True),
    "lenient_amounts": lambda: Faulty(lenient_amounts=True),
    "pending_without_tx": lambda: Faulty(pending_without_tx=True),
    "verify_commits": lambda: Faulty(verify_commits=True),
    "trust_kind": lambda: Faulty(trust_kind=True),
    "trust_asset": lambda: Faulty(trust_asset=True),
    "trust_network": lambda: Faulty(trust_network=True),
    "chainless_domain": lambda: Faulty(chainless_domain=True),
    "advertise_unhandled": lambda: Faulty(advertise_unhandled=True),
    "reasonless_invalid": lambda: Faulty(reasonless_invalid=True),
    "http_500_non_object": lambda: Faulty(http_500_non_object=True),
    "http_500_empty": lambda: Faulty(http_500_empty=True),
    "http_500_no_authorization": lambda: Faulty(http_500_no_authorization=True),
}


class RegisteredNetwork:
    """Registered for one exact network. A different network, including the same family, is invalid_network.

    Nothing is dialed. The object only answers the verify call the offline check makes."""

    def __init__(self, network: str) -> None:
        self.network = network

    def verify(self, _p: Any, req: Json) -> Json:
        net = req.get("network") if isinstance(req, dict) else None
        if net != self.network:
            return {"isValid": False, "invalidReason": "invalid_network"}
        return {"isValid": True}


class WildcardFamily:
    """The fault: every network in the family is accepted, which is a wildcard registration."""

    def __init__(self, family: str) -> None:
        self.family = family

    def verify(self, _p: Any, req: Json) -> Json:
        net = str(req.get("network")) if isinstance(req, dict) else ""
        if net.startswith(self.family + ":"):
            return {"isValid": True}
        return {"isValid": False, "invalidReason": "invalid_network"}
