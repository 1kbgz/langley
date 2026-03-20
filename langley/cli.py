"""langley CLI — command-line entry point for langley.

Usage:
    langley                   Start the server (API + built UI)
    langley up                Same as bare langley
    langley dev               Start API + JS watcher (serves from js/dist/)
    langley agent list        List running agents
    langley agent launch      Launch an agent from a profile
    langley agent stop <id>   Stop a running agent
    langley agent kill <id>   Force-kill an agent

Configuration is loaded from (in order):
    1. --config <path>
    2. ./langley.cfg
    3. ~/.langley.cfg

CLI flags override config file values.
"""

import argparse
import json
import logging
import signal
import subprocess
import sys
import threading
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from langley import __version__
from langley.config import DEFAULTS, load_config

logger = logging.getLogger(__name__)


def _find_js_dir() -> Path | None:
    """Locate the js/ source directory (only present in dev layout)."""
    js_dir = Path(__file__).parent.parent / "js"
    if (js_dir / "package.json").is_file():
        return js_dir
    return None


def _api_request(base: str, method: str, path: str, body: dict | None = None) -> dict:
    """Make a JSON request to the langley API server."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as resp:  # noqa: S310 — URL comes from user's own --url flag
            return json.loads(resp.read())
    except URLError as e:
        logger.error("Error connecting to %s: %s", base, e)
        sys.exit(1)


def _start_api_server(host: str, port: int, data_dir: str, auth_provider: str = "none", static_dir: Path | None = None):
    """Start the Starlette API server via uvicorn in a background thread."""
    import uvicorn  # optional heavy dependency

    from langley.server import create_app
    from langley.server_state import ServerState

    state = ServerState.create_default(data_dir=data_dir, auth_provider=auth_provider)
    if static_dir is not None:
        state.static_dir = static_dir
    app = create_app(state)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


def _start_js_watch(js_dir: Path) -> subprocess.Popen:
    """Start the JS rebuild watcher (nodemon) as a subprocess."""
    return subprocess.Popen(
        ["pnpm", "run", "watch"],
        cwd=str(js_dir),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def _wait_and_cleanup(js_proc: subprocess.Popen | None) -> int:
    """Block until Ctrl+C, then clean up child processes."""
    try:
        if js_proc is not None:
            js_proc.wait()
        else:
            signal.pause()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if js_proc is not None and js_proc.poll() is None:
            js_proc.terminate()
            try:
                js_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                js_proc.kill()
    return 0


# ── Server commands ────────────────────────────────────────────


def cmd_up(args: argparse.Namespace) -> int:
    """Start the langley server (API + built UI on one port)."""
    host = args.host
    port = args.port
    _start_api_server(host, port, data_dir=args.data_dir, auth_provider=args.auth)
    logger.info("Running at http://%s:%d (auth: %s)", host, port, args.auth)
    logger.info("Press Ctrl+C to stop.")
    return _wait_and_cleanup(None)


def cmd_dev(args: argparse.Namespace) -> int:
    """Start development servers (API + JS live-rebuild).

    In dev mode the API server serves static files from js/dist/ so that
    the nodemon watcher rebuilds are picked up on browser refresh.
    """
    host = args.host
    api_port = args.port
    js_dir = _find_js_dir()

    api_server = None
    js_proc = None

    if not args.ui_only:
        dev_static = js_dir / "dist" if js_dir is not None else None
        api_server = _start_api_server(host, api_port, data_dir=args.data_dir, auth_provider=args.auth, static_dir=dev_static)
        logger.info("API server running at http://%s:%d (auth: %s)", host, api_port, args.auth)

    if not args.api_only:
        if js_dir is not None:
            logger.info("Starting JS rebuild watcher in %s", js_dir)
            js_proc = _start_js_watch(js_dir)
        else:
            logger.warning("JS source directory not found, skipping JS dev watcher")

    if api_server is None and js_proc is None:
        logger.error("Nothing to start")
        return 1

    logger.info("Dev servers running. Press Ctrl+C to stop.")
    return _wait_and_cleanup(js_proc)


# ── Agent commands ─────────────────────────────────────────────


def cmd_agent_list(args: argparse.Namespace) -> int:
    """List running agents."""
    data = _api_request(args.url, "GET", "/api/agents")
    if not data:
        logger.info("No agents.")
        return 0
    # Simple table output
    header = f"{'AGENT ID':<36}  {'STATUS':<10}  {'PROFILE':<20}  {'PID':<8}  {'UPTIME'}"
    logger.info(header)
    for a in data:
        uptime = f"{a.get('uptime_seconds', 0):.0f}s"
        pid = str(a.get("pid") or "-")
        logger.info("%s  %s  %s  %s  %s", a["agent_id"].ljust(36), a["status"].ljust(10), a.get("profile_name", "").ljust(20), pid.ljust(8), uptime)
    return 0


def cmd_agent_launch(args: argparse.Namespace) -> int:
    """Launch an agent from a profile."""
    body: dict = {}
    if args.profile_id:
        body["profile_id"] = args.profile_id
    else:
        body["profile"] = {"name": args.name, "tenant_id": args.tenant or "default", "command": args.command}
    data = _api_request(args.url, "POST", "/api/agents", body)
    logger.info("Launched agent %s (status: %s)", data["agent_id"], data["status"])
    return 0


def cmd_agent_stop(args: argparse.Namespace) -> int:
    """Stop an agent."""
    _api_request(args.url, "POST", f"/api/agents/{args.agent_id}/stop")
    logger.info("Stopping agent %s", args.agent_id)
    return 0


def cmd_agent_kill(args: argparse.Namespace) -> int:
    """Kill an agent."""
    _api_request(args.url, "POST", f"/api/agents/{args.agent_id}/kill")
    logger.info("Killing agent %s", args.agent_id)
    return 0


# ── Main entry point ───────────────────────────────────────────


def _add_server_args(p: argparse.ArgumentParser) -> None:
    """Add common server CLI arguments to a subparser."""
    p.add_argument("--host", default=None, help="Server host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="Server port (default: 8000)")
    p.add_argument("--data-dir", default=None, help="Data directory (default: .langley)")
    p.add_argument("--auth", default=None, choices=["none", "local", "pam", "mac", "win32"], help="Auth provider (default: none)")


def _apply_config_defaults(args: argparse.Namespace, cfg) -> None:
    """Fill in unset CLI args from the config file values."""
    if hasattr(args, "host") and args.host is None:
        args.host = cfg.get("server", "host", fallback=DEFAULTS["server"]["host"])
    if hasattr(args, "port") and args.port is None:
        args.port = cfg.getint("server", "port", fallback=int(DEFAULTS["server"]["port"]))
    if hasattr(args, "data_dir") and args.data_dir is None:
        args.data_dir = cfg.get("server", "data_dir", fallback=DEFAULTS["server"]["data_dir"])
    if hasattr(args, "auth") and args.auth is None:
        args.auth = cfg.get("auth", "provider", fallback=DEFAULTS["auth"]["provider"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="langley", description="Langley — launcher and control plane for LLM agents")
    parser.add_argument("--version", action="version", version=f"langley {__version__}")
    parser.add_argument("--config", default=None, metavar="PATH", help="Path to config file (default: ./langley.cfg or ~/.langley.cfg)")
    sub = parser.add_subparsers(dest="command")

    # langley up
    up_parser = sub.add_parser("up", help="Start langley server")
    _add_server_args(up_parser)
    up_parser.set_defaults(func=cmd_up)

    # langley dev
    dev_parser = sub.add_parser("dev", help="Start development servers (API + JS live-rebuild)")
    _add_server_args(dev_parser)
    dev_parser.add_argument("--api-only", action="store_true", help="Start only the API server")
    dev_parser.add_argument("--ui-only", action="store_true", help="Start only the JS dev watcher")
    dev_parser.set_defaults(func=cmd_dev)

    # langley agent ...
    agent_parser = sub.add_parser("agent", help="Manage agents (requires a running server)")
    agent_parser.add_argument("--url", default="http://127.0.0.1:8000", help="API server URL")
    agent_sub = agent_parser.add_subparsers(dest="agent_command")

    # langley agent list
    ag_list = agent_sub.add_parser("list", help="List running agents")
    ag_list.set_defaults(func=cmd_agent_list)

    # langley agent launch
    ag_launch = agent_sub.add_parser("launch", help="Launch an agent")
    ag_launch.add_argument("--profile-id", default="", help="Profile ID to launch from")
    ag_launch.add_argument("--name", default="", help="Agent name (for inline profile)")
    ag_launch.add_argument("--tenant", default="", help="Tenant ID (default: 'default')")
    ag_launch.add_argument("command", nargs="*", help="Command to run (for inline profile)")
    ag_launch.set_defaults(func=cmd_agent_launch)

    # langley agent stop
    ag_stop = agent_sub.add_parser("stop", help="Stop a running agent")
    ag_stop.add_argument("agent_id", help="Agent ID to stop")
    ag_stop.set_defaults(func=cmd_agent_stop)

    # langley agent kill
    ag_kill = agent_sub.add_parser("kill", help="Force-kill an agent")
    ag_kill.add_argument("agent_id", help="Agent ID to kill")
    ag_kill.set_defaults(func=cmd_agent_kill)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        # Bare `langley` → same as `langley up`
        args = parser.parse_args(["up"] + (argv if argv is not None else []))

    # Load config file and fill in unset values
    cfg = load_config(args.config)
    _apply_config_defaults(args, cfg)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
