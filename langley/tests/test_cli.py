"""Tests for langley.cli."""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from langley.cli import main, _find_js_dir, _api_request


class TestMain:
    def test_no_args_defaults_to_up(self, capsys, tmp_path):
        """Bare `langley` should default to `langley up`."""
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_start_api_server", return_value=MagicMock()) as mock_start:
            with patch.object(cli_mod, "signal") as mock_signal:
                mock_signal.pause.side_effect = KeyboardInterrupt
                ret = main([])
                assert ret == 0
                mock_start.assert_called_once()

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


class TestUpCommand:
    def test_up_starts_server(self, capsys, tmp_path):
        """langley up starts only the API server."""
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_start_api_server", return_value=MagicMock()) as mock_start:
            with patch.object(cli_mod, "signal") as mock_signal:
                mock_signal.pause.side_effect = KeyboardInterrupt
                ret = main(["up", "--port", "18765", "--data-dir", str(tmp_path)])
                assert ret == 0
                mock_start.assert_called_once_with("127.0.0.1", 18765, data_dir=str(tmp_path))
        captured = capsys.readouterr()
        assert "http://127.0.0.1:18765" in captured.out


class TestDevCommand:
    def test_dev_api_only_starts_server(self, capsys, tmp_path):
        """Start API server and immediately shut it down."""
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_find_js_dir", return_value=Path("/fake/js")):
            with patch.object(cli_mod, "_start_api_server", return_value=MagicMock()) as mock_start:
                with patch.object(cli_mod, "signal") as mock_signal:
                    mock_signal.pause.side_effect = KeyboardInterrupt
                    ret = main(["dev", "--api-only", "--port", "18765", "--data-dir", str(tmp_path)])
                    assert ret == 0
                    mock_start.assert_called_once_with(
                        "127.0.0.1", 18765, data_dir=str(tmp_path), static_dir=Path("/fake/js/dist"),
                    )

    def test_dev_ui_only_no_js_dir(self, capsys):
        """When JS dir is not found, nothing starts."""
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_find_js_dir", return_value=None):
            ret = main(["dev", "--ui-only"])
            assert ret == 1


class TestHelpers:
    def test_find_js_dir(self):
        js_dir = _find_js_dir()
        # In the dev layout, js/ should exist
        assert js_dir is not None
        assert (js_dir / "package.json").is_file()


class TestApiRequest:
    """Test the _api_request helper used by agent subcommands."""

    def test_api_request_get(self):
        """GET request returns parsed JSON."""
        import langley.cli as cli_mod

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{"agent_id": "a1"}]).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(cli_mod, "urlopen", return_value=mock_resp):
            result = _api_request("http://localhost:8000", "GET", "/api/agents")
        assert result == [{"agent_id": "a1"}]

    def test_api_request_connection_error(self):
        """Connection error prints message and exits."""
        import langley.cli as cli_mod
        from urllib.error import URLError

        with patch.object(cli_mod, "urlopen", side_effect=URLError("refused")):
            with pytest.raises(SystemExit) as exc_info:
                _api_request("http://localhost:9999", "GET", "/api/agents")
            assert exc_info.value.code == 1


class TestAgentCommands:
    """Test agent subcommands (list, launch, stop, kill)."""

    def _mock_api(self, cli_mod, response_data):
        return patch.object(cli_mod, "_api_request", return_value=response_data)

    def test_agent_list_empty(self, capsys):
        import langley.cli as cli_mod

        with self._mock_api(cli_mod, []):
            ret = main(["agent", "list"])
        assert ret == 0
        assert "No agents" in capsys.readouterr().out

    def test_agent_list_with_agents(self, capsys):
        import langley.cli as cli_mod

        agents = [
            {"agent_id": "abc-123", "status": "running", "profile_name": "test-prof", "pid": 12345, "uptime_seconds": 60},
        ]
        with self._mock_api(cli_mod, agents):
            ret = main(["agent", "list"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "abc-123" in out
        assert "running" in out
        assert "test-prof" in out

    def test_agent_launch_with_profile_id(self, capsys):
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_api_request", return_value={"agent_id": "new-1", "status": "starting"}) as mock_req:
            ret = main(["agent", "launch", "--profile-id", "prof-1"])
        assert ret == 0
        mock_req.assert_called_once_with("http://127.0.0.1:8000", "POST", "/api/agents", {"profile_id": "prof-1"})
        assert "new-1" in capsys.readouterr().out

    def test_agent_launch_inline(self, capsys):
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_api_request", return_value={"agent_id": "new-2", "status": "starting"}) as mock_req:
            ret = main(["agent", "launch", "--name", "my-agent", "--tenant", "t1", "echo", "hello"])
        assert ret == 0
        call_args = mock_req.call_args
        assert call_args[0][2] == "/api/agents"
        body = call_args[0][3]
        assert body["profile"]["name"] == "my-agent"
        assert body["profile"]["tenant_id"] == "t1"
        assert body["profile"]["command"] == ["echo", "hello"]

    def test_agent_stop(self, capsys):
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_api_request", return_value={}) as mock_req:
            ret = main(["agent", "stop", "agent-xyz"])
        assert ret == 0
        mock_req.assert_called_once_with("http://127.0.0.1:8000", "POST", "/api/agents/agent-xyz/stop")
        assert "agent-xyz" in capsys.readouterr().out

    def test_agent_kill(self, capsys):
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_api_request", return_value={}) as mock_req:
            ret = main(["agent", "kill", "agent-xyz"])
        assert ret == 0
        mock_req.assert_called_once_with("http://127.0.0.1:8000", "POST", "/api/agents/agent-xyz/kill")
        assert "agent-xyz" in capsys.readouterr().out

    def test_agent_custom_url(self, capsys):
        import langley.cli as cli_mod

        with patch.object(cli_mod, "_api_request", return_value=[]) as mock_req:
            ret = main(["agent", "--url", "http://remote:9000", "list"])
        assert ret == 0
        mock_req.assert_called_once_with("http://remote:9000", "GET", "/api/agents")
