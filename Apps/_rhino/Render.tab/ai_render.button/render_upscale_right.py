# -*- coding: utf-8 -*-

__title__ = "AiRenderUpscale"
__doc__ = "Upscale tool is being rebuilt - see in-app message for status."

# 2026-04-30: standalone upscaler dialog retired. The local Stable
# Diffusion pipeline (S:\\SD-Model + EA_AI_SCALER exe) is dead in
# production. A new server-side upscaler is being built into
# RenderPolisher; once live, "Upscale" will appear in AI Render's
# row context menu.
#
# This stub stays in place to handle toolbar-pinned-button orphaning -
# users with a custom Rhino toolbar item still bound to AiRenderUpscale
# get a polite "rebuild in progress" message instead of "Unknown
# command" errors.
#
# Plan: DEBUG/plans/2026-04-30-ai-render-fix-plan-v2.md (Phase C-now)
# Memory: project_upscale_replicate_renderpolisher.md
# Replaces 432 LOC of dead code with this 25-LOC shim. Net -407.

import Eto # pyright: ignore
from EnneadTab import LOG, ERROR_HANDLE


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def render_upscale():
    Eto.Forms.MessageBox.Show(
        "The Upscale tool is being rebuilt.\n\n"
        "The old local Stable Diffusion pipeline is retired. A new\n"
        "server-side upscaler is in development - it will appear in\n"
        "AI Render's row context menu when ready.\n\n"
        "For now, render at the highest resolution from the start\n"
        "if you need a large output.",
        "Upscale unavailable (rebuild in progress)",
        Eto.Forms.MessageBoxButtons.OK,
        Eto.Forms.MessageBoxType.Information)


if __name__ == "__main__":
    render_upscale()
