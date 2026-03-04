"""Tests for Merkle tree anchoring — tamper-evident simulation log integrity."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import MerkleAnchor, SimulationLog
from simulation.merkle import (
    build_merkle_tree,
    compute_entry_hash,
    verify_proof,
)


# ---------------------------------------------------------------------------
# Pure unit tests — no DB
# ---------------------------------------------------------------------------


class TestComputeEntryHash:
    def test_deterministic(self):
        """Same inputs always produce the same hash."""
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        h1 = compute_entry_hash("edge", "NOTE", {"msg": "hello"}, ts, thesis_id=None)
        h2 = compute_entry_hash("edge", "NOTE", {"msg": "hello"}, ts, thesis_id=None)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_data_different_hash(self):
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        h1 = compute_entry_hash("edge", "NOTE", {"msg": "hello"}, ts)
        h2 = compute_entry_hash("edge", "NOTE", {"msg": "world"}, ts)
        assert h1 != h2

    def test_different_agent_different_hash(self):
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        h1 = compute_entry_hash("edge", "NOTE", {"msg": "hello"}, ts)
        h2 = compute_entry_hash("pm", "NOTE", {"msg": "hello"}, ts)
        assert h1 != h2

    def test_none_event_data(self):
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        h = compute_entry_hash("edge", "NOTE", None, ts)
        assert len(h) == 64

    def test_thesis_id_matters(self):
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        h1 = compute_entry_hash("edge", "NOTE", None, ts, thesis_id=1)
        h2 = compute_entry_hash("edge", "NOTE", None, ts, thesis_id=2)
        assert h1 != h2


class TestBuildMerkleTree:
    def test_empty_list(self):
        root, proofs = build_merkle_tree([])
        assert root == ""
        assert proofs == {}

    def test_single_entry(self):
        root, proofs = build_merkle_tree(["abc123"])
        assert root == "abc123"
        assert proofs == {"abc123": []}

    def test_two_entries(self):
        hashes = ["aaa", "bbb"]
        root, proofs = build_merkle_tree(hashes)
        assert root != ""
        assert len(proofs) == 2
        # Both leaves should verify
        assert verify_proof("aaa", proofs["aaa"], root)
        assert verify_proof("bbb", proofs["bbb"], root)

    def test_three_entries_odd_padding(self):
        hashes = ["aaa", "bbb", "ccc"]
        root, proofs = build_merkle_tree(hashes)
        for h in hashes:
            assert verify_proof(h, proofs[h], root), f"Proof failed for {h}"

    def test_power_of_two(self):
        hashes = [f"hash_{i:03d}" for i in range(8)]
        root, proofs = build_merkle_tree(hashes)
        for h in hashes:
            assert verify_proof(h, proofs[h], root)

    def test_large_tree(self):
        hashes = [f"entry_{i:04d}" for i in range(100)]
        root, proofs = build_merkle_tree(hashes)
        assert len(proofs) == 100
        # Spot check several
        for h in [hashes[0], hashes[49], hashes[99]]:
            assert verify_proof(h, proofs[h], root)

    def test_tamper_detection(self):
        """Changing one leaf should break all proofs that depend on it."""
        hashes = ["aaa", "bbb", "ccc", "ddd"]
        root, proofs = build_merkle_tree(hashes)
        # Tamper: try verifying a different hash with aaa's proof
        assert not verify_proof("zzz", proofs["aaa"], root)


class TestVerifyProof:
    def test_valid_proof(self):
        hashes = ["x", "y"]
        root, proofs = build_merkle_tree(hashes)
        assert verify_proof("x", proofs["x"], root)

    def test_wrong_root(self):
        hashes = ["x", "y"]
        root, proofs = build_merkle_tree(hashes)
        assert not verify_proof("x", proofs["x"], "wrong_root")

    def test_empty_proof_single_entry(self):
        root, proofs = build_merkle_tree(["only"])
        assert verify_proof("only", [], "only")


# ---------------------------------------------------------------------------
# Integration tests — with DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_hash_auto_computed_on_insert(db_session: AsyncSession):
    """The before_insert event listener should auto-compute content_hash."""
    entry = SimulationLog(
        agent_name="test_agent",
        event_type="NOTE",
        event_data={"msg": "integrity test"},
    )
    db_session.add(entry)
    await db_session.flush()

    assert entry.content_hash is not None
    assert len(entry.content_hash) == 64


@pytest.mark.asyncio
async def test_content_hash_matches_recomputation(db_session: AsyncSession):
    """Stored hash should match independent recomputation."""
    entry = SimulationLog(
        agent_name="test_agent",
        event_type="NOTE",
        event_data={"msg": "recompute test"},
    )
    db_session.add(entry)
    await db_session.flush()

    recomputed = compute_entry_hash(
        agent_name=entry.agent_name,
        event_type=entry.event_type,
        event_data=entry.event_data,
        created_at=entry.created_at,
        thesis_id=entry.thesis_id,
    )
    assert entry.content_hash == recomputed


@pytest.mark.asyncio
async def test_merkle_anchor_model(db_session: AsyncSession):
    """MerkleAnchor can be created and queried."""
    anchor = MerkleAnchor(
        anchor_date="2026-03-03",
        merkle_root="a" * 64,
        entry_count=5,
        entry_hashes=["h1", "h2", "h3", "h4", "h5"],
    )
    db_session.add(anchor)
    await db_session.flush()

    result = await db_session.execute(
        select(MerkleAnchor).where(MerkleAnchor.anchor_date == "2026-03-03")
    )
    loaded = result.scalar_one()
    assert loaded.merkle_root == "a" * 64
    assert loaded.entry_count == 5
    assert loaded.entry_hashes == ["h1", "h2", "h3", "h4", "h5"]
    assert loaded.chain_tx_id is None


@pytest.mark.asyncio
async def test_end_to_end_verify(db_session: AsyncSession):
    """Full round-trip: insert entries, build tree, verify each."""
    entries = []
    for i in range(5):
        e = SimulationLog(
            agent_name="test",
            event_type="NOTE",
            event_data={"index": i},
        )
        db_session.add(e)
        entries.append(e)

    await db_session.flush()

    hashes = [e.content_hash for e in entries]
    assert all(h is not None for h in hashes)

    root, proofs = build_merkle_tree(hashes)

    # Store anchor
    anchor = MerkleAnchor(
        anchor_date="2026-03-03",
        merkle_root=root,
        entry_count=len(entries),
        entry_hashes=hashes,
    )
    db_session.add(anchor)
    await db_session.flush()

    # Verify each entry
    for e in entries:
        assert verify_proof(e.content_hash, proofs[e.content_hash], root)

    # Verify tamper detection: if we change an entry's data, recomputed hash won't match
    tampered_hash = compute_entry_hash(
        agent_name="test",
        event_type="NOTE",
        event_data={"index": 999},  # tampered
        created_at=entries[0].created_at,
        thesis_id=None,
    )
    assert tampered_hash != entries[0].content_hash
    assert not verify_proof(tampered_hash, proofs[entries[0].content_hash], root)
