"""Visual tokens for NotificationHost toast cards.

macOS/iOS notification cues: translucent glass card, large uniform radius,
level-tinted ambient glow (no accent bar - border-left accents are a banned
generic-AI UI tell, see repo CLAUDE.md), tight stack gap.
"""

# Translucent glass card - not purple-gradient AI chrome. Window already sets
# WA_TranslucentBackground so this rgba alpha reads as real glass, not fake blur.
COLORS = {
    "card_bg": "rgba(28, 33, 43, 230)",
    "card_border": "rgba(255, 255, 255, 20)",
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
# Room around the card so the drop shadow/glow is not clipped.
SHADOW_PAD = 14
SHADOW_BLUR = 36
SHADOW_OFFSET_Y = 3
# Level-tinted glow alpha (0-255). Neutral shadow color no longer used.
SHADOW_GLOW_ALPHA = 100
# Optional toast image/gif: full-bleed at card width, height follows aspect
# ratio uncapped (no max-height box).

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
    border-radius: {radius}px;
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
"""


def level_glow_color(level):
    """QColor-ready (r, g, b, a) for the level-tinted ambient shadow glow."""
    from PyQt5.QtGui import QColor
    hex_accent = LEVEL_ACCENT.get(level, LEVEL_ACCENT[DEFAULT_LEVEL])
    color = QColor(hex_accent)
    color.setAlpha(SHADOW_GLOW_ALPHA)
    return color


def build_card_stylesheet(level="info", font_family=None, font_size=None,
                           has_title=False):
    resolved_font_size = font_size or DEFAULT_FONT_SIZE
    body_color = COLORS["text_muted"] if has_title else COLORS["text"]
    return CARD_STYLE.format(
        card_bg=COLORS["card_bg"],
        card_border=COLORS["card_border"],
        radius=CARD_RADIUS,
        text=COLORS["text"],
        body_color=body_color,
        button_bg=COLORS["button_bg"],
        button_hover=COLORS["button_hover"],
        button_text=COLORS["button_text"],
        icon=COLORS["icon"],
        icon_hover=COLORS["icon_hover"],
        close_hover=COLORS["close_hover"],
        mute_hover=COLORS["mute_hover"],
        font_family=font_family or resolve_default_font_family(),
        font_size=resolved_font_size,
        title_font_size=resolved_font_size + 1,
        icon_font=ICON_FONT_FAMILY,
    )


def stay_ms_for_level(level):
    return DEFAULT_STAY_MS.get(level, DEFAULT_STAY_MS[DEFAULT_LEVEL])
