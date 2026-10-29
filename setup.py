#!/usr/bin/env python3
"""Interactive bootstrap, not a setuptools package. See setup.README.md."""

import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import venv

from runtime import ENV_FILE, FIELDS, ROOT, read_env, validate, write_private

NEXUS_SOURCE = "https://github.com/fw-ai/nexus-cli.git"
NEXUS_REVISION = "b1d5c968e9b9f7e18c2f02e8c631b3b8b3905bdf"
NEXUS_DIR = ROOT / ".local/nexus"


def collect_values(non_interactive):
    values = read_env()
    values.update({key: os.environ[key] for key in FIELDS if key in os.environ})
    prompts = {
        "FOUNDRY_API_BASE": "Full Foundry HTTPS OpenAI v1 base URL (from deployment sample)",
        "FOUNDRY_API_KEY": "Foundry resource API key (hidden)",
        "FOUNDRY_SONNET_DEPLOYMENT": "Foundry deployment for the Sonnet route",
        "FOUNDRY_OPUS_DEPLOYMENT": "Foundry deployment for the Opus route (can be the same)",
        "FOUNDRY_HAIKU_DEPLOYMENT": "Foundry deployment for the Haiku route (can be the same)",
        "LITELLM_PROXY_BASE_URL": "Local proxy HTTP base URL (loopback + explicit unused port)",
    }
    if not non_interactive and not values.get("FOUNDRY_MODEL"):
        values["FOUNDRY_MODEL"] = input(
            "Foundry deployment for ALL Claude models (blank for per-role mappings): "
        ).strip()
    for field, prompt in prompts.items():
        if values.get("FOUNDRY_MODEL") and field.endswith("_DEPLOYMENT"):
            continue
        if not values.get(field) and not non_interactive:
            reader = getpass.getpass if field.endswith("API_KEY") else input
            values[field] = reader(prompt + ": ").strip()
    if not values.get("LITELLM_MASTER_KEY"):
        values["LITELLM_MASTER_KEY"] = "sk-" + secrets.token_urlsafe(32)
    validate(values)
    return values


def install_nexus():
    for binary in ("node", "npm", "git"):
        if not shutil.which(binary):
            raise ValueError(f"Install {binary} first; see setup.README.md")
    major = subprocess.check_output(["node", "-p", "process.versions.node.split('.')[0]"], text=True).strip()
    if int(major) < 22:
        raise ValueError("Node.js 22+ required for Nexus")
    NEXUS_DIR.parent.mkdir(exist_ok=True)
    if not NEXUS_DIR.exists():
        subprocess.run(["git", "clone", "--no-checkout", NEXUS_SOURCE, str(NEXUS_DIR)], check=True)
    else:
        actual = subprocess.check_output(["git", "-C", str(NEXUS_DIR), "remote", "get-url", "origin"], text=True).strip()
        if actual != NEXUS_SOURCE:
            raise ValueError("Unexpected Nexus origin; inspect .local/nexus manually")
    subprocess.run(["git", "-C", str(NEXUS_DIR), "checkout", "--detach", NEXUS_REVISION], check=True)
    # Disable the upstream postinstall finalizer: it can modify global harness settings.
    subprocess.run(["npm", "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
                   cwd=NEXUS_DIR / "packages/setup-cli", check=True)


def install_litellm():
    environment = ROOT / ".venv"
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(environment / "bin/python"), "-m", "pip", "install", "--requirement",
                    str(ROOT / "requirements.txt")], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--non-interactive", action="store_true", help="Read .env/environment without prompts")
    parser.add_argument("--configure-only", action="store_true", help="Write local configuration without downloading dependencies")
    parser.add_argument("--skip-nexus", action="store_true", help="Install only LiteLLM and configuration")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11+ is required")
    if os.name != "posix":
        parser.error("Use macOS, Linux, or WSL; native Windows is not supported")
    os.umask(0o077)
    values = collect_values(args.non_interactive)
    write_private(ENV_FILE, "# Local secrets; JSON-quoted literal values. Do not source or share.\n" +
                  "".join(f"{field}={json.dumps(values.get(field, ""))}\n" for field in FIELDS))
    if not args.configure_only:
        if not args.skip_nexus:
            install_nexus()
        install_litellm()
    print("Local configuration saved privately to .env; credentials were not printed.")
    print("Start: python3 runtime.py start")
    print("Verify (billable): python3 smoke_test.py --allow-billable")
    print("Launch Claude Code: python3 runtime.py claude")
    print("Local Nexus: ./nexus.sh --help (does not configure this proxy)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError):
        print("Setup failed. Check required inputs, prerequisites, and dependency installer output; see setup.README.md.", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Setup cancelled.", file=sys.stderr)
        sys.exit(130)
