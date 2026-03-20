"""Tests for langley.config."""

import pytest

from langley.config import load_config


class TestLoadConfigDefaults:
    def test_no_file_returns_defaults(self, tmp_path, monkeypatch):
        """When no config file exists, built-in defaults are used."""
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert cfg.get("server", "host") == "127.0.0.1"
        assert cfg.getint("server", "port") == 8000
        assert cfg.get("server", "data_dir") == ".langley"
        assert cfg.get("auth", "provider") == "none"

    def test_explicit_path_loads(self, tmp_path):
        p = tmp_path / "custom.cfg"
        p.write_text("[server]\nhost = 0.0.0.0\nport = 9999\n[auth]\nprovider = pam\n")
        cfg = load_config(p)
        assert cfg.get("server", "host") == "0.0.0.0"
        assert cfg.getint("server", "port") == 9999
        assert cfg.get("auth", "provider") == "pam"

    def test_explicit_path_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(tmp_path / "nonexistent.cfg")

    def test_partial_config_inherits_defaults(self, tmp_path):
        p = tmp_path / "partial.cfg"
        p.write_text("[server]\nport = 3000\n")
        cfg = load_config(p)
        assert cfg.getint("server", "port") == 3000
        # host should come from defaults
        assert cfg.get("server", "host") == "127.0.0.1"
        # auth section should come from defaults
        assert cfg.get("auth", "provider") == "none"


class TestLoadConfigSearchPaths:
    def test_cwd_config_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "langley.cfg").write_text("[server]\nport = 4444\n")
        cfg = load_config()
        assert cfg.getint("server", "port") == 4444

    def test_home_config_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        # Patch Path.home() to return tmp_path
        import langley.config as config_mod

        monkeypatch.setattr(config_mod.Path, "home", classmethod(lambda cls: tmp_path))
        (tmp_path / ".langley.cfg").write_text("[server]\nport = 5555\n")
        cfg = load_config()
        assert cfg.getint("server", "port") == 5555

    def test_cwd_takes_precedence_over_home(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import langley.config as config_mod

        monkeypatch.setattr(config_mod.Path, "home", classmethod(lambda cls: tmp_path))
        (tmp_path / "langley.cfg").write_text("[server]\nport = 1111\n")
        (tmp_path / ".langley.cfg").write_text("[server]\nport = 2222\n")
        cfg = load_config()
        assert cfg.getint("server", "port") == 1111
