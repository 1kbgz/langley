"""Tests for langley.profile (ProfileStore, file loading, merge)."""

import json

import pytest

from langley.models import AgentProfile
from langley.profile import (
    SqliteProfileStore,
    load_profile_from_file,
    load_profile_from_string,
    merge_profiles,
)


@pytest.fixture()
def store():
    s = SqliteProfileStore(":memory:")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


class TestLoadFromFile:
    def test_load_json(self, tmp_path):
        p = tmp_path / "agent.json"
        p.write_text(json.dumps({"name": "bot", "tenant_id": "t1", "model": "gpt-4"}))
        profile = load_profile_from_file(str(p))
        assert profile.name == "bot"
        assert profile.tenant_id == "t1"
        assert profile.model == "gpt-4"

    def test_load_unsupported_ext(self, tmp_path):
        p = tmp_path / "agent.xml"
        p.write_text("<agent/>")
        with pytest.raises(ValueError, match="Unsupported"):
            load_profile_from_file(str(p))


class TestLoadFromString:
    def test_load_json_string(self):
        profile = load_profile_from_string(
            json.dumps({"name": "bot", "tenant_id": "t1"}),
            fmt="json",
        )
        assert profile.name == "bot"

    def test_unsupported_format(self):
        with pytest.raises(ValueError, match="Unsupported"):
            load_profile_from_string("{}", fmt="xml")


# ---------------------------------------------------------------------------
# Merge / overlay
# ---------------------------------------------------------------------------


class TestMergeProfiles:
    def test_scalar_override(self):
        base = AgentProfile(name="base", tenant_id="t1", model="gpt-3.5")
        merged = merge_profiles(base, {"model": "gpt-4"})
        assert merged.model == "gpt-4"
        assert merged.name == "base"  # unchanged

    def test_dict_merge(self):
        base = AgentProfile(
            name="base",
            tenant_id="t1",
            environment={"A": "1", "B": "2"},
        )
        merged = merge_profiles(base, {"environment": {"B": "3", "C": "4"}})
        assert merged.environment == {"A": "1", "B": "3", "C": "4"}

    def test_list_replace(self):
        base = AgentProfile(
            name="base",
            tenant_id="t1",
            tools=["tool-a", "tool-b"],
        )
        merged = merge_profiles(base, {"tools": ["tool-c"]})
        assert merged.tools == ["tool-c"]

    def test_unknown_keys_ignored(self):
        base = AgentProfile(name="base", tenant_id="t1")
        merged = merge_profiles(base, {"nonexistent": "value"})
        assert merged.name == "base"

    def test_base_not_mutated(self):
        base = AgentProfile(
            name="base",
            tenant_id="t1",
            environment={"A": "1"},
        )
        merge_profiles(base, {"environment": {"B": "2"}})
        assert base.environment == {"A": "1"}


# ---------------------------------------------------------------------------
# SqliteProfileStore
# ---------------------------------------------------------------------------


class TestSqliteProfileStoreSave:
    def test_save_creates_version_1(self, store):
        profile = AgentProfile(name="bot", tenant_id="t1")
        saved = store.save(profile)
        assert saved.version == 1

    def test_save_increments_version(self, store):
        profile = AgentProfile(name="bot", tenant_id="t1")
        v1 = store.save(profile)
        v2 = store.save(profile)
        assert v1.version == 1
        assert v2.version == 2


class TestSqliteProfileStoreGet:
    def test_get_latest(self, store):
        profile = AgentProfile(name="bot", tenant_id="t1")
        store.save(profile)
        profile.model = "gpt-4"
        store.save(profile)
        latest = store.get(profile.id)
        assert latest is not None
        assert latest.version == 2
        assert latest.model == "gpt-4"

    def test_get_specific_version(self, store):
        profile = AgentProfile(name="bot", tenant_id="t1")
        store.save(profile)
        profile.model = "gpt-4"
        store.save(profile)
        v1 = store.get(profile.id, version=1)
        assert v1 is not None
        assert v1.version == 1

    def test_get_nonexistent(self, store):
        assert store.get("no-such-id") is None

    def test_get_nonexistent_version(self, store):
        profile = AgentProfile(name="bot", tenant_id="t1")
        store.save(profile)
        assert store.get(profile.id, version=99) is None


class TestSqliteProfileStoreList:
    def test_list_profiles(self, store):
        p1 = AgentProfile(name="bot1", tenant_id="t1")
        p2 = AgentProfile(name="bot2", tenant_id="t1")
        store.save(p1)
        store.save(p2)
        profiles = store.list_profiles()
        assert len(profiles) == 2

    def test_list_profiles_by_tenant(self, store):
        p1 = AgentProfile(name="bot1", tenant_id="t1")
        p2 = AgentProfile(name="bot2", tenant_id="t2")
        store.save(p1)
        store.save(p2)
        t1_profiles = store.list_profiles(tenant_id="t1")
        assert len(t1_profiles) == 1
        assert t1_profiles[0].name == "bot1"

    def test_list_returns_latest_version(self, store):
        p = AgentProfile(name="bot", tenant_id="t1")
        store.save(p)
        p.model = "gpt-4"
        store.save(p)
        profiles = store.list_profiles()
        assert len(profiles) == 1
        assert profiles[0].version == 2


class TestSqliteProfileStoreVersions:
    def test_list_versions(self, store):
        p = AgentProfile(name="bot", tenant_id="t1")
        store.save(p)
        p.model = "v2"
        store.save(p)
        p.model = "v3"
        store.save(p)
        versions = store.list_versions(p.id)
        assert len(versions) == 3
        assert versions[0].version == 1
        assert versions[2].version == 3

    def test_list_versions_empty(self, store):
        assert store.list_versions("no-such") == []


class TestSqliteProfileStoreDelete:
    def test_delete(self, store):
        p = AgentProfile(name="bot", tenant_id="t1")
        store.save(p)
        assert store.delete(p.id) is True
        assert store.get(p.id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete("no-such-id") is False

    def test_delete_removes_all_versions(self, store):
        p = AgentProfile(name="bot", tenant_id="t1")
        store.save(p)
        store.save(p)
        store.save(p)
        store.delete(p.id)
        assert store.list_versions(p.id) == []
