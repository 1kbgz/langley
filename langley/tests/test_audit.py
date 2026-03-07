"""Tests for langley.audit (SqliteAuditLog)."""

import pytest

from langley.audit import SqliteAuditLog
from langley.models import AuditEntry


@pytest.fixture()
def audit(tmp_path):
    a = SqliteAuditLog(tmp_path / "audit.db")
    yield a
    a.close()


class TestSqliteAuditLogAppend:
    def test_append_and_query(self, audit):
        entry = AuditEntry(
            tenant_id="t1",
            agent_id="a1",
            event_type="agent.started",
            payload={"profile": "coder"},
        )
        audit.append(entry)
        results = audit.query("t1")
        assert len(results) == 1
        assert results[0].agent_id == "a1"
        assert results[0].event_type == "agent.started"
        assert results[0].payload == {"profile": "coder"}

    def test_append_multiple(self, audit):
        for i in range(10):
            audit.append(
                AuditEntry(
                    tenant_id="t1",
                    agent_id=f"a{i}",
                    event_type="test.event",
                    payload={"i": i},
                )
            )
        results = audit.query("t1")
        assert len(results) == 10


class TestSqliteAuditLogQuery:
    def _populate(self, audit):
        entries = [
            AuditEntry(tenant_id="t1", agent_id="a1", event_type="agent.started", timestamp=100.0),
            AuditEntry(tenant_id="t1", agent_id="a1", event_type="agent.message", timestamp=200.0),
            AuditEntry(tenant_id="t1", agent_id="a2", event_type="agent.started", timestamp=300.0),
            AuditEntry(tenant_id="t1", agent_id="a1", event_type="agent.stopped", timestamp=400.0),
            AuditEntry(tenant_id="t2", agent_id="a3", event_type="agent.started", timestamp=500.0),
        ]
        for e in entries:
            audit.append(e)

    def test_query_by_tenant(self, audit):
        self._populate(audit)
        results = audit.query("t1")
        assert len(results) == 4
        assert all(r.tenant_id == "t1" for r in results)

    def test_query_by_agent(self, audit):
        self._populate(audit)
        results = audit.query("t1", agent_id="a1")
        assert len(results) == 3
        assert all(r.agent_id == "a1" for r in results)

    def test_query_by_event_type(self, audit):
        self._populate(audit)
        results = audit.query("t1", event_type="agent.started")
        assert len(results) == 2

    def test_query_by_time_range(self, audit):
        self._populate(audit)
        results = audit.query("t1", since=150.0, until=350.0)
        assert len(results) == 2

    def test_query_since_only(self, audit):
        self._populate(audit)
        results = audit.query("t1", since=300.0)
        assert len(results) == 2

    def test_query_until_only(self, audit):
        self._populate(audit)
        results = audit.query("t1", until=200.0)
        assert len(results) == 2

    def test_query_with_limit(self, audit):
        self._populate(audit)
        results = audit.query("t1", limit=2)
        assert len(results) == 2

    def test_query_with_offset(self, audit):
        self._populate(audit)
        all_results = audit.query("t1")
        offset_results = audit.query("t1", offset=2)
        assert len(offset_results) == len(all_results) - 2

    def test_query_ordered_by_timestamp_desc(self, audit):
        self._populate(audit)
        results = audit.query("t1")
        timestamps = [r.timestamp for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_query_empty_tenant(self, audit):
        results = audit.query("nonexistent")
        assert results == []

    def test_query_combined_filters(self, audit):
        self._populate(audit)
        results = audit.query("t1", agent_id="a1", event_type="agent.started")
        assert len(results) == 1


class TestSqliteAuditLogCount:
    def test_count_all(self, audit):
        for i in range(5):
            audit.append(AuditEntry(tenant_id="t1", agent_id="a1", event_type="test"))
        assert audit.count("t1") == 5

    def test_count_by_agent(self, audit):
        audit.append(AuditEntry(tenant_id="t1", agent_id="a1", event_type="test"))
        audit.append(AuditEntry(tenant_id="t1", agent_id="a2", event_type="test"))
        audit.append(AuditEntry(tenant_id="t1", agent_id="a1", event_type="test"))
        assert audit.count("t1", agent_id="a1") == 2
        assert audit.count("t1", agent_id="a2") == 1

    def test_count_by_type(self, audit):
        audit.append(AuditEntry(tenant_id="t1", agent_id="a1", event_type="start"))
        audit.append(AuditEntry(tenant_id="t1", agent_id="a1", event_type="stop"))
        audit.append(AuditEntry(tenant_id="t1", agent_id="a1", event_type="start"))
        assert audit.count("t1", event_type="start") == 2

    def test_count_empty(self, audit):
        assert audit.count("t1") == 0


class TestSqliteAuditLogRecent:
    def test_recent_returns_entries_across_tenants(self, audit):
        audit.append(AuditEntry(tenant_id="t1", agent_id="a1", event_type="start"))
        audit.append(AuditEntry(tenant_id="t2", agent_id="a2", event_type="stop"))
        results = audit.recent(limit=10)
        assert len(results) == 2
        # Most recent first
        assert results[0].tenant_id == "t2"
        assert results[1].tenant_id == "t1"

    def test_recent_respects_limit(self, audit):
        for i in range(5):
            audit.append(AuditEntry(tenant_id="t1", agent_id=f"a{i}", event_type="start"))
        results = audit.recent(limit=3)
        assert len(results) == 3

    def test_recent_empty(self, audit):
        assert audit.recent() == []
