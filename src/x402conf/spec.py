"""Identifiers quoted from the x402 V2 specification (specs/x402-specification-v2.md), the Solana `exact` scheme
(specs/schemes/exact/scheme_exact_svm.md) and https://solana.com/docs/payments/agentic-payments/x402.
Read on 2026-10-20 at x402-foundation/x402 commit 0e6e8c55d86b4f14234fb6e49a4052074fb93e57."""

from __future__ import annotations

import re
from typing import Final

X402_VERSION: Final = 2
SOLANA_MAINNET: Final = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
SOLANA_DEVNET: Final = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
SOLANA_DEVNET_USDC: Final = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
# V1 network names. V2 kinds must use CAIP-2 instead.
SOLANA_V1_NAMES: Final = frozenset({"solana", "solana-devnet", "solana-mainnet", "solana-testnet"})
# V1 EVM network names (V1 used names, not CAIP-2).
EVM_V1_NAMES: Final = frozenset({"base", "base-sepolia", "avalanche", "avalanche-fuji", "polygon", "polygon-amoy",
                                 "ethereum", "sepolia", "iotex", "sei", "sei-testnet"})
CAIP2: Final = re.compile(r"^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}$")
SETTLEMENT_PENDING: Final = "settlement_pending"      # V2 section 9, non-terminal
DUPLICATE_SETTLEMENT: Final = "duplicate_settlement"  # SVM exact, Duplicate Settlement Mitigation
INVALID_TRANSACTION_STATE: Final = "invalid_transaction_state"  # V2 section 9, the transaction failed on chain
_B58: Final = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            raise ValueError("not base58")
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def is_solana_pubkey(s: object) -> bool:
    if not isinstance(s, str) or not 32 <= len(s) <= 44:
        return False
    try:
        return len(b58decode(s)) == 32
    except ValueError:
        return False
