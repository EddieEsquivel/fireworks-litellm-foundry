"""Proxy hook: drop reasoning fields from replayed history before upstream calls.

Anthropic Messages clients such as Claude Code replay assistant thinking blocks
in every follow-up request (for example tool-result turns). LiteLLM translates
those blocks into OpenAI-style reasoning fields on the assistant history, and
some OpenAI-compatible upstreams (Fireworks deployments on Microsoft Foundry at
the time of testing) reject those fields with `invalid_payload`.

This hook removes reasoning content and thinking blocks from *historical*
assistant messages before the request leaves the proxy, which restores tool
round-trips. It deliberately does not touch live generation: a reasoning model
still produces reasoning, and clients still receive translated thinking blocks
for the current turn. Stripping replayed reasoning is a documented compatibility
choice, not an attempt to make the upstream a native Claude implementation.

This only exists because Foundry's OpenAI v1 surface is not Anthropic-native.
If Anthropic-native routing is available for your deployment, prefer it and
remove this hook.
"""

import copy

from litellm.integrations.custom_logger import CustomLogger


class ReasoningHistoryHook(CustomLogger):
    """Strip reasoning fields from replayed assistant history."""

    def _clean_message(self, message):
        candidate = copy.deepcopy(message)
        stripped = False
        for field in ("reasoning_content", "thinking_blocks", "reasoning"):
            if field in candidate:
                candidate.pop(field)
                stripped = True
        content = candidate.get("content")
        if isinstance(content, list):
            filtered = [block for block in content
                       if not (isinstance(block, dict)
                               and block.get("type") in ("thinking", "redacted_thinking"))]
            if len(filtered) != len(content):
                candidate["content"] = filtered
                stripped = True
        return candidate if stripped else message

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if call_type not in ("acompletion", "completion", "anthropic_messages"):
            return data
        messages = data.get("messages")
        if not isinstance(messages, list):
            return data
        new_messages = []
        changed = False
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "assistant":
                cleaned = self._clean_message(message)
                if cleaned is not message:
                    changed = True
                    new_messages.append(cleaned)
                    continue
            new_messages.append(message)
        if changed:
            data["messages"] = new_messages
        return data


proxy_handler_instance = ReasoningHistoryHook()
