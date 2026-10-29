#!/usr/bin/env python3
"""Exercise the proxy's Anthropic API; upstream inference is billable."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from runtime import ROUTES, load_config


def request(values, path, payload=None, token=None):
    headers = {"Authorization": "Bearer " + (token if token is not None else values["LITELLM_MASTER_KEY"]),
               "Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(values["LITELLM_PROXY_BASE_URL"].rstrip("/") + path, data=body, headers=headers)
    return urlopen(req, timeout=180)


def check_stream(response):
    events = []
    for raw in response:
        line = raw.decode().strip()
        if line.startswith("data: "):
            data = json.loads(line[6:])
            if data.get("type") == "error":
                raise ValueError("Streaming response contained an error event")
            events.append(data.get("type"))
    if not {"message_start", "content_block_delta", "message_stop"}.issubset(events):
        raise ValueError("Missing expected Anthropic stream events")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-billable", action="store_true", required=True,
                        help="Consent to seven inference requests: three text, three streaming, one forced tool call")
    args = parser.parse_args()
    values = load_config()
    try:
        with request(values, "/v1/models", token="invalid-local-proxy-token"):
            raise ValueError("Proxy accepted an invalid token")
    except HTTPError as error:
        # A master-key-only proxy (no database/virtual keys) rejects unknown keys with 400.
        if error.code not in (400, 401, 403):
            raise ValueError("Unexpected status checking authentication") from None
    print("PASS: invalid proxy credentials rejected")
    with request(values, "/v1/models") as response:
        models = {item["id"] for item in json.load(response)["data"]}
    if not set(ROUTES.values()).issubset(models):
        raise ValueError("Not all configured routes are listed")
    print("PASS: model discovery")
    for route in ROUTES.values():
        payload = {"model": route, "max_tokens": 1024,
                   "messages": [{"role": "user", "content": "Reply with the single word pong."}]}
        with request(values, "/v1/messages", payload) as response:
            result = json.load(response)
        if result.get("type") != "message" or not any(
                block.get("type") == "text" and block.get("text") for block in result.get("content", [])):
            raise ValueError("Missing Anthropic text response")
        print(f"PASS: {route} text response")
        with request(values, "/v1/messages", {**payload, "stream": True}) as response:
            check_stream(response)
        print(f"PASS: {route} streaming")
    payload = {
        "model": ROUTES["SONNET"], "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Call report_status with status ok."}],
        "tools": [{"name": "report_status", "description": "Report a status; no action is executed.",
                   "input_schema": {"type": "object", "properties": {"status": {"type": "string"}},
                                    "required": ["status"]}}],
        "tool_choice": {"type": "tool", "name": "report_status"},
    }
    with request(values, "/v1/messages", payload) as response:
        result = json.load(response)
    if not any(block.get("type") == "tool_use" and block.get("name") == "report_status"
               and isinstance(block.get("input"), dict) for block in result.get("content", [])):
        raise ValueError("Model did not return the forced tool call")
    print("PASS: Sonnet-route tool use (no tool executed)")
    print("Smoke tests passed. This does not establish full Claude feature compatibility.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HTTPError as error:
        print(f"FAIL: HTTP {error.code}. Inspect the proxy locally; response body withheld to protect credentials.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, TypeError, URLError, OSError):
        print("FAIL: configuration, connection, or response validation error. See README.md; private details withheld.", file=sys.stderr)
        sys.exit(1)
