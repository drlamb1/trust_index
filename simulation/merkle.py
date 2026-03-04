"""Merkle tree anchoring for the simulation log.

Provides tamper-evident integrity for the SimulationLog. Each log entry
gets a SHA-256 content hash on write. Daily, a Merkle tree is built over
the day's entries and the root hash is stored as a MerkleAnchor.

The root can later be published to a blockchain (OpenTimestamps, L2, etc.)
for cryptographic proof that the log existed at a point in time and has
not been altered. The chain is the witness, not the warehouse.

References:
  - Merkle, R. C. (1988). A Digital Signature Based on a Conventional
    Encryption Function. CRYPTO '87.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def compute_entry_hash(
    agent_name: str,
    event_type: str,
    event_data: dict[str, Any] | None,
    created_at: datetime,
    thesis_id: int | None = None,
) -> str:
    """Compute a deterministic SHA-256 hash of a simulation log entry.

    Uses canonical JSON serialization (sorted keys, no whitespace,
    ISO-format timestamps) so the same content always produces the
    same hash regardless of when or where it's computed.
    """
    canonical = json.dumps(
        {
            "agent_name": agent_name,
            "event_type": event_type,
            "event_data": event_data,
            "created_at": created_at.isoformat() if created_at else None,
            "thesis_id": thesis_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_pair(a: str, b: str) -> str:
    """Hash two hex digest strings together (sorted for determinism)."""
    combined = min(a, b) + max(a, b)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def build_merkle_tree(hashes: list[str]) -> tuple[str, dict[str, list[str]]]:
    """Build a Merkle tree from a list of leaf hashes.

    Returns:
        (root_hash, proofs) where proofs maps each leaf hash to its
        proof path — a list of sibling hashes needed to recompute the
        root. Verification uses sorted pairing so no left/right tracking
        is needed.

    If the list has an odd number of elements, the last element is
    duplicated (standard Merkle tree padding).
    """
    if not hashes:
        return "", {}

    if len(hashes) == 1:
        return hashes[0], {hashes[0]: []}

    n = len(hashes)

    # Build the tree bottom-up, storing all levels.
    # levels[0] = leaves, levels[-1] = [root]
    levels: list[list[str]] = [list(hashes)]

    current = list(hashes)
    while len(current) > 1:
        # Pad odd levels
        if len(current) % 2 == 1:
            current.append(current[-1])
        next_level = []
        for i in range(0, len(current), 2):
            next_level.append(_hash_pair(current[i], current[i + 1]))
        levels.append(next_level)
        current = next_level

    root = levels[-1][0]

    # Build proofs by walking from each leaf up through the levels
    proofs: dict[str, list[str]] = {}
    for leaf_idx in range(n):
        proof: list[str] = []
        idx = leaf_idx
        for level in levels[:-1]:  # all levels except root
            # Pad if needed (same logic as tree build)
            padded = list(level)
            if len(padded) % 2 == 1:
                padded.append(padded[-1])
            # Sibling index
            sibling_idx = idx ^ 1  # flip last bit
            proof.append(padded[sibling_idx])
            idx //= 2  # parent index in next level
        proofs[hashes[leaf_idx]] = proof

    return root, proofs


def verify_proof(leaf_hash: str, proof: list[str], root: str) -> bool:
    """Verify that a leaf hash belongs to a Merkle tree with the given root.

    Args:
        leaf_hash: The SHA-256 hash of the entry to verify.
        proof: The proof path from build_merkle_tree (list of sibling hashes).
        root: The expected Merkle root.

    Returns:
        True if the proof is valid and the leaf belongs to the tree.
    """
    current = leaf_hash
    for sibling in proof:
        current = _hash_pair(current, sibling)
    return current == root
