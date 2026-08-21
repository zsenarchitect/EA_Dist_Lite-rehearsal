#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Client for EnneadTab-AI-Gate's OpenAI-compatible /v1/chat/completions endpoint.

senzhang-todo #2322: "Build an IronPython 2.7 gateway client shim ... so Revit/Rhino
tools call the gateway without an SDK." 'OpenAI-compatible' is a WIRE PROTOCOL, not an
SDK -- one uniform POST body/response shape can serve Next.js, CPython, and IP2.7 alike.

This is a THIN wrapper, not a new transport. `EnneadTab.AI._common.post_json` already
solves the two real IronPython hazards (TLS 1.2 must be forced before any HTTPS call;
.NET HttpClient is async-only and deadlock-prone under Revit's single-thread apartment,
so use synchronous HttpWebRequest instead) for every other AI endpoint in this package
(AI_CHAT.py, AI_RENDER.py, AI_TRANSLATE.py). Do not re-solve those hazards here --
reuse post_json, per this package's own "prime directive: REUSE, don't reinvent"
(see AI_CHAT.py's module docstring).

Caller-provided credential: every existing post_json call site in this package always
passes a real bearer token (never empty) -- see improve_prompt_with_token's explicit
`if not token: raise AIRequestError(...)` guard in AI_CHAT.py. This module follows the
same convention and requires a `virtual_key`, even though the Gate's
/v1/chat/completions does not enforce it yet (Phase 1, EnneadTab-AI-Gate#2, still lands
Phase 2 -- wiring /v1/chat/completions to require a virtual key -- separately). Once
that lands, this call site needs zero changes: the header is already being sent.
"""

import json

from EnneadTab.AI._common import AIRequestError, post_json, to_unicode


def chat_completions(gate_base_url, virtual_key, model, messages, max_tokens=None, timeout_ms=60000):
    """POST {gate_base_url}/v1/chat/completions with an OpenAI-shaped body.

    gate_base_url: e.g. "http://localhost:8787" (local dev) or the deployed Gate's
        origin once EnneadTab-AI-Gate is live. No trailing slash assumed either way --
        this strips one if present.
    virtual_key: the egk_live_... key from EnneadTab-AI-Gate's /v1/keys/issue (contract:
        senzhang-todo docs/plans/2026-07-27-ai-gate-federated-key-issuance-contract.md).
        Required -- see module docstring for why this doesn't silently accept None.
    model: e.g. "gemini-2.5-flash" (A.1) -- see the Gate's own adapter registry for what
        it currently routes.
    messages: list of {"role": ..., "content": ...} dicts, OpenAI chat-message shape.

    Returns the assistant's reply text (choices[0].message.content). Raises
    AIRequestError on any transport or upstream failure -- same exception type every
    other AI_* module in this package raises, so existing 401-retry / error-display
    call sites can catch it identically.
    """
    if not virtual_key:
        raise AIRequestError("No Gate virtual key provided.", status_code=401)
    if not gate_base_url:
        raise AIRequestError("No Gate base URL provided.")

    base = gate_base_url.rstrip("/")
    url = "{}/v1/chat/completions".format(base)

    safe_messages = []
    for m in (messages or []):
        if isinstance(m, dict) and "content" in m:
            m = dict(m)
            m["content"] = to_unicode(m.get("content"))
        safe_messages.append(m)

    body = {"model": model, "messages": safe_messages}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    payload = json.dumps(body, ensure_ascii=True)
    data = post_json(url, payload, virtual_key, timeout_ms=timeout_ms)

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AIRequestError("Gate response missing choices[0].message.content: {}".format(data))
