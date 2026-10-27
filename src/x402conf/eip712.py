"""EIP-712 typed-data signing for the offline doubles, with no dependency: Keccak-256, secp256k1 ECDSA (RFC 6979
nonces, low-s) and public-key recovery, in plain Python.

It exists for one thing: F14a needs a real signature over an EIP-3009 TransferWithAuthorization whose EIP-712
domain omits chainId, so the doubles can show that such a signature is not bound to any network. The key is a
throwaway generated per run (throwaway_key), never funded, never written anywhere and never sent over a network.
This is test code, not a wallet: it is slow and makes no attempt to be constant-time."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from typing import Any

# ---------------- Keccak-256 (the pre-NIST padding Ethereum uses) ----------------
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _M64 if n else x


def _keccak_f(a: list[list[int]]) -> None:
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x][y] ^= d[x]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        for x in range(5):
            for y in range(5):
                a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])
        a[0][0] ^= rc


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * (-len(msg) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        _keccak_f(a)
    return b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


# ---------------- secp256k1 ----------------
P = 2**256 - 2**32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)
Point = tuple[int, int] | None


def _add(p: Point, q: Point) -> Point:
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % P == 0:
        return None
    if p == q:
        lam = 3 * p[0] * p[0] * pow(2 * p[1], -1, P) % P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, P) % P
    x = (lam * lam - p[0] - q[0]) % P
    return x, (lam * (p[0] - x) - p[1]) % P


def _mul(k: int, p: Point) -> Point:
    r: Point = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)
        k >>= 1
    return r


def address_of(pub: Point) -> str:
    """The EIP-55 checksummed address of a public key."""
    assert pub is not None
    raw = keccak256(pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big"))[12:].hex()
    h = keccak256(raw.encode()).hex()
    return "0x" + "".join(ch.upper() if ch.isalpha() and int(h[i], 16) >= 8 else ch for i, ch in enumerate(raw))


def throwaway_key() -> int:
    """A fresh private key for this run only, from the OS CSPRNG. Never funded; never persisted."""
    return secrets.randbelow(N - 1) + 1


def key_address(priv: int) -> str:
    return address_of(_mul(priv, G))


def _rfc6979_k(priv: int, digest: bytes) -> int:
    x, h = priv.to_bytes(32, "big"), (int.from_bytes(digest, "big") % N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < N:
            return cand
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign_digest(priv: int, digest: bytes) -> str:
    """A 65-byte r || s || v signature (v = 27 or 28, low s), hex with 0x, as wallets return for eth_signTypedData."""
    z = int.from_bytes(digest, "big")
    while True:
        k = _rfc6979_k(priv, digest)
        rp = _mul(k, G)
        assert rp is not None
        r = rp[0] % N
        s = pow(k, -1, N) * (z + r * priv) % N
        if r and s:
            break
    recid = (rp[1] & 1) | (2 if rp[0] >= N else 0)
    if s > N // 2:
        s, recid = N - s, recid ^ 1
    return "0x" + r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex() + bytes([27 + (recid & 1)]).hex()


def recover(digest: bytes, signature: str) -> str | None:
    """The address that signed digest, or None for a signature that is malformed or recovers nothing."""
    try:
        raw = bytes.fromhex(signature[2:] if signature.startswith("0x") else signature)
    except (ValueError, AttributeError):
        return None
    if len(raw) != 65:
        return None
    r, s, v = int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:64], "big"), raw[64]
    v = v - 27 if v >= 27 else v
    if v not in (0, 1) or not (1 <= r < N and 1 <= s <= N // 2):
        return None
    y2 = (pow(r, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if y * y % P != y2:
        return None
    if y & 1 != v:
        y = P - y
    z = int.from_bytes(digest, "big")
    rinv = pow(r, -1, N)
    q = _add(_mul(s * rinv % N, (r, y)), _mul((-z * rinv) % N, G))
    return address_of(q) if q is not None else None


# ---------------- EIP-712 ----------------
# EIP712Domain fields in the order EIP-712 lists them; a domain names only the ones it uses.
DOMAIN_FIELDS: tuple[tuple[str, str], ...] = (("name", "string"), ("version", "string"), ("chainId", "uint256"),
                                              ("verifyingContract", "address"), ("salt", "bytes32"))
TRANSFER_WITH_AUTHORIZATION: tuple[tuple[str, str], ...] = (
    ("from", "address"), ("to", "address"), ("value", "uint256"), ("validAfter", "uint256"),
    ("validBefore", "uint256"), ("nonce", "bytes32"))


def _encode(kind: str, value: Any) -> bytes:
    if kind == "string":
        return keccak256(str(value).encode("utf-8"))
    if kind == "uint256":
        return int(value).to_bytes(32, "big")
    if kind == "address":
        return int(str(value), 16).to_bytes(32, "big")
    if kind == "bytes32":
        raw = bytes.fromhex(str(value)[2:] if str(value).startswith("0x") else str(value))
        if len(raw) != 32:
            raise ValueError("bytes32 must be 32 bytes")
        return raw
    raise ValueError(f"unsupported EIP-712 type {kind}")


def hash_struct(name: str, fields: tuple[tuple[str, str], ...], data: Mapping[str, Any]) -> bytes:
    sig = f"{name}(" + ",".join(f"{t} {n}" for n, t in fields) + ")"
    return keccak256(keccak256(sig.encode()) + b"".join(_encode(t, data[n]) for n, t in fields))


def domain_separator(domain: Mapping[str, Any]) -> bytes:
    """The separator of exactly the fields the domain carries. A domain without chainId hashes to the same value on
    every chain, which is the replay F14a tests."""
    fields = tuple((n, t) for n, t in DOMAIN_FIELDS if n in domain)
    return hash_struct("EIP712Domain", fields, domain)


def transfer_digest(domain: Mapping[str, Any], message: Mapping[str, Any]) -> bytes:
    """The EIP-712 digest of an EIP-3009 TransferWithAuthorization: keccak256(0x1901 || domainSeparator || hashStruct)."""
    return keccak256(b"\x19\x01" + domain_separator(domain)
                     + hash_struct("TransferWithAuthorization", TRANSFER_WITH_AUTHORIZATION, message))
