"""Visual tokens for NotificationHost toast cards.

macOS/iOS notification cues: translucent glass card, large uniform radius,
thin level-tinted border on all four sides (no accent bar - border-left
accents are a banned generic-AI UI tell, see repo CLAUDE.md) plus a subtle
neutral elevation shadow, tight stack gap.
"""

# Translucent glass card - not purple-gradient AI chrome. Window already sets
# WA_TranslucentBackground so this rgba alpha reads as real glass, not fake blur.
# Dark sophisticated grey (near-neutral, faint cool undertone - not blue,
# not warm) - was a blue-charcoal rgba(28, 33, 43, 230).
COLORS = {
    "card_bg": "rgba(39, 39, 42, 230)",
    "text": "#F2F4F8",
    "text_muted": "#A8B0C0",
    "button_bg": "#2A3344",
    "button_hover": "#3A4558",
    "button_text": "#F2F4F8",
    "icon": "#C5CBD6",
    "icon_hover": "#FFFFFF",
    "close_hover": "#E07070",
    "mute_hover": "#F0C14A",
    "shadow": "#000000",
}

LEVEL_ACCENT = {
    "info": "#3B82F6",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "error": "#EF4444",
}

DEFAULT_LEVEL = "info"
# Legacy / last-resort name. Prefer resolve_default_font_family() at runtime.
DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 13
# First installed wins — Variable/Aptos read cleaner than plain Segoe UI.
FONT_PREFERENCE = (
    "Segoe UI Variable Text",
    "Segoe UI Variable",
    "Aptos",
    "Bahnschrift",
    "Segoe UI",
    "Calibri",
)
_resolved_font_family = None
# Windows monochrome icon font (single-color glyphs, not color emoji).
ICON_FONT_FAMILY = "Segoe MDL2 Assets"
MAX_VISIBLE = 4
CARD_WIDTH = 360
ICON_COL_WIDTH = 34
CARD_RADIUS = 18
BODY_PAD_H = 18 + 8  # left body pad + gap before icon col
CARD_GAP = 8
SCREEN_EDGE_PAD = 20
# Room around the card so the drop shadow is not clipped.
SHADOW_PAD = 14
SHADOW_BLUR = 28
SHADOW_OFFSET_Y = 3
# Subtle neutral elevation shadow alpha (0-255) - depth only, no level tint.
# The level cue now lives in the card border instead (see LEVEL_BORDER_ALPHA).
SHADOW_ALPHA = 60
# Level-tinted, semi-opaque border alpha (0-255) - a thin border line around
# all four sides of the card carries the per-level color cue that the old
# ambient glow used to carry.
LEVEL_BORDER_ALPHA = 150
# Optional toast image/gif: full-bleed at card width, height follows aspect
# ratio uncapped (no max-height box).

# Thin bottom countdown bar (non-sticky cards only) - hints at time left
# before auto-dismiss. Range is 0-1000 for smooth animation precision.
COUNTDOWN_BAR_HEIGHT = 3
COUNTDOWN_RANGE_MAX = 1000

# Segoe MDL2 Assets codepoints (monochrome).
SYM_CLOSE = "\uE711"   # Cancel / X
SYM_COPY = "\uE8C8"    # Copy
SYM_MUTE = "\uE74F"    # Mute

# Durations (ms)
DEFAULT_STAY_MS = {
    "info": 5000,
    "success": 5000,
    "warning": 7000,
    "error": 9000,
}
SLIDE_MS = 420          # Restack, smooth deceleration
SLIDE_IN_MS = 420       # Smooth entrance, no bounce
SLIDE_OUT_MS = 480      # Smooth exit slide
FADE_MS = 480           # Fade paired with exit; also entrance fade-in
ENTER_OFFSET_X = 72     # Enter from off-screen left
EXIT_OFFSET_X = 90      # Exit toward left

# Sticky cards (payload["sticky"]) never auto-dismiss, so that one does not
# sit and compete for attention a persistent card fades to a low opacity
# after a quiet interval, then returns to full opacity on hover. Tune here.
STICKY_DIM_DELAY_MS = 10000   # idle time (no hover) before dimming
STICKY_DIM_OPACITY = 0.45     # semi-transparent resting opacity
STICKY_DIM_FADE_MS = 450      # dim / undim transition


def resolve_default_font_family():
    """Pick the best installed UI font from FONT_PREFERENCE (cached)."""
    global _resolved_font_family
    if _resolved_font_family:
        return _resolved_font_family
    try:
        from PyQt5.QtGui import QFontDatabase
        available = set(QFontDatabase().families())
        for name in FONT_PREFERENCE:
            if name in available:
                _resolved_font_family = name
                return _resolved_font_family
    except Exception:
        pass
    _resolved_font_family = DEFAULT_FONT_FAMILY
    return _resolved_font_family


def window_width():
    return CARD_WIDTH + (SHADOW_PAD * 2)


def body_max_width():
    """Text wrap width inside the card (excludes icon column)."""
    return CARD_WIDTH - ICON_COL_WIDTH - BODY_PAD_H - 8


CARD_STYLE = """
QFrame#ToastCard {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-top-left-radius: {radius}px;
    border-top-right-radius: {radius}px;
    border-bottom-left-radius: {bottom_radius}px;
    border-bottom-right-radius: {bottom_radius}px;
}}
QLabel#ToastTitle {{
    color: {text};
    background: transparent;
    font-family: "{font_family}";
    font-size: {title_font_size}pt;
    font-weight: 600;
}}
QLabel#ToastBody {{
    color: {body_color};
    background: transparent;
    font-family: "{font_family}";
    font-size: {font_size}pt;
}}
QLabel#ToastImage {{
    background: transparent;
    border: none;
}}
QPushButton#ActionBtn {{
    background-color: {button_bg};
    color: {button_text};
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    font-family: "{font_family}";
    font-size: 11pt;
}}
QPushButton#ActionBtn:hover {{
    background-color: {button_hover};
}}
QPushButton#IconBtn,
QPushButton#IconBtnClose,
QPushButton#IconBtnMute {{
    background: transparent;
    color: {icon};
    border: none;
    padding: 0px;
    font-family: "{icon_font}";
    font-size: 12pt;
}}
QPushButton#IconBtn:hover {{
    color: {icon_hover};
}}
QPushButton#IconBtnClose:hover {{
    color: {close_hover};
}}
QPushButton#IconBtnMute:hover {{
    color: {mute_hover};
}}
QProgressBar#CountdownBar {{
    background: transparent;
    border: none;
}}
QProgressBar#CountdownBar::chunk {{
    background-color: {countdown_color};
}}
"""


def level_border_color(level):
    """rgba(...) CSS string for the level-tinted, thin all-sides card border.

    Replaces the old ambient shadow glow as the per-level color cue.
    """
    from PyQt5.QtGui import QColor
    hex_accent = LEVEL_ACCENT.get(level, LEVEL_ACCENT[DEFAULT_LEVEL])
    color = QColor(hex_accent)
    color.setAlpha(LEVEL_BORDER_ALPHA)
    return "rgba({}, {}, {}, {})".format(
        color.red(), color.green(), color.blue(), color.alpha()
    )


def neutral_shadow_color():
    """QColor for the subtle, level-neutral elevation drop shadow."""
    from PyQt5.QtGui import QColor
    color = QColor(COLORS["shadow"])
    color.setAlpha(SHADOW_ALPHA)
    return color


def build_card_stylesheet(level="info", font_family=None, font_size=None,
                           has_title=False, has_countdown_bar=False):
    resolved_font_size = font_size or DEFAULT_FONT_SIZE
    body_color = COLORS["text_muted"] if has_title else COLORS["text"]
    countdown_color = LEVEL_ACCENT.get(level, LEVEL_ACCENT[DEFAULT_LEVEL])
    # The countdown bar is a plain rectangular QProgressBar flush against the
    # card's bottom edge - rounding the card's bottom corners while the bar
    # stays square makes the bar visibly overflow/clip past the curve at
    # both bottom corners. Square the bottom corners off instead whenever
    # the bar is present so it sits flush without any mismatch to hide.
    bottom_radius = 0 if has_countdown_bar else CARD_RADIUS
    return CARD_STYLE.format(
        card_bg=COLORS["card_bg"],
        card_border=level_border_color(level),
        radius=CARD_RADIUS,
        bottom_radius=bottom_radius,
        text=COLORS["text"],
        body_color=body_color,
        button_bg=COLORS["button_bg"],
        button_hover=COLORS["button_hover"],
        button_text=COLORS["button_text"],
        icon=COLORS["icon"],
        icon_hover=COLORS["icon_hover"],
        close_hover=COLORS["close_hover"],
        mute_hover=COLORS["mute_hover"],
        countdown_color=countdown_color,
        font_family=font_family or resolve_default_font_family(),
        font_size=resolved_font_size,
        title_font_size=resolved_font_size + 1,
        icon_font=ICON_FONT_FAMILY,
    )


def stay_ms_for_level(level):
    return DEFAULT_STAY_MS.get(level, DEFAULT_STAY_MS[DEFAULT_LEVEL])
