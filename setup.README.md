# `setup.py`: implementation and LiteLLM configuration reference

This document is the companion to [`setup.py`](setup.py). For the user journey, start with [README.md](README.md). `setup.py` is an executable bootstrap utility, **not** a setuptools packaging entry point. Do not run `pip install .` or `python setup.py install`.

## Single-model override and Desktop wildcard routing (2026-10-29)

`FOUNDRY_MODEL` is an optional ninth `.env` field. Set it to an exact Azure deployment name to override **all** per-role mappings; when it is nonempty, the three `FOUNDRY_*_DEPLOYMENT` values are optional and ignored. Leave it empty to preserve the legacy role-specific behavior. Interactive setup offers this option before requesting per-role deployment names. The actual value belongs only in ignored `.env` alongside the Azure key, never in committed YAML.

`deployment_for()` resolves this override before `proxy_environment()` creates the provider-prefixed `LITELLM_*_MODEL` values. The YAML now includes a `claude-*` pattern route using `LITELLM_SONNET_MODEL`, in addition to the three explicit routes. Thus built-in/background Anthropic Claude IDs map to the single override (or the Sonnet deployment in legacy per-role mode). The wildcard is restricted to the Claude namespace: unrelated names fail, and the incoming Claude name is never substituted into the upstream deployment. The three explicit routes take precedence over the wildcard. See [LiteLLM wildcard routing](https://docs.litellm.ai/docs/wildcard_routing).

Restart LiteLLM after changing `.env`. Existing environment-variable overrides still take precedence over local file values. The checked-in `.env.example` contains only an empty `FOUNDRY_MODEL`; no customer deployment value is committed.

## Scope and prerequisites

The goal is a single-user local integration between an Anthropic Messages client and Fireworks deployments billed through Microsoft Foundry. The script requires Python 3.11+ on POSIX (macOS, Linux, or WSL). A normal full setup also requires Node.js 22+, npm, Git, internet access to GitHub/npm/PyPI, and Python's venv/pip support. It does not install system prerequisites, request administrator access, configure Azure resources, or install Claude Code/Desktop.

All Python setup/runtime utilities use the standard library; LiteLLM itself is installed into an isolated virtual environment. The scripts resolve file paths from their own location rather than assuming the current shell directory.

## Invocation and flags

```bash
python3 setup.py
python3 setup.py --non-interactive
python3 setup.py --configure-only
python3 setup.py --skip-nexus
python3 setup.py --help
```

- **Default:** collect configuration, save it, install repo-local Nexus, and install LiteLLM. Missing values prompt; the Foundry key uses `getpass` so terminal echo is disabled.
- **`--non-interactive`:** never prompt. Missing required values cause failure. Read `.env` and/or the process environment. This is not a license to put secrets into command history or CI logs; use your CI's masked secret injection.
- **`--configure-only`:** validate and write configuration without downloading or installing anything. Useful for initial review or reconfiguration. It will not make `runtime.py start` work until LiteLLM is installed.
- **`--skip-nexus`:** install LiteLLM and write configuration, but do not install Nexus. Useful if company policy manages Nexus separately. The repo-local `nexus.sh` requires the local installation; it does not look for a global CLI.
- Options can be combined. No option initiates inference or launches a background daemon.

## Exact setup sequence

### 1. Check platform and set a restrictive file mask

Python must be 3.11 or newer. Native Windows is rejected because virtualenv executables and the shell launcher use POSIX paths. The process sets `umask(077)` before writing configuration or installing dependencies. This does not retroactively repair permissions on existing unrelated files.

### 2. Read `.env` as inert data

`runtime.read_env()` accepts blank lines, whole-line comments, and `NAME=value` assignments for the nine known settings in `.env.example`. Duplicate or unknown setting names fail. There is no shell evaluation, variable expansion, `export` syntax, command substitution, interpolation, or inline-comment handling. Double-quoted values are decoded as JSON strings. Raw one-line values are also accepted, but JSON quoting is recommended for punctuation. Single quotes are literal characters, not shell quoting.

The setup script never sources `.env`. The file is deliberately not a shell script and should not be sourced by users either.

### 3. Overlay process environment values

Only the nine supported configuration names are read from the process environment. An explicitly present environment value takes precedence over the corresponding `.env` value, including an empty value. Setup prompts for missing values in interactive mode. In noninteractive mode, validation catches missing inputs.

**Persistence warning:** setup writes the resulting merged values into `.env`, even if they originated in a secret store. If you require environment-only secrets, do not run setup with production credentials: install dependencies using throwaway configuration, remove the local secrets file, and inject the required connection/credential settings and either `FOUNDRY_MODEL` or all three per-role mappings only when starting runtime utilities. The runtime loader supports environment-only operation and never writes secrets back to disk.

### 4. Collect the connection inputs

- **`FOUNDRY_API_BASE`:** the exact HTTPS OpenAI v1 base from the deployment sample. It must end in `/openai/v1` (trailing slash optional). Resource-root and project-scoped v1 bases are accepted. Userinfo, URL query strings, and fragments are rejected. The script does not turn an arbitrary project URL into an inference URL and does not silently strip an operation suffix. It does not restrict hostname to a single Azure domain; the operator must trust and verify the endpoint before entering a key. A wrong but syntactically valid host could receive your credential.
- **`FOUNDRY_API_KEY`:** Azure resource API key used by the proxy for upstream authentication. Required; the script does not contact Azure to validate it during setup.
- **`FOUNDRY_SONNET_DEPLOYMENT`:** exact deployment name used behind `claude-sonnet-foundry`.
- **`FOUNDRY_OPUS_DEPLOYMENT`:** exact deployment name used behind `claude-opus-foundry`.
- **`FOUNDRY_HAIKU_DEPLOYMENT`:** exact deployment name used behind `claude-haiku-foundry`.
- **`LITELLM_PROXY_BASE_URL`:** operator-chosen local HTTP base with hostname `127.0.0.1` or `localhost`, explicit port 1024–65535, and no non-root path. No username, password, query, or fragment. The listener always binds IPv4 loopback; use `127.0.0.1` if your system resolves `localhost` to an incompatible IPv6-only listener.
- **`LITELLM_MASTER_KEY`:** generated if absent/empty at setup using `sk-` plus `secrets.token_urlsafe(32)`. This uses 32 bytes of cryptographic randomness. Supplied keys must start `sk-` and have at least 32 additional characters; length validation alone does not establish entropy. Existing keys are retained on rerun.

Deployment names cannot contain whitespace or `/`; do not supply provider prefixes or full catalog paths. All three deployment values may be identical. An alias called “Opus” does not deploy or select Anthropic Opus: only the Azure deployment name determines the model.

All fields reject line breaks and NUL characters when loaded from disk. Errors intentionally withhold private values rather than echoing malformed URLs or credentials.

### 5. Write `.env` privately

`write_private()` creates an exclusive temporary file with mode `0600`, serializes values with JSON string quoting, then atomically replaces `.env`. It does not follow an existing `.env` symlink to write its target. An existing temporary file causes failure rather than unsafe reuse. The temporary file is removed on normal cleanup. If the machine/process crashes before cleanup, inspect a leftover `.env.tmp` locally before removing it; it may contain secrets. `.gitignore` covers `.env.*`.

The plaintext file is not encrypted. Backups, endpoint-management tools, other programs running as the same user, and administrators may access it. Use your organization's approved secret-management approach for production.

### 6. Install Nexus without running the global installer

The script clones the public [Nexus source repository](https://github.com/fw-ai/nexus-cli) into `.local/nexus` with no initial checkout, then checks out this exact revision:

`b1d5c968e9b9f7e18c2f02e8c631b3b8b3905bdf` (package version 0.10.1 at inspection time).

It then runs `npm ci --omit=dev --ignore-scripts --no-audit --no-fund` in `packages/setup-cli`.

Why this approach:

- The official installer is useful for normal end users, but performs global launcher/profile and finalization work. This reference deliberately avoids it to preserve existing harness configuration.
- The source revision is immutable rather than floating at `main`.
- `npm ci` consumes the upstream lockfile rather than resolving new ranges.
- `--ignore-scripts` prevents the package's postinstall finalizer from reconciling global harness settings, as well as disabling dependency lifecycle scripts.
- `nexus.sh` directly invokes the installed Node entry point, without modifying PATH or writing a system launcher.

If `.local/nexus` already exists, setup checks its origin string and re-checks out the pinned revision. It does not use `git reset --hard`, clean the checkout, or delete local modifications; conflicting local edits can cause checkout failure. The Nexus source/dependencies occupy local disk and are excluded from Git. The full source clone can be larger than a packaged binary installation.

**Boundary:** this is an isolated installation, not a claim that every future Nexus command is side-effect free. Explicit Nexus commands may manage global settings, credentials, or network connections according to upstream behavior. Running `nexus.sh --help` is informational. For this Foundry proxy, launch Claude with `runtime.py claude`, not Nexus's harness commands. Nexus does not implement this repository's transport translation and is not in the inference request path.

### 7. Install LiteLLM into `.venv`

If absent, Python creates `.venv` with pip. Setup then invokes that environment's Python with `-m pip install --requirement requirements.txt`. The direct dependency is `litellm[proxy]==1.106.4`.

The `proxy` extra installs server dependencies required for the `litellm` console command. No global pip installation is performed. This is a direct-version pin, **not** a hash-locked transitive dependency set or a security certification. Review upstream release notes, package provenance, dependency advisories, and your organization's approved package mirror before deploying. Rerunning setup can resolve different transitive versions if they are not already installed. There is no implicit `pip --upgrade` to a floating LiteLLM release.

The install subprocess streams normal package output. Private package-index URLs from your own pip/npm/Git environment may appear in installer diagnostics; do not publish raw logs without review. Failed dependency installation does not undo the already-saved `.env`. Rerun after fixing the prerequisite/network issue.

## LiteLLM configuration: every decision

### `model_list` and client-visible names

`config.yaml` exposes three explicit client-facing routes:

- `claude-sonnet-foundry`
- `claude-opus-foundry`
- `claude-haiku-foundry`

These are stable client-facing routes, not Azure deployment IDs. A fourth pattern route, `claude-*`, catches built-in/background Claude IDs and sends them to the single-model override or the Sonnet deployment. This includes misspellings in the Claude namespace, so inspect client requests when debugging unexpected selections. Unrelated model IDs fail. There is no automatic Azure deployment discovery, fallback, or load balancing.

If a client requests an ID outside `claude-*`, add an explicit alias under `router_settings.model_group_alias` pointing that ID to one of these route names. Review which capability/role the client expects; changing the name does not create that capability. Commit only non-customer-specific aliases. Restart LiteLLM after any configuration change.

### Provider selection: `openai/`, not `anthropic/` or legacy `azure/`

Before spawning LiteLLM, `proxy_environment()` derives three environment values by prepending `openai/` to the user-supplied deployment name:

- `LITELLM_SONNET_MODEL`
- `LITELLM_OPUS_MODEL`
- `LITELLM_HAIKU_MODEL`

Each route's `litellm_params.model` references its corresponding value through LiteLLM's `os.environ/…` syntax. LiteLLM strips the provider prefix to obtain the upstream `model` request field. `openai/` means “use the OpenAI-compatible protocol”; **it does not select OpenAI-hosted models or OpenAI billing**. The configured API base directs requests to Foundry.

The sibling example uses `anthropic/` with Fireworks' native Messages endpoint. That approach is not copied: Fireworks models in this Foundry scenario are consumed through the OpenAI v1 surface. Nor do we use the native Azure Anthropic provider configuration, which is a different route for actual Claude models hosted by Azure. Legacy `azure/` deployment routes use different URL/version semantics and are not appropriate for this v1 configuration.

References: [OpenAI-compatible endpoints](https://docs.litellm.ai/docs/providers/openai_compatible), [Azure AI provider](https://docs.litellm.ai/docs/providers/azure_ai), and [Azure Anthropic provider (a different integration)](https://docs.litellm.ai/docs/providers/azure/azure_anthropic).

### `api_base` and the upstream path

Every route uses `api_base: os.environ/FOUNDRY_API_BASE`. Runtime never injects a repository-owned inference URL. The OpenAI-compatible client appends `/chat/completions` to the v1 base. Do not include that operation in the base and do not use a Responses-only provider passthrough URL.

No `api_version` is supplied: Foundry's OpenAI v1 API uses implicit versioning. The incoming Anthropic protocol version header and the Azure API version are unrelated concepts.

References: [Foundry v1 API lifecycle](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle), [Foundry endpoints](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints), and [Fireworks deployments on Foundry](https://learn.microsoft.com/en-us/azure/foundry/how-to/fireworks/enable-fireworks-models).

### `api_key` and the two credential boundaries

Every route uses `api_key: os.environ/FOUNDRY_API_KEY`. The OpenAI-compatible client sends it as an upstream bearer credential. Microsoft's v1 examples use `OpenAI(api_key=...)` for Foundry API-key authentication. This reference is API-key based; it does not acquire, refresh, or manage Entra tokens.

Separately, `general_settings.master_key: os.environ/LITELLM_MASTER_KEY` protects the local proxy API. Claude sends this local credential as its bearer token. Do not substitute the Azure key in the Claude client or send the proxy master key to Azure.

A master key is convenient for a one-user local example but has gateway-administration scope. A shared service should issue scoped [LiteLLM virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys) with appropriate authorization, expiration, model access, budgets, and database-backed management.

### Anthropic ingress and translation

Claude Code connects to the root of the local proxy through `ANTHROPIC_BASE_URL` and appends `/v1/messages`. LiteLLM accepts the Anthropic request, maps messages/system content/tool schemas/tool choices to Chat Completions, invokes the chosen Foundry deployment, and translates its response into Anthropic message/content blocks. For `stream: true`, LiteLLM translates upstream streaming into Anthropic SSE event framing.

This is translation, not byte-for-byte pass-through. Anthropic-hosted tools, extended thinking, beta fields, cache controls, image formats, usage semantics, and token-counting support may differ or fail. The configuration does not claim native Anthropic reasoning signatures or server-side tools. Confirm each required feature with the actual deployment/client versions.

References: [LiteLLM Claude Code setup](https://docs.litellm.ai/docs/proxy/client_setup/claude_code), [Anthropic Messages interface](https://docs.litellm.ai/docs/anthropic_unified), and [Claude gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol).

### Strict parameter handling

`litellm_settings.drop_params: false` keeps unsupported fields visible as errors instead of silently removing them. Depending on the selected provider transformation, some fields may still be translated or handled locally; this option is not proof of perfect semantic preservation. If a feature fails, inspect the field and deployment contract and make a narrowly scoped, documented decision. Do not casually enable global parameter dropping to get past a smoke test.

No global token limit, reasoning budget, temperature, context window, caching policy, or capability metadata is invented. Different deployments have different constraints. The smoke test uses a bounded `max_tokens` value for its own calls only, not as a server-wide configuration.

Reference: [LiteLLM parameter dropping](https://docs.litellm.ai/docs/completion/drop_params).

### Reasoning replay compatibility hook

`litellm_settings.callbacks` registers `reasoning_history_hook.proxy_handler_instance`, a `CustomLogger` whose `async_pre_call_hook` runs before every upstream call. It deep-copies and strips `reasoning_content`, `thinking_blocks`, `reasoning`, and inline `thinking`/`redacted_thinking` content blocks from **historical assistant messages only**, leaving tool calls and text intact. Unmodified messages are passed through by reference, so unchanged requests aren't copied.

Why it exists: Anthropic Messages clients (Claude Code) replay assistant thinking blocks in every follow-up request — every tool-result turn. LiteLLM's translation converts those into OpenAI-style reasoning fields on the assistant history, and the Foundry OpenAI v1 surface rejects those fields with `invalid_payload` (observed 2026-10-27 against a real Fireworks deployment). Without this hook, every agentic tool turn fails; with it, full Bash-tool round trips succeed while the model still generates live reasoning and the client still receives translated thinking blocks for the current turn.

This is a compatibility shim for a non-Anthropic-native upstream, not a semantics-preserving feature: stripping replayed reasoning can affect multi-turn reasoning quality, and guardrail-style hooks see the modified history. If your deployment gains Anthropic-native routing (or a Foundry build accepts reasoning fields on history), remove the callback entry and the hook file, and re-run the tool round-trip check.

Reference: [LiteLLM custom callbacks](https://docs.litellm.ai/docs/proxy/callable_hooks).

### Logging and telemetry

`turn_off_message_logging: true` disables prompt/response attachment to LiteLLM logging callbacks. The runtime child environment also sets `LITELLM_TELEMETRY=False`. There are no logging callbacks, prompt databases, spend dashboards, or request-body debug flags configured by this repo.

These controls are not a guarantee that no sensitive data ever appears in logs. HTTP access logs, dependency exceptions, upstream Azure service diagnostics, client telemetry policies, and manually enabled debug settings are separate concerns. Avoid verbose logs in customer-shared artifacts. The smoke script intentionally omits response bodies from errors.

### Listener and lifecycle

`runtime.py start` executes the `.venv/bin/litellm` console command with `--config`, `--host 127.0.0.1`, and the port parsed from the operator's local URL. It does not bind all interfaces. HTTP is allowed only for the local hop; the upstream URL must be HTTPS. Other local processes can still access the listener and must be considered in the workstation threat model.

The process runs in the foreground and inherits signals; Ctrl+C stops it. There is no PID-file-based killing, system service registration, daemon restart policy, TLS termination, or background log file. If a port is occupied, the server should fail rather than killing another process. Startup itself is not an inference test; perform the explicit smoke test before connecting clients.

## Claude Code environment, precisely

`runtime.py claude` copies the parent environment and removes competing `ANTHROPIC_*`, `FOUNDRY_*`, and `LITELLM_*` values before inserting only the intended Claude client settings. It also removes provider selectors for Bedrock, Vertex, Foundry, and AWS and a forced subagent model override. This prevents the repo's Azure key from being directly inherited as `FOUNDRY_API_KEY` by the child.

The inserted settings are:

- `ANTHROPIC_BASE_URL`: operator-supplied local gateway base, trailing slash trimmed.
- `ANTHROPIC_AUTH_TOKEN`: local proxy master key.
- `ANTHROPIC_MODEL`: `claude-sonnet-foundry`.
- `ANTHROPIC_DEFAULT_SONNET_MODEL`: `claude-sonnet-foundry`.
- `ANTHROPIC_DEFAULT_OPUS_MODEL`: `claude-opus-foundry`.
- `ANTHROPIC_DEFAULT_HAIKU_MODEL`: `claude-haiku-foundry`.
- `CLAUDE_CODE_SUBAGENT_MODEL`: `claude-sonnet-foundry` (a tool/agent-specific model can still override this).
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`: `1`.

The wrapper locates the already-installed `claude` executable on PATH and forwards its arguments without shell interpolation. No key is placed in argv. The initial working directory is this repository; use Claude's normal directory commands if you want to work elsewhere. User-level settings are isolated with `CLAUDE_CONFIG_DIR=.local/claude-config`; existing local settings there are preserved on relaunch. Project and managed settings still apply, as do organization policies. A child process is not a security sandbox: a coding agent with file-read permissions could read `.env`, and a subprocess environment is visible to suitably privileged local processes. Apply normal agent permissions and use a separate working directory/secret store for sensitive workloads.

Reference: [Claude Code model aliases](https://code.claude.com/docs/en/model-config) and [connecting an LLM gateway](https://code.claude.com/docs/en/llm-gateway-connect).

## Verification and evidence boundaries

### Offline checks

```bash
python3 -m unittest discover -s tests -v
```

These validate inert configuration parsing, URL validation, secret-file permissions, provider model construction, client environment scoping, setup rerun behavior, and smoke-test assertions using synthetic local data/mocks. They do not need or read another project's secrets.

### Local build verification (2026-10-27)

The initial implementation was checked on macOS with Python 3.12.13 and Node.js 24.4.1:

- All 11 standard-library offline unit tests passed.
- LiteLLM 1.106.4 and its proxy dependencies installed successfully; `pip check` found no broken requirements.
- The actual LiteLLM `ProxyConfig.get_config()` loader resolved the environment-backed model names, and its Router accepted all three synthetic OpenAI-compatible routes. No inference request was made.
- The pinned Nexus source and locked dependencies installed with lifecycle scripts disabled; `./nexus.sh --help` ran successfully.
- Shell syntax and Git ignore rules were checked. `.gitattributes` enforces LF line endings for portable shell execution.

This initial check established local installation/configuration only. Subsequent live Foundry/Claude Code testing and user-supplied Desktop screenshots are documented in the later sections below.

### Live smoke checks

```bash
python3 smoke_test.py --allow-billable
```

The mandatory flag records explicit consent to seven potential inference requests. First the script checks `/v1/models` rejects a bad credential, then verifies all three routes exist with the correct credential. It sends one ordinary message and one stream per route, then a forced tool-call request on Sonnet. It validates Anthropic response blocks and stream events, without printing generated text or executing a tool. Timeouts are 180 seconds per request. It does not retry at the script level; SDK/provider layers may have their own policies.

For publication-quality compatibility claims, additionally test a tool-result round trip in a disposable coding workspace, long contexts and compaction, each required image/document format, representative client operations, client upgrades, Azure quotas, key rotation, and cancellation. Capture software versions and the model/deployment version without publishing private URLs or keys.

### Live verification (2026-10-27, contributor's own Foundry project)

The full path was validated locally against a real Microsoft Foundry resource (Fireworks `FW-Kimi-K3` deployment, API-key auth) with LiteLLM 1.106.4 and Claude Code 2.1.286:

- All 8 `smoke_test.py` checks passed: auth rejection, model discovery, text + streaming on all three routes, and forced tool use.
- Claude Code end-to-end: `-p` query returned through the proxy, and a full agentic turn (Bash tool call → tool result → follow-up reasoning) completed successfully.
- One real incompatibility was found and fixed in this repo: Claude Code replays assistant **thinking blocks** in follow-up requests, and LiteLLM translates them into `reasoning_content` on the OpenAI-compatible upstream call, which Foundry rejects with `invalid_payload`. The `reasoning_history_hook.py` CustomLogger (registered under `litellm_settings.callbacks`) strips replayed reasoning fields from history before the request leaves the proxy; live reasoning generation is unaffected. Without this hook, every agentic tool turn fails.
- The proxy also rejects unknown client keys with HTTP 400 (not 401/403) when running master-key-only without a database; `smoke_test.py` accounts for this.
- Claude Code may warn that `claude-*-foundry` is not in its model catalog and assumes a 200k context; this is cosmetic for these routes. Auto-mode classifier billing eligibility was reported as unavailable behind a non-first-party host.
- Claude Code layered a user's global `~/.claude/settings.json` (a Nexus/Fireworks gateway config) over the wrapper environment, which broke proxy auth. `runtime.py claude` now points `CLAUDE_CONFIG_DIR` at a repo-local config directory so wrapped sessions ignore user-level settings. This also means wrapped sessions do not see user-level MCP servers or settings; add what you need to `.local/claude-config/settings.json`.

Still not verified in that test: long-context/compaction behavior, image inputs, extended thinking budgets, token counting, and the Claude Desktop UI. The subsequent October 29 user-supplied Desktop screenshots are described below.

### Desktop evidence

On October 29, 2026, the user supplied five authentic macOS Desktop screenshots showing the developer menus, Gateway connection settings, an expanded model route, and a responding test conversation with `claude-opus-foundry` selected. The main README now embeds these captures and follows their visible field labels. Local connection values and personal details are redacted/cropped; see [screenshot provenance](docs/screenshots/README.md). The exact Desktop build was not recorded, and the images do not establish compatibility for every Desktop capability or independently prove which upstream handled a request.

## Rotation, upgrades, and removal

- **Rotate Azure key:** replace `FOUNDRY_API_KEY` in `.env` or the injected environment, then restart the proxy. The local proxy key can stay the same.
- **Rotate proxy key:** empty `LITELLM_MASTER_KEY` and rerun setup with `--configure-only` to generate a fresh value; restart the proxy, relaunch wrapped Claude Code, and update Desktop's stored key. An environment override will take precedence over an edited file.
- **Change deployment/base/port:** edit local configuration, validate via `setup.py --configure-only`, restart the proxy, rerun billable smoke checks deliberately, and update Desktop's URL if necessary.
- **Upgrade LiteLLM:** deliberately change the version in `requirements.txt`, review release notes/advisories, rerun setup, and rerun offline plus live client checks. A direct pin is not a full reproducible environment.
- **Upgrade Nexus:** deliberately update `NEXUS_REVISION`, review the revision and lockfile, rerun setup, and validate `nexus.sh --help`. Do not use a moving revision in a customer release without review.
- **Remove:** stop the proxy and wrapped clients; disable the Desktop gateway through its UI. Delete local `.env`, `.venv`, and `.local` using your normal filesystem tools. The repo-local install did not change shell profiles or Claude settings; separately invoked Nexus commands may have their own cleanup requirements. Revoke any exposed Azure credentials in Azure rather than relying on file deletion.

## Intentionally absent production features

No shared authentication service, database, Redis, TLS termination, network exposure, automatic key rotation, Entra refresh, quotas/budgets, distributed tracing, fallback models, deployment provisioning, service manager, or supply-chain attestation is provided. These should be designed for the actual deployment, not inferred from a local demo.
