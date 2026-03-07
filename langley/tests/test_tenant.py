"""Tests for langley.tenant (LocalTenantManager)."""

import pytest

from langley.tenant import LocalTenantManager


@pytest.fixture()
def mgr(tmp_path):
    m = LocalTenantManager(tmp_path / "tenants.db")
    yield m
    m.close()


class TestLocalTenantManagerCreate:
    def test_create_tenant(self, mgr):
        t = mgr.create_tenant("acme")
        assert t.name == "acme"
        assert t.active is True
        assert t.id
        assert t.created_at > 0

    def test_create_with_metadata(self, mgr):
        t = mgr.create_tenant("acme", metadata={"plan": "enterprise"})
        assert t.metadata == {"plan": "enterprise"}

    def test_create_with_quotas(self, mgr):
        t = mgr.create_tenant("acme", resource_quotas={"max_agents": 50})
        assert t.resource_quotas == {"max_agents": 50}

    def test_create_duplicate_raises(self, mgr):
        mgr.create_tenant("acme")
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_tenant("acme")


class TestLocalTenantManagerGet:
    def test_get_by_id(self, mgr):
        created = mgr.create_tenant("acme")
        found = mgr.get_tenant(created.id)
        assert found is not None
        assert found.name == "acme"
        assert found.id == created.id

    def test_get_nonexistent(self, mgr):
        assert mgr.get_tenant("nonexistent") is None

    def test_get_by_name(self, mgr):
        mgr.create_tenant("acme")
        found = mgr.get_tenant_by_name("acme")
        assert found is not None
        assert found.name == "acme"

    def test_get_by_name_nonexistent(self, mgr):
        assert mgr.get_tenant_by_name("nonexistent") is None


class TestLocalTenantManagerList:
    def test_list_active_only(self, mgr):
        mgr.create_tenant("acme")
        t2 = mgr.create_tenant("beta")
        mgr.suspend_tenant(t2.id)

        active = mgr.list_tenants(active_only=True)
        assert len(active) == 1
        assert active[0].name == "acme"

    def test_list_all(self, mgr):
        mgr.create_tenant("acme")
        t2 = mgr.create_tenant("beta")
        mgr.suspend_tenant(t2.id)

        all_tenants = mgr.list_tenants(active_only=False)
        assert len(all_tenants) == 2

    def test_list_empty(self, mgr):
        assert mgr.list_tenants() == []


class TestLocalTenantManagerUpdate:
    def test_update_name(self, mgr):
        t = mgr.create_tenant("old-name")
        updated = mgr.update_tenant(t.id, name="new-name")
        assert updated is not None
        assert updated.name == "new-name"

    def test_update_metadata(self, mgr):
        t = mgr.create_tenant("acme")
        updated = mgr.update_tenant(t.id, metadata={"plan": "pro"})
        assert updated is not None
        assert updated.metadata == {"plan": "pro"}

    def test_update_quotas(self, mgr):
        t = mgr.create_tenant("acme")
        updated = mgr.update_tenant(t.id, resource_quotas={"max_agents": 100})
        assert updated is not None
        assert updated.resource_quotas == {"max_agents": 100}

    def test_update_nonexistent(self, mgr):
        assert mgr.update_tenant("nonexistent", name="x") is None

    def test_update_duplicate_name_raises(self, mgr):
        mgr.create_tenant("acme")
        t2 = mgr.create_tenant("beta")
        with pytest.raises(ValueError, match="already exists"):
            mgr.update_tenant(t2.id, name="acme")

    def test_update_no_changes(self, mgr):
        t = mgr.create_tenant("acme", metadata={"k": "v"})
        updated = mgr.update_tenant(t.id)
        assert updated is not None
        assert updated.name == "acme"
        assert updated.metadata == {"k": "v"}


class TestLocalTenantManagerSuspendActivate:
    def test_suspend(self, mgr):
        t = mgr.create_tenant("acme")
        assert mgr.suspend_tenant(t.id) is True
        found = mgr.get_tenant(t.id)
        assert found is not None
        assert found.active is False

    def test_suspend_nonexistent(self, mgr):
        assert mgr.suspend_tenant("nonexistent") is False

    def test_suspend_already_suspended(self, mgr):
        t = mgr.create_tenant("acme")
        mgr.suspend_tenant(t.id)
        assert mgr.suspend_tenant(t.id) is False  # already suspended

    def test_activate(self, mgr):
        t = mgr.create_tenant("acme")
        mgr.suspend_tenant(t.id)
        assert mgr.activate_tenant(t.id) is True
        found = mgr.get_tenant(t.id)
        assert found.active is True

    def test_activate_already_active(self, mgr):
        t = mgr.create_tenant("acme")
        assert mgr.activate_tenant(t.id) is False  # already active

    def test_activate_nonexistent(self, mgr):
        assert mgr.activate_tenant("nonexistent") is False


class TestLocalTenantManagerDelete:
    def test_delete(self, mgr):
        t = mgr.create_tenant("acme")
        assert mgr.delete_tenant(t.id) is True
        assert mgr.get_tenant(t.id) is None

    def test_delete_nonexistent(self, mgr):
        assert mgr.delete_tenant("nonexistent") is False

    def test_delete_removes_from_list(self, mgr):
        t = mgr.create_tenant("acme")
        mgr.delete_tenant(t.id)
        assert mgr.list_tenants(active_only=False) == []
