# -*- coding: utf-8 -*-
"""EnneadTab AI package.

Submodules (all proxied through enneadtab.com / ennead-ai.com):
- _common      Shared HTTP transport (.NET WebRequest + urllib fallback), AIRequestError
- AI_CHAT      Chat completions + prompt improvement + spell check
- AI_TRANSLATE Text translation
- AI_RENDER    Image/video render API + cloud Gallery + render-job queue + style-ref library

Two valid import styles, both supported:

    # Submodule (preferred for new code -- explicit about which surface):
    from EnneadTab.AI import AI_RENDER
    AI_RENDER.render_image_with_token(...)

    # Top-level (back-compat with the pre-package-split AI.py -- keeps existing
    # callers in QAQC_AI, translate_AI, keynote_assistant, BIM_Client,
    # text2script, ENGINE working unchanged):
    from EnneadTab import AI
    AI.chat(...)
    AI.translate(...)
    AI.AIRequestError
"""

# Back-compat re-exports -- DO NOT REMOVE without auditing every
# `from EnneadTab import AI` call site across Apps/_revit/, Apps/_rhino/,
# and Apps/lib/EnneadTab/. Removing these silently breaks ~7 buttons.

from EnneadTab.AI._common import (  # noqa: F401
    AIRequestError,
    ENNEADTAB_URL,
    RENDER_URL,
)

from EnneadTab.AI.AI_CHAT import (  # noqa: F401
    chat,
    chat_with_token,
    improve_prompt_with_token,
    spell_check_with_token,
)

from EnneadTab.AI.AI_TRANSLATE import (  # noqa: F401
    translate,
    translate_multiple,
)

from EnneadTab.AI.AI_RENDER import (  # noqa: F401
    # Image render
    render_image,
    render_image_with_token,
    get_render_presets,
    # Video render
    render_video_with_token,
    # Style-reference library + cache
    get_demo_style_images,
    get_or_cache_demo_style_image,
    prefetch_demo_style_images,
    # Saved prompts
    list_prompts_with_token,
    save_prompt_with_token,
    # Quota
    get_quota_with_token,
    # Cloud Gallery
    list_gallery_index_with_token,
    get_gallery_items_with_token,
    save_to_gallery_with_token,
    save_to_community_with_token,
    delete_gallery_item_with_token,
    # Local cache + filter helpers
    cache_dir,
    cache_size_bytes,
    clear_cache,
    cleanup_old_captures,
    fetch_gallery_index_async,
    fetch_full_item_async,
    filter_rows,
    fmt_bytes,
    fmt_elapsed,
    truncate_str,
    DATE_FILTERS,
    DEFAULT_DATE_FILTER,
    # Render job model + worker
    RenderJob,
    QueueWorker,
    KIND_IMAGE,
    KIND_VIDEO,
    STATUS_PENDING,
    STATUS_ACTIVE,
    STATUS_DONE,
    STATUS_FAILED,
    ACTIVE_CAP,
    count_inflight,
    can_enqueue,
    play_completion_sound,
)
