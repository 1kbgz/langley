"""Tests for langley.auth (LocalAuthProvider)."""

import pytest

from langley.auth import LocalAuthProvider


@pytest.fixture()
def auth(tmp_path):
    a = LocalAuthProvider(tmp_path / "auth.db")
    yield a
    a.close()


class TestLocalAuthProviderCreateUser:
    def test_create_user(self, auth):
        ident = auth.create_user("t1", "alice", "password123", roles=["admin"])
        assert ident.username == "alice"
        assert ident.tenant_id == "t1"
        assert ident.roles == ["admin"]
        assert ident.user_id  # auto-generated

    def test_create_user_default_roles(self, auth):
        ident = auth.create_user("t1", "bob", "pass")
        assert ident.roles == ["viewer"]

    def test_create_duplicate_raises(self, auth):
        auth.create_user("t1", "alice", "pass1")
        with pytest.raises(ValueError, match="already exists"):
            auth.create_user("t1", "alice", "pass2")

    def test_same_username_different_tenant(self, auth):
        i1 = auth.create_user("t1", "alice", "pass1")
        i2 = auth.create_user("t2", "alice", "pass2")
        assert i1.tenant_id == "t1"
        assert i2.tenant_id == "t2"
        assert i1.user_id != i2.user_id


class TestLocalAuthProviderAuthenticate:
    def test_authenticate_success(self, auth):
        auth.create_user("t1", "alice", "correctpassword", roles=["operator"])
        ident = auth.authenticate("t1", "alice", "correctpassword")
        assert ident is not None
        assert ident.username == "alice"
        assert ident.roles == ["operator"]

    def test_authenticate_wrong_password(self, auth):
        auth.create_user("t1", "alice", "correctpassword")
        assert auth.authenticate("t1", "alice", "wrongpassword") is None

    def test_authenticate_nonexistent_user(self, auth):
        assert auth.authenticate("t1", "ghost", "pass") is None

    def test_authenticate_wrong_tenant(self, auth):
        auth.create_user("t1", "alice", "pass")
        assert auth.authenticate("t2", "alice", "pass") is None

    def test_authenticate_deleted_user(self, auth):
        auth.create_user("t1", "alice", "pass")
        auth.delete_user("t1", "alice")
        assert auth.authenticate("t1", "alice", "pass") is None


class TestLocalAuthProviderAuthorize:
    def test_admin_can_do_everything(self, auth):
        ident = auth.create_user("t1", "admin", "pass", roles=["admin"])
        assert auth.authorize(ident, "admin") is True
        assert auth.authorize(ident, "operate") is True
        assert auth.authorize(ident, "view") is True

    def test_operator_can_operate_and_view(self, auth):
        ident = auth.create_user("t1", "op", "pass", roles=["operator"])
        assert auth.authorize(ident, "admin") is False
        assert auth.authorize(ident, "operate") is True
        assert auth.authorize(ident, "view") is True

    def test_viewer_can_only_view(self, auth):
        ident = auth.create_user("t1", "viewer", "pass", roles=["viewer"])
        assert auth.authorize(ident, "admin") is False
        assert auth.authorize(ident, "operate") is False
        assert auth.authorize(ident, "view") is True

    def test_unknown_role_denied(self, auth):
        ident = auth.create_user("t1", "custom", "pass", roles=["custom_role"])
        assert auth.authorize(ident, "view") is False

    def test_multiple_roles(self, auth):
        ident = auth.create_user("t1", "multi", "pass", roles=["viewer", "operator"])
        assert auth.authorize(ident, "operate") is True
        assert auth.authorize(ident, "view") is True
        assert auth.authorize(ident, "admin") is False


class TestLocalAuthProviderGetUser:
    def test_get_existing(self, auth):
        auth.create_user("t1", "alice", "pass", roles=["admin"])
        ident = auth.get_user("t1", "alice")
        assert ident is not None
        assert ident.username == "alice"

    def test_get_nonexistent(self, auth):
        assert auth.get_user("t1", "ghost") is None


class TestLocalAuthProviderListUsers:
    def test_list_users(self, auth):
        auth.create_user("t1", "alice", "pass1")
        auth.create_user("t1", "bob", "pass2")
        auth.create_user("t2", "charlie", "pass3")

        t1_users = auth.list_users("t1")
        assert len(t1_users) == 2
        names = {u.username for u in t1_users}
        assert names == {"alice", "bob"}

    def test_list_empty_tenant(self, auth):
        assert auth.list_users("empty") == []


class TestLocalAuthProviderDeleteUser:
    def test_delete_existing(self, auth):
        auth.create_user("t1", "alice", "pass")
        assert auth.delete_user("t1", "alice") is True
        assert auth.get_user("t1", "alice") is None

    def test_delete_nonexistent(self, auth):
        assert auth.delete_user("t1", "ghost") is False


class TestLocalAuthProviderUpdateRoles:
    def test_update_roles(self, auth):
        auth.create_user("t1", "alice", "pass", roles=["viewer"])
        updated = auth.update_roles("t1", "alice", ["admin", "operator"])
        assert updated is not None
        assert set(updated.roles) == {"admin", "operator"}

        # Verify authentication returns updated roles
        ident = auth.authenticate("t1", "alice", "pass")
        assert set(ident.roles) == {"admin", "operator"}

    def test_update_nonexistent(self, auth):
        assert auth.update_roles("t1", "ghost", ["admin"]) is None
