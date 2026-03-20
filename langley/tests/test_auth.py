"""Tests for langley.auth (all providers)."""

import pytest

from langley.auth import LocalAuthProvider, NoAuthProvider, PamAuthProvider, create_auth_provider


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


class TestNoAuthProvider:
    def test_authenticate_always_succeeds(self):
        provider = NoAuthProvider()
        ident = provider.authenticate("t1", "anyone", "anything")
        assert ident is not None
        assert ident.username == "anyone"
        assert ident.roles == ["admin"]

    def test_authorize_always_true(self):
        provider = NoAuthProvider()
        ident = provider.authenticate("t1", "user", "pass")
        assert provider.authorize(ident, "admin") is True
        assert provider.authorize(ident, "view") is True

    def test_create_user_returns_identity(self):
        provider = NoAuthProvider()
        ident = provider.create_user("t1", "alice", "pass", roles=["viewer"])
        assert ident.username == "alice"
        assert ident.roles == ["viewer"]

    def test_list_users_empty(self):
        provider = NoAuthProvider()
        assert provider.list_users("t1") == []

    def test_delete_returns_false(self):
        provider = NoAuthProvider()
        assert provider.delete_user("t1", "alice") is False

    def test_close_is_noop(self):
        provider = NoAuthProvider()
        provider.close()  # should not raise


class TestPamAuthProvider:
    def test_pam_auto_provisions_user(self, tmp_path):
        """When OS auth succeeds, user is auto-provisioned in local store."""
        from unittest.mock import patch

        provider = PamAuthProvider(tmp_path / "pam.db")
        with patch("langley.auth.PamAuthProvider._os_authenticate", return_value=True):
            ident = provider.authenticate("t1", "testuser", "testpass")
        assert ident is not None
        assert ident.username == "testuser"
        assert ident.roles == ["viewer"]
        # Second auth should find existing user
        with patch("langley.auth.PamAuthProvider._os_authenticate", return_value=True):
            ident2 = provider.authenticate("t1", "testuser", "testpass")
        assert ident2.user_id == ident.user_id
        provider.close()

    def test_pam_rejects_bad_credentials(self, tmp_path):
        from unittest.mock import patch

        provider = PamAuthProvider(tmp_path / "pam.db")
        with patch("langley.auth.PamAuthProvider._os_authenticate", return_value=False):
            ident = provider.authenticate("t1", "testuser", "bad")
        assert ident is None
        provider.close()


class TestCreateAuthProviderFactory:
    def test_none(self, tmp_path):
        p = create_auth_provider("none", tmp_path / "auth.db")
        assert isinstance(p, NoAuthProvider)

    def test_local(self, tmp_path):
        p = create_auth_provider("local", tmp_path / "auth.db")
        assert isinstance(p, LocalAuthProvider)
        p.close()

    def test_pam(self, tmp_path):
        p = create_auth_provider("pam", tmp_path / "auth.db")
        assert isinstance(p, PamAuthProvider)
        p.close()

    def test_unknown_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown auth provider"):
            create_auth_provider("ldap", tmp_path / "auth.db")

    def test_case_insensitive(self, tmp_path):
        p = create_auth_provider("  None  ", tmp_path / "auth.db")
        assert isinstance(p, NoAuthProvider)
