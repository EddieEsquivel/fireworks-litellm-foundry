"""Local configuration and scoped launchers; Python standard library only."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ROUTES = {role: f"claude-{role.lower()}-foundry" for role in ("SONNET", "OPUS", "HAIKU")}
FIELDS = (
    "FOUNDRY_API_BASE", "FOUNDRY_API_KEY", "FOUNDRY_SONNET_DEPLOYMENT",
    "FOUNDRY_OPUS_DEPLOYMENT", "FOUNDRY_HAIKU_DEPLOYMENT",
    "LITELLM_PROXY_BASE_URL", "LITELLM_MASTER_KEY", "FOUNDRY_MODEL",
)
OPTIONAL_FIELDS = {"FOUNDRY_MODEL", *(f"FOUNDRY_{role}_DEPLOYMENT" for role in ROUTES)}


def deployment_for(values, role):
    """A single local model override wins over the legacy per-role mappings."""
    return values.get("FOUNDRY_MODEL", "").strip() or values.get(f"FOUNDRY_{role}_DEPLOYMENT", "").strip()


def read_env(path=ENV_FILE):
    """Parse literal values without executing shell substitutions or imports."""
    values = {}
    if not path.exists():
        return values
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in FIELDS or key in values:
            raise ValueError(f"Invalid or duplicate setting on .env line {number}")
        value = value.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON quoting on .env line {number}") from None
        if not isinstance(value, str) or any(c in value for c in "\r\n\x00"):
            raise ValueError(f"Invalid value on .env line {number}")
        values[key] = value
    return values


def validate(values):
    for field in FIELDS:
        value = values.get(field, "")
        if field not in OPTIONAL_FIELDS and not value.strip():
            raise ValueError(f"Missing {field}; run python3 setup.py")
        if any(c in value for c in "\r\n\x00"):
            raise ValueError(f"Invalid control character in {field}")
    base = urlsplit(values["FOUNDRY_API_BASE"])
    if (base.scheme != "https" or not base.hostname or base.username or base.password
            or base.query or base.fragment or not base.path.rstrip("/").endswith("/openai/v1")):
        raise ValueError("FOUNDRY_API_BASE must be an HTTPS OpenAI v1 base ending /openai/v1; no query or credentials")
    proxy = urlsplit(values["LITELLM_PROXY_BASE_URL"])
    if (proxy.scheme != "http" or proxy.hostname not in ("127.0.0.1", "localhost")
            or proxy.username or proxy.password or proxy.path not in ("", "/")
            or proxy.query or proxy.fragment or proxy.port is None or not 1024 <= proxy.port <= 65535):
        raise ValueError("Proxy URL must use HTTP, localhost or 127.0.0.1, and an explicit port 1024-65535; no path")
    if not values["LITELLM_MASTER_KEY"].startswith("sk-") or len(values["LITELLM_MASTER_KEY"]) < 35:
        raise ValueError("LITELLM_MASTER_KEY must start sk- and contain at least 32 more characters")
    for role in ROUTES:
        deployment = deployment_for(values, role)
        if not deployment or any(c.isspace() for c in deployment) or "/" in deployment:
            raise ValueError(f"FOUNDRY_{role}_DEPLOYMENT must be a deployment name, not a catalog path")


def load_config():
    values = read_env()
    # Explicit environment variables override local values for secret-store workflows.
    values.update({key: os.environ[key] for key in FIELDS if key in os.environ})
    validate(values)
    return values


def write_private(path, text):
    """Replace a local file without following symlinks or opening it world-readable."""
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def proxy_environment(values):
    env = os.environ.copy()
    env.update(values)
    for role in ROUTES:
        env[f"LITELLM_{role}_MODEL"] = "openai/" + deployment_for(values, role)
    env["LITELLM_TELEMETRY"] = "False"
    return env


def claude_environment(values):
    env = os.environ.copy()
    # Remove competing provider and auth selections in this child process only.
    for key in list(env):
        if key.startswith(("ANTHROPIC_", "FOUNDRY_", "LITELLM_")) or key in (
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
            "CLAUDE_CODE_USE_AWS", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
        ):
            env.pop(key)
    # A user's global ~/.claude/settings.json env block (for example a Nexus or other
    # gateway configuration) is merged on top of the child environment by Claude Code,
    # which overrides the proxy auth below. Point CLAUDE_CONFIG_DIR at a repo-local
    # config so only this repo's settings apply in the wrapped session.
    config_dir = ROOT / ".local/claude-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = config_dir / "settings.json"
    if not settings_file.exists():
        write_private(settings_file, "{}\n")
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    env.update({
        "ANTHROPIC_BASE_URL": values["LITELLM_PROXY_BASE_URL"].rstrip("/"),
        "ANTHROPIC_AUTH_TOKEN": values["LITELLM_MASTER_KEY"],
        "ANTHROPIC_MODEL": ROUTES["SONNET"],
        "CLAUDE_CODE_SUBAGENT_MODEL": ROUTES["SONNET"],
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })
    for role, route in ROUTES.items():
        env[f"ANTHROPIC_DEFAULT_{role}_MODEL"] = route
    return env


def run_child(command, env):
    try:
        return subprocess.call(command, env=env, cwd=ROOT)
    except KeyboardInterrupt:
        return 130


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "claude", "desktop-values"))
    parser.add_argument("--show-key", action="store_true", help="Explicitly reveal the proxy key for Desktop; do not record or share output")
    args, extra = parser.parse_known_args()
    values = load_config()
    if args.action == "start":
        if extra:
            parser.error("start does not accept extra options")
        binary = ROOT / ".venv/bin/litellm"
        if not binary.exists():
            raise ValueError("LiteLLM not installed; run python3 setup.py")
        port = urlsplit(values["LITELLM_PROXY_BASE_URL"]).port
        return run_child([str(binary), "--config", str(ROOT / "config.yaml"),
                          "--host", "127.0.0.1", "--port", str(port)], proxy_environment(values))
    if args.action == "claude":
        binary = shutil.which("claude")
        if not binary:
            raise ValueError("Claude Code is not installed or not on PATH")
        return run_child([binary, *extra], claude_environment(values))
    if extra:
        parser.error("desktop-values does not accept extra options")
    print("Gateway base URL:", values["LITELLM_PROXY_BASE_URL"])
    print("Gateway auth scheme: Bearer")
    print("Gateway API key:", values["LITELLM_MASTER_KEY"] if args.show_key else "[hidden; use --show-key locally]")
    for route in ROUTES.values():
        print("Model ID:", route)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError):
        # URL parsing and OS errors can contain private values; never echo them.
        print("Unable to launch: check .env values, file permissions, and setup installation. See README.md.", file=sys.stderr)
        sys.exit(1)
