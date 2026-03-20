"""Agent process manager — launches, monitors, and controls agent subprocesses."""

import enum
import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any

from langley.audit import AuditLog
from langley.models import AgentProfile, AuditEntry, _new_id, _now
from langley.store import StateStore
from langley.transport import FileMessageTransport, MessageTransport

logger = logging.getLogger(__name__)


class AgentStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERRORED = "errored"
    DEAD = "dead"


class RestartPolicy(str, enum.Enum):
    ALWAYS = "always"
    ON_FAILURE = "on-failure"
    NEVER = "never"


@dataclass
class AgentInfo:
    """Runtime information about a managed agent."""

    agent_id: str
    tenant_id: str
    profile: AgentProfile
    status: AgentStatus = AgentStatus.PENDING
    pid: int | None = None
    exit_code: int | None = None
    restart_count: int = 0
    restart_policy: RestartPolicy = RestartPolicy.NEVER
    started_at: float | None = None
    stopped_at: float | None = None
    last_heartbeat: float | None = None
    error_message: str = ""

    @property
    def uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.stopped_at if self.stopped_at else _now()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "profile_id": self.profile.id,
            "profile_name": self.profile.name,
            "status": self.status.value,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "restart_count": self.restart_count,
            "restart_policy": self.restart_policy.value,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_heartbeat": self.last_heartbeat,
            "uptime_seconds": self.uptime_seconds,
            "error_message": self.error_message,
        }


class AgentProcessManager:
    """Manages agent subprocess lifecycles.

    Launches agents as subprocesses, monitors them via heartbeat,
    handles graceful/forceful shutdown, and applies restart policies.
    """

    def __init__(
        self,
        transport: MessageTransport,
        state_store: StateStore,
        audit_log: AuditLog,
        heartbeat_interval: float = 5.0,
        heartbeat_timeout: float = 15.0,
        graceful_shutdown_timeout: float = 10.0,
    ):
        self._transport = transport
        self._state_store = state_store
        self._audit_log = audit_log
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._graceful_shutdown_timeout = graceful_shutdown_timeout

        self._agents: dict[str, AgentInfo] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._closed = False

    @property
    def agents(self) -> dict[str, AgentInfo]:
        """Return a snapshot of all managed agents."""
        with self._lock:
            return dict(self._agents)

    def launch(
        self,
        profile: AgentProfile,
        agent_id: str | None = None,
        restart_policy: RestartPolicy = RestartPolicy.NEVER,
        environment: dict[str, str] | None = None,
    ) -> AgentInfo:
        """Launch an agent subprocess from a profile.

        Args:
            profile: Agent configuration.
            agent_id: Optional explicit ID. Auto-generated if not provided.
            restart_policy: Restart behavior on exit.
            environment: Additional environment variables.

        Returns:
            AgentInfo for the launched agent.

        Raises:
            ValueError: If profile has no command or agent_id already exists.
            RuntimeError: If the manager is closed.
        """
        if self._closed:
            raise RuntimeError("Process manager is closed")
        if not profile.command and not profile.llm_provider:
            raise ValueError("AgentProfile must have a non-empty command or an llm_provider")

        # Auto-generate command for provider-based agents
        if not profile.command and profile.llm_provider:
            profile = AgentProfile(
                **{
                    **profile.to_dict(),
                    "command": [sys.executable, "-m", "langley.agent_runner"],
                }
            )

        if agent_id is None:
            agent_id = _new_id()

        with self._lock:
            if agent_id in self._agents:
                raise ValueError(f"Agent '{agent_id}' already exists")

            info = AgentInfo(
                agent_id=agent_id,
                tenant_id=profile.tenant_id,
                profile=profile,
                restart_policy=restart_policy,
            )
            self._agents[agent_id] = info

        self._start_process(info, environment)
        return info

    def _build_env(self, info: AgentInfo, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build environment variables for the agent subprocess."""
        env = os.environ.copy()
        env["LANGLEY_AGENT_ID"] = info.agent_id
        env["LANGLEY_TENANT_ID"] = info.tenant_id
        env["LANGLEY_PROFILE_ID"] = info.profile.id
        env["LANGLEY_PROFILE_NAME"] = info.profile.name

        # Transport directory for file-based messaging
        if isinstance(self._transport, FileMessageTransport):
            env["LANGLEY_TRANSPORT_DIR"] = str(self._transport._base)

        if info.profile.llm_provider:
            env["LANGLEY_LLM_PROVIDER"] = info.profile.llm_provider
        if info.profile.model:
            env["LANGLEY_MODEL"] = info.profile.model
        if info.profile.system_prompt:
            env["LANGLEY_SYSTEM_PROMPT"] = info.profile.system_prompt

        # Profile-defined environment
        env.update(info.profile.environment)

        # Caller-provided overrides
        if extra:
            env.update(extra)

        return env

    def _start_process(self, info: AgentInfo, extra_env: dict[str, str] | None = None) -> None:
        """Start the actual subprocess for an agent."""
        env = self._build_env(info, extra_env)

        try:
            proc = subprocess.Popen(
                info.profile.command,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except (OSError, FileNotFoundError) as e:
            with self._lock:
                info.status = AgentStatus.ERRORED
                info.error_message = str(e)
            self._audit(info, "agent.launch_failed", {"error": str(e)})
            raise

        with self._lock:
            self._processes[info.agent_id] = proc
            info.pid = proc.pid
            info.status = AgentStatus.RUNNING
            info.started_at = _now()
            info.last_heartbeat = _now()
            info.error_message = ""

        self._audit(info, "agent.started", {"pid": proc.pid})

    def stop(self, agent_id: str, force: bool = False) -> bool:
        """Stop an agent gracefully (SIGTERM) or forcefully (SIGKILL).

        Returns True if the agent was found and stop was initiated.
        """
        with self._lock:
            info = self._agents.get(agent_id)
            proc = self._processes.get(agent_id)
            if info is None or proc is None:
                return False
            if info.status not in (AgentStatus.RUNNING, AgentStatus.PENDING):
                return False
            info.status = AgentStatus.STOPPING

        if force:
            self._kill_process_group(proc)
            self._audit(info, "agent.killed")
        else:
            self._terminate_process_group(proc)
            self._audit(info, "agent.stop_requested")

            # Start a watchdog thread for graceful shutdown timeout
            threading.Thread(
                target=self._graceful_shutdown_watchdog,
                args=(proc, info),
                daemon=True,
            ).start()

        return True

    @staticmethod
    def _terminate_process_group(proc: subprocess.Popen) -> None:
        """Send SIGTERM to the child's process group."""
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()

    @staticmethod
    def _kill_process_group(proc: subprocess.Popen) -> None:
        """Send SIGKILL to the child's process group."""
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()

    def _graceful_shutdown_watchdog(
        self,
        proc: subprocess.Popen,
        info: AgentInfo,
    ) -> None:
        """Wait for a process to exit; force-kill after timeout."""
        try:
            proc.wait(timeout=self._graceful_shutdown_timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_group(proc)
            self._audit(info, "agent.force_killed_after_timeout")

    def restart(self, agent_id: str) -> AgentInfo | None:
        """Restart an agent. Stops it first if running, then relaunches."""
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return None
            proc = self._processes.get(agent_id)

        # Stop if still running
        if proc and proc.poll() is None:
            self.stop(agent_id, force=True)
            proc.wait(timeout=5)

        with self._lock:
            info.restart_count += 1
            info.exit_code = None
            info.stopped_at = None
            info.error_message = ""

        self._start_process(info)
        self._audit(info, "agent.restarted", {"restart_count": info.restart_count})
        return info

    def get_agent(self, agent_id: str) -> AgentInfo | None:
        """Get info for a specific agent."""
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self, tenant_id: str | None = None) -> list[AgentInfo]:
        """List agents, optionally filtered by tenant."""
        with self._lock:
            agents = list(self._agents.values())
        if tenant_id is not None:
            agents = [a for a in agents if a.tenant_id == tenant_id]
        return agents

    def remove_agent(self, agent_id: str) -> bool:
        """Remove a stopped/errored agent from tracking. Returns False if still running."""
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return False
            if info.status in (AgentStatus.RUNNING, AgentStatus.STOPPING):
                return False
            del self._agents[agent_id]
            self._processes.pop(agent_id, None)
        return True

    def record_heartbeat(self, agent_id: str) -> bool:
        """Record a heartbeat from an agent. Returns False if agent not found."""
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return False
            info.last_heartbeat = _now()
            return True

    def poll(self) -> list[AgentInfo]:
        """Poll all running agents for status changes.

        Checks if subprocesses have exited and applies restart policies.
        Also checks heartbeat timeouts.
        Returns list of agents whose status changed.
        """
        changed: list[AgentInfo] = []

        with self._lock:
            items = list(self._agents.items())

        for agent_id, info in items:
            proc = self._processes.get(agent_id)
            if proc is None:
                continue

            # Check if process has exited
            returncode = proc.poll()
            if returncode is not None and info.status in (
                AgentStatus.RUNNING,
                AgentStatus.STOPPING,
            ):
                with self._lock:
                    info.exit_code = returncode
                    info.stopped_at = _now()
                    if returncode == 0 or info.status == AgentStatus.STOPPING:
                        info.status = AgentStatus.STOPPED
                    else:
                        info.status = AgentStatus.ERRORED
                        info.error_message = f"Process exited with code {returncode}"

                self._audit(info, "agent.exited", {"exit_code": returncode})
                changed.append(info)

                # Apply restart policy
                if self._should_restart(info):
                    info.restart_count += 1
                    try:
                        self._start_process(info)
                        self._audit(info, "agent.auto_restarted", {"restart_count": info.restart_count})
                    except (OSError, FileNotFoundError):
                        pass  # Already logged in _start_process
                continue

            # Check heartbeat timeout for running agents
            if info.status == AgentStatus.RUNNING and info.last_heartbeat is not None and (_now() - info.last_heartbeat) > self._heartbeat_timeout:
                with self._lock:
                    info.status = AgentStatus.DEAD
                    info.error_message = "Heartbeat timeout"
                self._audit(info, "agent.heartbeat_timeout")
                changed.append(info)

        return changed

    def _should_restart(self, info: AgentInfo) -> bool:
        """Determine if an agent should be restarted based on its restart policy."""
        if info.restart_policy == RestartPolicy.ALWAYS:
            return True
        if info.restart_policy == RestartPolicy.ON_FAILURE and info.exit_code != 0:
            return True
        return False

    def start_monitor(self) -> None:
        """Start background thread that periodically polls agents."""
        if self._monitor_thread is not None:
            return
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """Periodically poll agents for status changes."""
        while not self._monitor_stop.is_set():
            try:
                self.poll()
            except Exception:
                logger.exception("Error in agent monitor loop")
            self._monitor_stop.wait(self._heartbeat_interval)

    def stop_monitor(self) -> None:
        """Stop the background monitor thread."""
        self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

    def _audit(self, info: AgentInfo, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """Record an audit event for an agent."""
        try:
            self._audit_log.append(
                AuditEntry(
                    tenant_id=info.tenant_id,
                    agent_id=info.agent_id,
                    event_type=event_type,
                    payload=payload or {},
                )
            )
        except Exception:
            logger.exception("Failed to write audit entry")

    def close(self) -> None:
        """Stop all agents and clean up."""
        self._closed = True
        self.stop_monitor()

        with self._lock:
            for agent_id, proc in list(self._processes.items()):
                if proc.poll() is None:
                    self._terminate_process_group(proc)
                    try:
                        proc.wait(timeout=self._graceful_shutdown_timeout)
                    except subprocess.TimeoutExpired:
                        self._kill_process_group(proc)
                        proc.wait(timeout=5)
