#!/usr/bin/env bash
# Run the repo-local Nexus without changing PATH or shell profiles.
set -euo pipefail
cd -- "$(dirname -- "$0")"
test -f .local/nexus/packages/setup-cli/bin/nexus.mjs || {
  printf '%s\n' 'Nexus not installed. Run python3 setup.py first.' >&2
  exit 1
}
exec node .local/nexus/packages/setup-cli/bin/nexus.mjs "$@"
