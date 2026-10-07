#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Direct-to-Gate translation, bypassing Home's /api/ai/translate proxy.

senzhang-todo #5939 track (1): the first real wiring of AI_GATE.chat_completions()
(#2322) into a live tool. Home's own /api/ai/translate route builds the system prompt
server-side from {text, targetLanguage, personality} -- bypassing Home means that prompt
construction moves here, ported verbatim, so translation behavior does not silently change.

Fails via AIRequestError on ANY failure (assertion exchange, key issuance, or the
completion call itself) -- AI_TRANSLATE.translate() catches this and falls through to its
existing, unmodified direct-Home code path.
"""

from EnneadTab.AI._common import ENNEADTAB_URL, AIRequestError, post_json, to_unicode
from EnneadTab.AI.AI_GATE import chat_completions

GATE_URL = "https://enneadtab-ai-gate.vercel.app"
GEMINI_MODEL = "gemini-2.5-flash"

# Explicit, tighter per-call timeouts for this 3-call Gate chain (assertion exchange +
# key issuance + completion). Left at their defaults (post_json=120000ms x2,
# chat_completions=60000ms) the worst case before falling through to the Home fallback
# is ~300s -- roughly 3.5x the pre-existing single Home-only call. These three values
# keep the worst-case total (15s + 15s + 30s = 60s) at about half of the original
# ~120s single-call baseline, so a user is never worse off waiting for the Gate to
# fail than they were before this path existed.
ASSERTION_TIMEOUT_MS = 15000
KEY_ISSUE_TIMEOUT_MS = 15000
COMPLETION_TIMEOUT_MS = 30000

# Both str (IronPython 2.7 byte string / CPython 3 str) and type(u"") (IronPython 2.7
# unicode / CPython 3 str again) so this works identically on both runtimes without
# ever naming `unicode` directly -- that name does not exist under CPython 3 and would
# NameError this module the moment it is imported there (this file's test harness runs
# under CPython 3 on this Mac; production is IronPython 2.7 inside Revit).
_STRING_TYPES = (str, type(u""))


def _get_virtual_key(desktop_token):
    """Exchange a desktop Bearer token for a Gate virtual key. Raises AIRequestError."""
    assertion_url = "{}/api/ai-gate/assertion".format(ENNEADTAB_URL)
    assertion_data = post_json(assertion_url, "{}", desktop_token, timeout_ms=ASSERTION_TIMEOUT_MS)
    if not isinstance(assertion_data, dict):
        raise AIRequestError("Unexpected non-object response from Home's /api/ai-gate/assertion")
    assertion = assertion_data.get("assertion")
    if not assertion:
        raise AIRequestError("No assertion returned from Home's /api/ai-gate/assertion")

    key_url = "{}/v1/keys/issue".format(GATE_URL)
    key_data = post_json(key_url, "{}", assertion, timeout_ms=KEY_ISSUE_TIMEOUT_MS)
    if not isinstance(key_data, dict):
        raise AIRequestError("Unexpected non-object response from the Gate's /v1/keys/issue")
    virtual_key = key_data.get("virtual_key")
    if not virtual_key:
        raise AIRequestError("No virtual_key returned from the Gate's /v1/keys/issue")
    return virtual_key


def _build_system_prompt(target_language, personality):
    """Ported verbatim from EnneadTab-Home/app/api/ai/translate/route.ts so translation
    behavior is identical whether the call goes through Home or directly to the Gate."""
    if personality:
        return (
            u"You are a translator with the following personality: {}. "
            u"Translate the given text to {}. Return ONLY the translated text, "
            u"no explanations or extra commentary."
        ).format(personality, target_language)
    return (
        u"You are a professional translator. Translate the given text to {}. "
        u"Return ONLY the translated text, no explanations or extra commentary."
    ).format(target_language)


def get_translation_via_gate(desktop_token, input_text, target_language, personality):
    """Returns the translated text, or raises AIRequestError on any failure."""
    virtual_key = _get_virtual_key(desktop_token)
    system_prompt = _build_system_prompt(target_language, personality)
    messages = [
        {"role": "system", "content": to_unicode(system_prompt)},
        {"role": "user", "content": to_unicode(input_text)},
    ]
    result = chat_completions(GATE_URL, virtual_key, GEMINI_MODEL, messages, timeout_ms=COMPLETION_TIMEOUT_MS)

    # Guard: choices[0].message.content is a legal OpenAI-compat response field that can
    # come back null (e.g. finish_reason="length", a safety block) or as a list of
    # content parts rather than a plain string -- chat_completions() returns it
    # verbatim with no validation. Letting either shape through here means the caller
    # (AI_TRANSLATE.translate()) returns it as if it were a real translation, and the
    # live consumer (additional_util.py) then crashes concatenating it into a string.
    # Raising AIRequestError instead sends this down the same existing fallback path as
    # every other Gate failure. Message carries only the returned TYPE, never the
    # content itself, per this plan's "no translation content in logs" constraint.
    if not result or not isinstance(result, _STRING_TYPES):
        raise AIRequestError(
            "Gate returned a non-string translation result (type: {})".format(type(result).__name__)
        )
    return result
