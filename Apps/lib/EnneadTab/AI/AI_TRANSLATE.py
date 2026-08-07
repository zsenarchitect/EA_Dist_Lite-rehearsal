#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Translation via the EnneadTab AI proxy at /api/ai/translate."""

import json

from EnneadTab import AUTH
from EnneadTab.AI._common import ENNEADTAB_URL, AIRequestError, post_json


def translate(input_text, target_language="cn",
              personality="professional architect, precise, concise, and creative"):
    """Translate text. Blocking auth (opens browser if needed). Empty string on failure."""
    token = AUTH.get_token_blocking()
    if not token:
        return ""
    url = "{}/api/ai/translate".format(ENNEADTAB_URL)
    payload = json.dumps({
        "text": input_text,
        "targetLanguage": target_language,
        "personality": personality,
    }, ensure_ascii=True)
    try:
        data = post_json(url, payload, token)
        return data.get("translation", "")
    except AIRequestError as e:
        if e.status_code == 401:
            AUTH.clear_token()
            token = AUTH.get_token_blocking()
            if not token:
                return ""
            return translate(input_text, target_language, personality)
        print("Translation API error: {}".format(e))
        return ""


def translate_multiple(input_texts, target_language="cn",
                       personality="professional architect, precise, concise, and creative, "
                                   "i will give you a list of item to translate, "
                                   "please translate them all in the same style and tone, "
                                   "you will return a list of translated words only, no marker formating, "
                                   "if the input contain both English and Chinese, "
                                   "please just focus on translating the English part and ignore Chinese part"):
    """Translate a list of texts at once. Returns {original: translated} dict."""
    input_joined = "\n".join([str(x).strip() for x in input_texts if str(x).strip()])
    result = translate(input_joined, target_language, personality)
    if not result:
        return {}
    result_list = result.split("\n")
    while len(result_list) < len(input_texts):
        result_list.append("")
    return {k: (v.strip() or k) for k, v in zip(input_texts, result_list)}
