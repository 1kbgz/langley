"""Tests for langley.store (SqliteStateStore)."""

import pytest

from langley.models import CheckpointData
from langley.store import SqliteStateStore


@pytest.fixture()
def store(tmp_path):
    s = SqliteStateStore(tmp_path / "state.db")
    yield s
    s.close()


class TestSqliteStateStoreCheckpoints:
    def test_save_and_load(self, store):
        cp = CheckpointData(
            agent_id="a1",
            tenant_id="t1",
            state=b"hello world",
            metadata={"step": 1},
            sequence=1,
            machine_id="m1",
        )
        store.save_checkpoint(cp)
        loaded = store.load_checkpoint("a1")
        assert loaded is not None
        assert loaded.agent_id == "a1"
        assert loaded.tenant_id == "t1"
        assert loaded.state == b"hello world"
        assert loaded.metadata == {"step": 1}
        assert loaded.sequence == 1
        assert loaded.machine_id == "m1"

    def test_load_nonexistent(self, store):
        assert store.load_checkpoint("nonexistent") is None

    def test_load_returns_latest(self, store):
        store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=b"v1", sequence=1, id="cp1"))
        store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=b"v2", sequence=2, id="cp2"))
        store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=b"v3", sequence=3, id="cp3"))
        loaded = store.load_checkpoint("a1")
        assert loaded is not None
        assert loaded.state == b"v3"
        assert loaded.sequence == 3

    def test_list_checkpoints(self, store):
        for i in range(5):
            store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=f"s{i}".encode(), sequence=i))
        cps = store.list_checkpoints("a1")
        assert len(cps) == 5
        # Should be ordered by sequence descending
        seqs = [cp.sequence for cp in cps]
        assert seqs == sorted(seqs, reverse=True)

    def test_list_checkpoints_empty(self, store):
        assert store.list_checkpoints("nonexistent") == []

    def test_delete_all_checkpoints(self, store):
        for i in range(3):
            store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=b"x", sequence=i))
        deleted = store.delete_checkpoints("a1")
        assert deleted == 3
        assert store.load_checkpoint("a1") is None

    def test_delete_keep_latest(self, store):
        for i in range(5):
            store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=f"s{i}".encode(), sequence=i))
        deleted = store.delete_checkpoints("a1", keep_latest=2)
        assert deleted == 3
        remaining = store.list_checkpoints("a1")
        assert len(remaining) == 2
        assert remaining[0].sequence == 4
        assert remaining[1].sequence == 3

    def test_delete_nonexistent_agent(self, store):
        deleted = store.delete_checkpoints("nonexistent")
        assert deleted == 0

    def test_binary_state_data(self, store):
        # Test with various binary data
        binary_data = bytes(range(256))
        store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=binary_data, sequence=1))
        loaded = store.load_checkpoint("a1")
        assert loaded is not None
        assert loaded.state == binary_data

    def test_agents_isolated(self, store):
        store.save_checkpoint(CheckpointData(agent_id="a1", tenant_id="t1", state=b"state-a1", sequence=1))
        store.save_checkpoint(CheckpointData(agent_id="a2", tenant_id="t1", state=b"state-a2", sequence=1))
        assert store.load_checkpoint("a1").state == b"state-a1"
        assert store.load_checkpoint("a2").state == b"state-a2"


class TestSqliteStateStoreMetadata:
    def test_save_and_get(self, store):
        store.save_metadata("a1", "t1", "status", "running")
        assert store.get_metadata("a1", "status") == "running"

    def test_get_nonexistent(self, store):
        assert store.get_metadata("a1", "missing") is None

    def test_update_metadata(self, store):
        store.save_metadata("a1", "t1", "count", 1)
        store.save_metadata("a1", "t1", "count", 42)
        assert store.get_metadata("a1", "count") == 42

    def test_complex_metadata_values(self, store):
        store.save_metadata("a1", "t1", "config", {"nested": {"key": [1, 2, 3]}})
        val = store.get_metadata("a1", "config")
        assert val == {"nested": {"key": [1, 2, 3]}}

    def test_query_metadata_by_tenant(self, store):
        store.save_metadata("a1", "t1", "status", "running")
        store.save_metadata("a2", "t1", "status", "stopped")
        store.save_metadata("a3", "t2", "status", "running")

        results = store.query_metadata("t1")
        assert len(results) == 2
        agent_ids = {r["agent_id"] for r in results}
        assert agent_ids == {"a1", "a2"}

    def test_query_metadata_with_filter(self, store):
        store.save_metadata("a1", "t1", "status", "running")
        store.save_metadata("a2", "t1", "status", "stopped")

        results = store.query_metadata("t1", filters={"key": "status"})
        assert len(results) == 2

        results = store.query_metadata("t1", filters={"agent_id": "a1"})
        assert len(results) == 1
        assert results[0]["agent_id"] == "a1"

    def test_query_metadata_empty_tenant(self, store):
        results = store.query_metadata("nonexistent")
        assert results == []
