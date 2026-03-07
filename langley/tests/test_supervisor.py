"""Tests for langley.supervisor (AgentProcessManager)."""

import sys
import time
import threading

import pytest

from langley.audit import SqliteAuditLog
from langley.models import AgentProfile
from langley.store import SqliteStateStore
from langley.supervisor import (
    AgentInfo,
    AgentProcessManager,
    AgentStatus,
    RestartPolicy,
)
from langley.transport import FileMessageTransport


@pytest.fixture()
def deps(tmp_path):
    transport = FileMessageTransport(tmp_path / "transport", poll_interval=0.05)
    store = SqliteStateStore(":memory:")
    audit = SqliteAuditLog(":memory:")
    yield transport, store, audit
    transport.close()


@pytest.fixture()
def manager(deps):
    transport, store, audit = deps
    mgr = AgentProcessManager(
        transport=transport,
        state_store=store,
        audit_log=audit,
        heartbeat_interval=0.1,
        heartbeat_timeout=0.5,
        graceful_shutdown_timeout=2.0,
    )
    yield mgr
    mgr.close()


def _sleep_profile(tenant_id="t1", seconds=10):
    """Profile that runs a sleep command."""
    return AgentProfile(
        name="sleeper",
        tenant_id=tenant_id,
        command=[sys.executable, "-c", f"import time; time.sleep({seconds})"],
    )


def _exit_profile(tenant_id="t1", code=0):
    """Profile that exits immediately with a given code."""
    return AgentProfile(
        name="exiter",
        tenant_id=tenant_id,
        command=[sys.executable, "-c", f"raise SystemExit({code})"],
    )


def _no_command_profile():
    return AgentProfile(name="empty", tenant_id="t1", command=[])


class TestAgentInfo:
    def test_to_dict(self):
        profile = AgentProfile(name="test", tenant_id="t1")
        info = AgentInfo(agent_id="a1", tenant_id="t1", profile=profile)
        d = info.to_dict()
        assert d["agent_id"] == "a1"
        assert d["status"] == "pending"
        assert d["uptime_seconds"] == 0.0

    def test_uptime_while_running(self):
        profile = AgentProfile(name="test", tenant_id="t1")
        info = AgentInfo(agent_id="a1", tenant_id="t1", profile=profile, started_at=time.time() - 5)
        assert info.uptime_seconds >= 4.5

    def test_uptime_when_stopped(self):
        profile = AgentProfile(name="test", tenant_id="t1")
        info = AgentInfo(
            agent_id="a1", tenant_id="t1", profile=profile,
            started_at=100.0, stopped_at=110.0,
        )
        assert info.uptime_seconds == pytest.approx(10.0)


class TestAgentStatusEnum:
    def test_values(self):
        assert AgentStatus.PENDING.value == "pending"
        assert AgentStatus.RUNNING.value == "running"
        assert AgentStatus.STOPPED.value == "stopped"
        assert AgentStatus.ERRORED.value == "errored"
        assert AgentStatus.DEAD.value == "dead"


class TestRestartPolicyEnum:
    def test_values(self):
        assert RestartPolicy.ALWAYS.value == "always"
        assert RestartPolicy.ON_FAILURE.value == "on-failure"
        assert RestartPolicy.NEVER.value == "never"


class TestLaunch:
    def test_launch_creates_running_agent(self, manager):
        info = manager.launch(_sleep_profile())
        assert info.status == AgentStatus.RUNNING
        assert info.pid is not None
        assert info.agent_id is not None
        assert info.tenant_id == "t1"

    def test_launch_with_explicit_id(self, manager):
        info = manager.launch(_sleep_profile(), agent_id="my-agent")
        assert info.agent_id == "my-agent"

    def test_launch_duplicate_id_raises(self, manager):
        manager.launch(_sleep_profile(), agent_id="dup")
        with pytest.raises(ValueError, match="already exists"):
            manager.launch(_sleep_profile(), agent_id="dup")

    def test_launch_empty_command_raises(self, manager):
        with pytest.raises(ValueError, match="non-empty command or an llm_provider"):
            manager.launch(_no_command_profile())

    def test_launch_llm_provider_no_command_generates_runner(self, manager):
        """When llm_provider is set and command is empty, supervisor auto-generates the agent_runner command."""
        profile = AgentProfile(
            name="llm-agent",
            tenant_id="t1",
            command=[],
            llm_provider="github-copilot",
            model="claude-sonnet-4",
            system_prompt="Do stuff",
        )
        info = manager.launch(profile)
        assert info.status == AgentStatus.RUNNING or info.status == AgentStatus.ERRORED
        # The profile command should have been filled in with the agent_runner
        assert "agent_runner" in " ".join(info.profile.command)

    def test_launch_after_close_raises(self, manager):
        manager.close()
        with pytest.raises(RuntimeError, match="closed"):
            manager.launch(_sleep_profile())

    def test_launch_bad_command_raises(self, manager):
        profile = AgentProfile(name="bad", tenant_id="t1", command=["/nonexistent/binary"])
        with pytest.raises((OSError, FileNotFoundError)):
            manager.launch(profile)

    def test_launch_sets_environment(self, manager):
        info = manager.launch(_sleep_profile(), environment={"CUSTOM_VAR": "hello"})
        assert info.status == AgentStatus.RUNNING


class TestStop:
    def test_stop_running_agent(self, manager):
        info = manager.launch(_sleep_profile())
        result = manager.stop(info.agent_id)
        assert result is True
        assert info.status == AgentStatus.STOPPING

    def test_stop_nonexistent_returns_false(self, manager):
        assert manager.stop("no-such-agent") is False

    def test_stop_force(self, manager):
        info = manager.launch(_sleep_profile())
        result = manager.stop(info.agent_id, force=True)
        assert result is True

    def test_stop_already_stopped(self, manager):
        info = manager.launch(_exit_profile(code=0))
        time.sleep(0.3)
        manager.poll()
        assert manager.stop(info.agent_id) is False


class TestRestart:
    def test_restart_running_agent(self, manager):
        info = manager.launch(_sleep_profile())
        old_pid = info.pid
        restarted = manager.restart(info.agent_id)
        assert restarted is not None
        assert restarted.restart_count == 1
        assert restarted.pid != old_pid

    def test_restart_nonexistent(self, manager):
        assert manager.restart("no-such") is None


class TestListing:
    def test_get_agent(self, manager):
        info = manager.launch(_sleep_profile(), agent_id="a1")
        retrieved = manager.get_agent("a1")
        assert retrieved is not None
        assert retrieved.agent_id == "a1"

    def test_get_nonexistent(self, manager):
        assert manager.get_agent("nope") is None

    def test_list_agents(self, manager):
        manager.launch(_sleep_profile(tenant_id="t1"), agent_id="a1")
        manager.launch(_sleep_profile(tenant_id="t2"), agent_id="a2")
        all_agents = manager.list_agents()
        assert len(all_agents) == 2

    def test_list_agents_by_tenant(self, manager):
        manager.launch(_sleep_profile(tenant_id="t1"), agent_id="a1")
        manager.launch(_sleep_profile(tenant_id="t2"), agent_id="a2")
        t1_agents = manager.list_agents(tenant_id="t1")
        assert len(t1_agents) == 1
        assert t1_agents[0].agent_id == "a1"


class TestRemove:
    def test_remove_stopped_agent(self, manager):
        info = manager.launch(_exit_profile(code=0))
        time.sleep(0.3)
        manager.poll()
        assert info.status == AgentStatus.STOPPED
        assert manager.remove_agent(info.agent_id) is True
        assert manager.get_agent(info.agent_id) is None

    def test_remove_running_returns_false(self, manager):
        info = manager.launch(_sleep_profile())
        assert manager.remove_agent(info.agent_id) is False

    def test_remove_nonexistent(self, manager):
        assert manager.remove_agent("nope") is False


class TestHeartbeat:
    def test_record_heartbeat(self, manager):
        info = manager.launch(_sleep_profile())
        assert manager.record_heartbeat(info.agent_id) is True

    def test_record_heartbeat_nonexistent(self, manager):
        assert manager.record_heartbeat("nope") is False


class TestPoll:
    def test_poll_detects_exit(self, manager):
        info = manager.launch(_exit_profile(code=0))
        time.sleep(0.3)
        changed = manager.poll()
        assert len(changed) >= 1
        assert info.status == AgentStatus.STOPPED
        assert info.exit_code == 0

    def test_poll_detects_error_exit(self, manager):
        info = manager.launch(_exit_profile(code=1))
        time.sleep(0.3)
        changed = manager.poll()
        assert len(changed) >= 1
        assert info.status == AgentStatus.ERRORED
        assert info.exit_code == 1

    def test_poll_restart_on_failure(self, manager):
        info = manager.launch(
            _exit_profile(code=1),
            restart_policy=RestartPolicy.ON_FAILURE,
        )
        time.sleep(0.3)
        changed = manager.poll()
        # Should have been restarted
        assert info.restart_count >= 1
        assert info.status == AgentStatus.RUNNING

    def test_poll_restart_always(self, manager):
        info = manager.launch(
            _exit_profile(code=0),
            restart_policy=RestartPolicy.ALWAYS,
        )
        time.sleep(0.3)
        manager.poll()
        assert info.restart_count >= 1
        assert info.status == AgentStatus.RUNNING

    def test_poll_no_restart_on_clean_exit_on_failure_policy(self, manager):
        info = manager.launch(
            _exit_profile(code=0),
            restart_policy=RestartPolicy.ON_FAILURE,
        )
        time.sleep(0.3)
        manager.poll()
        assert info.restart_count == 0
        assert info.status == AgentStatus.STOPPED

    def test_poll_heartbeat_timeout(self, manager):
        info = manager.launch(_sleep_profile())
        # Fake an old heartbeat
        info.last_heartbeat = time.time() - 100
        changed = manager.poll()
        assert info.status == AgentStatus.DEAD


class TestMonitor:
    def test_start_stop_monitor(self, manager):
        manager.start_monitor()
        assert manager._monitor_thread is not None
        time.sleep(0.15)
        manager.stop_monitor()
        assert manager._monitor_thread is None

    def test_start_monitor_idempotent(self, manager):
        manager.start_monitor()
        t = manager._monitor_thread
        manager.start_monitor()
        assert manager._monitor_thread is t
        manager.stop_monitor()


class TestAgentsProperty:
    def test_agents_returns_snapshot(self, manager):
        manager.launch(_sleep_profile(), agent_id="a1")
        agents = manager.agents
        assert "a1" in agents
        assert isinstance(agents["a1"], AgentInfo)


class TestAudit:
    def test_launch_creates_audit_entry(self, deps, manager):
        _, _, audit = deps
        manager.launch(_sleep_profile())
        entries = audit.query(tenant_id="t1", event_type="agent.started")
        assert len(entries) >= 1
