#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Chat / prompt-improvement / spell-check endpoints.

- chat / chat_with_token  ->  enneadtab.com/api/ai/desktop-chat (general LLM)
- improve_prompt_with_token ->  ennead-ai.com/api/improve-prompt (scene-aware,
                                  language-preserving, action=improve|summarize)
- spell_check_with_token  ->  ennead-ai.com/api/spell-check (intent-preserving,
                                  content-moderated)

The improve_prompt and spell_check endpoints live on RenderPolisher
(ennead-ai.com) and have tuned, frequently-updated system prompts. Reuse
them -- do not roll our own LLM call here (prime directive: REUSE, don't
reinvent).
"""

import json

from EnneadTab import AUTH
from EnneadTab.AI._common import (
    ENNEADTAB_URL, RENDER_URL, AIRequestError, post_json, to_unicode,
)


def chat_with_token(token, messages, temperature=None, json_mode=False):
    """Chat with a pre-obtained token. Use from IronPython UIs that handle auth themselves."""
    url = "{}/api/ai/desktop-chat".format(ENNEADTAB_URL)
    safe_messages = []
    for m in (messages or []):
        if isinstance(m, dict) and "content" in m:
            m = dict(m)
            m["content"] = to_unicode(m.get("content"))
        safe_messages.append(m)
    body = {"messages": safe_messages}
    if temperature is not None:
        body["temperature"] = temperature
    if json_mode:
        body["jsonMode"] = True
    payload = json.dumps(body, ensure_ascii=True)
    data = post_json(url, payload, token)
    return data.get("content", "")


def chat(messages, system_prompt=None, temperature=None):
    """Chat with blocking auth. Empty string on failure."""
    token = AUTH.get_token_blocking()
    if not token:
        return ""
    if system_prompt:
        messages = [{"role": "system", "content": system_prompt}] + messages
    try:
        return chat_with_token(token, messages, temperature)
    except AIRequestError as e:
        if e.status_code == 401:
            AUTH.clear_token()
            token = AUTH.get_token_blocking()
            if not token:
                return ""
            return chat_with_token(token, messages, temperature)
        print("Chat API error: {}".format(e))
        return ""


def improve_prompt_with_token(token, prompt, mode="image", action="improve",
                              is_interior=False, has_last_frame=False,
                              has_mask=False, timeout_ms=60000):
    """Improve (lengthen) or summarize (shorten) a render prompt.

    action="improve": expands ~2x with quality guidance suffix.
    action="summarize": condenses to ~0.75x while preserving key terms.
    is_interior=True: uses interior-tuned system prompt.
    """
    if not token:
        raise AIRequestError("No auth token provided.", status_code=401)
    url = "{}/api/improve-prompt".format(RENDER_URL)
    payload = json.dumps({
        "prompt": to_unicode(prompt),
        "mode": mode,
        "action": action,
        "isInterior": bool(is_interior),
        "hasLastFrame": bool(has_last_frame),
        "hasMask": bool(has_mask),
    }, ensure_ascii=True)
    data = post_json(url, payload, token, timeout_ms=timeout_ms)
    if not data.get("ok"):
        # Propagate status_code so caller's 401-retry path fires when the
        # server bundles auth errors into the response body (Round 3 P2-6).
        raise AIRequestError(
            data.get("error") or "improve-prompt failed",
            status_code=data.get("statusCode"))
    out = data.get("improvedPrompt") or ""
    if not out:
        raise AIRequestError("improve-prompt returned empty result")
    return out


def spell_check_with_token(token, prompt, timeout_ms=60000):
    """Fix spelling & grammar while preserving intent."""
    if not token:
        raise AIRequestError("No auth token provided.", status_code=401)
    url = "{}/api/spell-check".format(RENDER_URL)
    payload = json.dumps({"prompt": to_unicode(prompt)}, ensure_ascii=True)
    data = post_json(url, payload, token, timeout_ms=timeout_ms)
    if not data.get("ok"):
        raise AIRequestError(
            data.get("error") or "spell-check failed",
            status_code=data.get("statusCode"))
    out = data.get("correctedPrompt") or ""
    if not out:
        raise AIRequestError("spell-check returned empty result")
    return out
