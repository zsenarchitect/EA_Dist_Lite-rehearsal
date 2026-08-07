import os
import io
import random
import json

import webbrowser


import ENVIRONMENT

# Try to import FOLDER, with a fallback mechanism
FOLDER = None
try:
    import FOLDER
    # Test if the function works
    try:
        test_result = FOLDER.get_local_dump_folder_file("test")
    except:
        FOLDER = None
except Exception as e:
    FOLDER = None

# If FOLDER import failed, create fallback
if FOLDER is None:
    # Provide fallback functions that use ENVIRONMENT directly
    class FOLDER_FALLBACK:
        @staticmethod
        def get_local_dump_folder_file(file_name):
            return os.path.join(ENVIRONMENT.DUMP_FOLDER, file_name)
        
        @staticmethod
        def get_shared_dump_folder_file(file_name):
            return os.path.join(ENVIRONMENT.SHARED_DUMP_FOLDER, file_name)
    
    FOLDER = FOLDER_FALLBACK()

import TIME 
import IMAGE


FUNCS = """
<script>
function sample_func(btn) {
  alert(btn.innerText);
  prompt("Type anything:");
  confirm("Do you want to continue?");
}

function highlightSearch() {
  var input, filter, body, p, h1, h2, li, i, txtValue;
  input = document.getElementById('searchBox');
  filter = input.value.toLowerCase();
  body = document.getElementsByTagName('body')[0];
  
  // Highlight paragraphs
  p = body.getElementsByTagName('p');
  for (i = 0; i < p.length; i++) {
    txtValue = p[i].textContent || p[i].innerText;
    if (filter === "") {
      p[i].style.backgroundColor = '';
    } else if (txtValue.toLowerCase().indexOf(filter) > -1) {
      p[i].style.backgroundColor = 'lightgreen';
    } else {
      p[i].style.backgroundColor = '';
    }
  }

  // Highlight titles
  h1 = body.getElementsByTagName('h1');
  for (i = 0; i < h1.length; i++) {
    txtValue = h1[i].textContent || h1[i].innerText;
    if (filter === "") {
      h1[i].style.backgroundColor = '';
    } else if (txtValue.toLowerCase().indexOf(filter) > -1) {
      h1[i].style.backgroundColor = 'lightgreen';
    } else {
      h1[i].style.backgroundColor = '';
    }
  }
  
  h2 = body.getElementsByTagName('h2');
  for (i = 0; i < h2.length; i++) {
    txtValue = h2[i].textContent || h2[i].innerText;
    if (filter === "") {
      h2[i].style.backgroundColor = '';
    } else if (txtValue.toLowerCase().indexOf(filter) > -1) {
      h2[i].style.backgroundColor = 'lightgreen';
    } else {
      h2[i].style.backgroundColor = '';
    }
  }

  // Highlight list items
  li = body.getElementsByTagName('li');
  for (i = 0; i < li.length; i++) {
    txtValue = li[i].textContent || li[i].innerText;
    if (filter === "") {
      li[i].style.backgroundColor = '';
    } else if (txtValue.toLowerCase().indexOf(filter) > -1) {
      li[i].style.backgroundColor = 'lightgreen';
    } else {
      li[i].style.backgroundColor = '';
    }
  }
}

function copyErrorCard(btn) {
    const card = btn.closest('.error-card');
    const text = card.textContent.replace('Copy', '').trim();
    navigator.clipboard.writeText(text).then(() => {
        btn.innerHTML = 'Copied!';
        setTimeout(() => {
            btn.innerHTML = 'Copy';
        }, 2000);
    });
}

// Mouse tracking and logo animation system
document.addEventListener('DOMContentLoaded', function() {
    // Setup floating logo animation
    const floatingLogoContainer = document.createElement('div');
    floatingLogoContainer.id = 'floating-logo-container';
    document.body.appendChild(floatingLogoContainer);
    
    const floatingLogo = document.createElement('img');
    floatingLogo.id = 'floating-logo';
    floatingLogo.src = document.querySelector('img[src*="logo_outline_white.png"]').src;
    floatingLogo.height = 80;
    floatingLogoContainer.appendChild(floatingLogo);
    
    // Variables for tracking mouse and animation
    let mouseX = 0, mouseY = 0;
    let logoX = window.innerWidth / 2;
    let logoY = window.innerHeight / 2;
    let prevLogoX = logoX;
    let prevLogoY = logoY;
    let angle = 0;
    let targetAngle = 0;
    let lastMoveTime = Date.now();
    let isRotatingToUpright = false;
    
    // Track mouse movement
    document.addEventListener('mousemove', function(e) {
        mouseX = e.pageX;
        mouseY = e.pageY;
    });
    
    // Animation function
    function updateLogoPosition() {
        // Store previous position for direction calculation
        prevLogoX = logoX;
        prevLogoY = logoY;
        
        // Calculate new position with easing for delay effect
        logoX += (mouseX - logoX) * 0.08;
        logoY += (mouseY - logoY) * 0.08;
        
        // Calculate direction of movement
        const dx = logoX - prevLogoX;
        const dy = logoY - prevLogoY;
        
        // Check if there's significant movement
        if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
            targetAngle = Math.atan2(dy, dx) * (180 / Math.PI);
            lastMoveTime = Date.now();
            isRotatingToUpright = false;
        } else {
            // If no movement for 0.5 seconds, start rotating back to upright
            const currentTime = Date.now();
            if (currentTime - lastMoveTime > 500 && !isRotatingToUpright) {
                isRotatingToUpright = true;
                targetAngle = 0; // Upright orientation
            }
        }
        
        // Smoothly interpolate current angle to target angle
        const rotationSpeed = isRotatingToUpright ? 0.03 : 0.2; // Slower rotation when returning to upright
        angle += (targetAngle - angle) * rotationSpeed;
        
        // Apply position and rotation transform
        floatingLogo.style.transform = `translate(${logoX - 40}px, ${logoY - 40}px) rotate(${angle}deg)`;
        
        // Continue animation loop
        requestAnimationFrame(updateLogoPosition);
    }
    
    // Start animation
    updateLogoPosition();
});

// Rotating message system
let currentMessageIndex = 0;
const rotationInterval = 6000; 

function rotateMessages() {
    const footer = document.querySelector('.floating-footer');
    if (!footer) return;
    
    const messages = JSON.parse(footer.dataset.messages);
    
    // Remove old animation class
    footer.classList.remove('message-animate');
    
    // Update content
    currentMessageIndex = (currentMessageIndex + 1) % messages.length;
    footer.innerHTML = messages[currentMessageIndex];
    
    // Force a reflow to restart animation
    void footer.offsetWidth;
    
    // Add animation class
    footer.classList.add('message-animate');
}

// Start rotation when document is loaded
document.addEventListener('DOMContentLoaded', function() {
    const footer = document.querySelector('.floating-footer');
    if (footer) {
        // Show first message immediately
        const messages = JSON.parse(footer.dataset.messages);
        footer.innerHTML = messages[0];
        footer.classList.add('message-animate');
        
        // Start rotation after first animation
        setInterval(rotateMessages, rotationInterval);
    }
});

// Add format method to String prototype if not exists
if (!String.prototype.format) {
    String.prototype.format = function() {
        const args = arguments;
        return this.replace(/{(\\d+)}/g, function(match, number) {
            return typeof args[number] != 'undefined' ? args[number] : match;
        });
    };
}
</script>
"""

"""
EnneadTab Output Module

A sophisticated output management system for EnneadTab that provides HTML-based reporting and console output capabilities.
This module handles the formatting, styling, and display of output content through a singleton Output class.

Key Features:
    - HTML report generation with modern styling and interactive features
    - Search functionality within output content
    - Error highlighting and formatting
    - Support for different text styles (titles, subtitles, body text)
    - Copy functionality for error messages
    - Responsive design with animations
    - Environment-aware output handling (Revit/Rhino/Terminal)

Note:
    The module uses a singleton pattern to ensure consistent output handling across the application.
"""


# Sanitize all footer messages
def sanitize_message(msg):
    # Convert to string and replace quotes with HTML entities
    return str(msg).replace('"', '&quot;').replace("'", '&#39;')
    
class Style:
    """Style constants for output formatting.
    
    Defines the available text styles for output content:
        MainBody: Standard paragraph text
        Title: Main headings (h1)
        Subtitle: Secondary headings (h2)
        Footnote: Small text for additional information
    """
    MainBody = "p"
    Title = "h1"
    Subtitle = "h2"
    SubSubtitle = "h3"
    Footnote = "foot_note"
    Link = "custom_link"


# ---------------------------------------------------------------------------
# Output HTML theming
# ---------------------------------------------------------------------------
# Each theme is a flat dict of semantic tokens. Token keys (snake_case) are
# emitted as CSS custom properties on :root (`--token-name`) and referenced
# from the stylesheet via `var(--token-name)`. To add a theme, add a new entry
# below with the same key set so every var() resolves.

# IronPython 2.7 / CPython 3 string-type compat. json.load() returns unicode
# under IronPython 2.7, so a plain isinstance(..., str) check silently drops
# every value loaded from disk.
try:
    _STRING_TYPES = basestring  # noqa: F821 - Py2 only
except NameError:
    _STRING_TYPES = str


THEME_TOKEN_KEYS = (
    "surface",            # page background
    "text_primary",       # body text / paragraphs / li
    "text_muted",         # subdued text
    "heading_primary",    # h1 / strong headings / list items
    "heading_secondary",  # h2 / h3 / footnotes
    "link",               # link color
    "link_hover",         # link hover color
    "footer_muted",       # floating footer text
    "error_surface",      # error card background
    "error_border",       # error card left border
    "error_text",         # error card text + copy button text
    "accent",             # copy button background, decorative accent
    "accent_strong",      # copy button hover, strong accent
    "logo_glow",          # rgba() drop-shadow color around floating logo
    "card_hover_shadow",  # rgba() shadow for hovered error card
    "font_family",        # body font stack
)

THEMES = {
    # Original warm browns - kept for users who liked the EnneadTab look.
    "classic": {
        "surface": "#2B1C10",
        "text_primary": "#F4E1D2",
        "text_muted": "#987284",
        "heading_primary": "#E1D4C1",
        "heading_secondary": "#987284",
        "link": "white",
        "link_hover": "#A9B8C2",
        "footer_muted": "#b89eab",
        "error_surface": "#6E493A",
        "error_border": "#987284",
        "error_text": "#F4E1D2",
        "accent": "#987284",
        "accent_strong": "#E1D4C1",
        "logo_glow": "rgba(152,114,132,0.5)",
        "card_hover_shadow": "rgba(152,114,132,0.15)",
        "font_family": "Helvetica, Arial, sans-serif",
    },
    # VSCode-inspired: dark grey surface, neutral grey info text, dark orange
    # errors. This is the new default per user request.
    "console_dark": {
        "surface": "#1e1e1e",
        "text_primary": "#cccccc",
        "text_muted": "#8a8a8a",
        "heading_primary": "#e8e8e8",
        "heading_secondary": "#9cdcfe",
        "link": "#4ec9b0",
        "link_hover": "#dcdcaa",
        "footer_muted": "#808080",
        "error_surface": "#5c2e0f",
        "error_border": "#d97706",
        "error_text": "#fed7aa",
        "accent": "#d97706",
        "accent_strong": "#fbbf24",
        "logo_glow": "rgba(217,119,6,0.45)",
        "card_hover_shadow": "rgba(217,119,6,0.18)",
        "font_family": "Consolas, 'Courier New', monospace",
    },
    # Neutral slate option - softer than console_dark, no syntax-highlight
    # accent colors. Good if console_dark feels too saturated.
    "slate": {
        "surface": "#2a2d34",
        "text_primary": "#d8dee9",
        "text_muted": "#9aa3b2",
        "heading_primary": "#eceff4",
        "heading_secondary": "#88c0d0",
        "link": "#a3be8c",
        "link_hover": "#ebcb8b",
        "footer_muted": "#7a8090",
        "error_surface": "#5a2a1c",
        "error_border": "#e07a3f",
        "error_text": "#f4d6c1",
        "accent": "#e07a3f",
        "accent_strong": "#f0a060",
        "logo_glow": "rgba(224,122,63,0.45)",
        "card_hover_shadow": "rgba(224,122,63,0.18)",
        "font_family": "'Segoe UI', Helvetica, Arial, sans-serif",
    },
}

DEFAULT_THEME_NAME = "console_dark"

# Preset keys available for set_theme(), CONFIG "output_html_theme", and
# plot(theme=...).  "classic" = original browns; "console_dark" = default
# grey + dark-orange errors; "slate" = neutral slate alternative.
THEME_NAMES = tuple(sorted(THEMES.keys()))


# ---------------------------------------------------------------------------
# Event -> Theme contract
# ---------------------------------------------------------------------------
# Scripts should NOT hard-code a theme name. Instead they call
# `plot(event="error")` / `plot(event="tip")` etc., and OUTPUT.py picks the
# right preset. This gives one place to retune which color "errors" or "tips"
# wear without grepping every pushbutton.
#
# To rebind without editing source, set CONFIG.get_setting(
# "output_event_theme_map", { ... }) at the user level - it merges over the
# defaults below. Unknown event names fall back to DEFAULT_THEME_NAME.

EVENT_THEME_MAP = {
    "default": "console_dark",
    "info":    "console_dark",
    "error":   "classic",
    "warning": "slate",
    "tip":     "slate",
    "success": "console_dark",
    "qaqc":    "classic",
    "debug":   "console_dark",
}


def get_event_theme(event):
    """Resolve an event name (e.g. "error") to a THEMES preset name.

    Honors CONFIG override at "output_event_theme_map". Unknown event names
    fall back to DEFAULT_THEME_NAME so callers never crash on typos.
    """
    if event is None:
        return DEFAULT_THEME_NAME
    merged = dict(EVENT_THEME_MAP)
    try:
        import CONFIG
        override = CONFIG.get_setting("output_event_theme_map", None) or {}
        for k, v in override.items():
            if isinstance(v, _STRING_TYPES) and v in THEMES:
                merged[k] = v
    except Exception:
        pass
    theme = merged.get(event, DEFAULT_THEME_NAME)
    if theme not in THEMES:
        return DEFAULT_THEME_NAME
    return theme


def _read_theme_override_file():
    """Optionally merge per-user hex tweaks from a JSON file in the dump folder.

    Only keys in THEME_TOKEN_KEYS are honored; unknown keys are silently dropped
    so a typo in the override file cannot break the page.
    """
    overrides = {}
    try:
        override_path = FOLDER.get_local_dump_folder_file("output_theme_override.json")
        if not os.path.exists(override_path):
            return overrides
        with io.open(override_path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
        for k, v in raw.items():
            if k in THEME_TOKEN_KEYS and isinstance(v, _STRING_TYPES):
                overrides[k] = v
    except Exception:
        return overrides
    return overrides


def _resolve_theme(theme_name=None, runtime_overrides=None):
    """Return a fully resolved theme dict: preset + JSON file + runtime overrides.

    Precedence (lowest -> highest): preset defaults -> override JSON file ->
    runtime overrides passed in by the caller.
    """
    name = theme_name or DEFAULT_THEME_NAME
    base = dict(THEMES.get(name, THEMES[DEFAULT_THEME_NAME]))
    for k, v in _read_theme_override_file().items():
        base[k] = v
    if runtime_overrides:
        for k, v in runtime_overrides.items():
            if k in THEME_TOKEN_KEYS and isinstance(v, _STRING_TYPES):
                base[k] = v
    return base


def _emit_theme_css(theme_dict, selector=":root"):
    """Emit a `selector { --token: value; ... }` block for a resolved theme."""
    parts = [selector, " {"]
    for key in THEME_TOKEN_KEYS:
        parts.append("--{0}: {1};".format(key.replace("_", "-"), theme_dict[key]))
    parts.append("}")
    return "".join(parts)


def _emit_static_css():
    """Stylesheet body that references theme tokens via var(). Theme-agnostic."""
    return (
        "body { background-color: var(--surface); font-family: var(--font-family); "
        "color: var(--text-primary); margin-left:10%; margin-right:10%; }"
        "h1 { font-size: 35px; font-weight: bold; color: var(--heading-primary); }"
        "h2 { font-size: 20px; color: var(--heading-secondary); }"
        "h3 { font-size: 15px; color: var(--heading-secondary); }"
        "ul { list-style-type: none; margin: 20; padding: 10; }"
        "li { margin-left: 40px; color: var(--heading-primary); }"
        "foot_note { font-size: 8px; color: var(--heading-secondary); }"
        "custom_link { color: var(--link); text-decoration: none; "
        "transition: all 0.3s ease; display: inline-block; }"
        "custom_link:hover { color: var(--link-hover); transform: translateY(-2px); "
        "text-shadow: 0 0 8px rgba(255,255,255,0.5); }"
        """
        #floating-logo-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 9999;
            overflow: hidden;
        }
        #floating-logo {
            position: absolute;
            transition: transform 0.1s ease-out;
            opacity: 0.8;
            filter: drop-shadow(0 0 10px var(--logo-glow));
            transform-origin: center center;
        }
        .floating-footer {
            position: fixed;
            bottom: 20px;
            left: 0;
            width: 100%;
            text-align: center;
            color: var(--footer-muted);
            font-size: 24px;
            opacity: 0;
            z-index: 1000;
        }
        .message-animate {
            animation: fadeFloat 4s ease-in-out forwards;
        }
        @keyframes fadeFloat {
            0% { opacity: 0; transform: translateY(10px); }
            20% { opacity: 0.7; transform: translateY(0); }
            80% { opacity: 0.7; transform: translateY(0); }
            100% { opacity: 0; transform: translateY(-10px); }
        }
        .error-card {
            background: var(--error-surface);
            border-radius: 10px;
            padding: 15px;
            margin: 20px 0;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            animation: shake 1.2s;
            position: relative;
            border-left: 5px solid var(--error-border);
            transition: all 0.3s ease;
            color: var(--error-text);
            padding-right: 80px;
        }
        .error-card::before {
            content: '!';
            position: absolute;
            right: 10px;
            top: 10px;
            font-size: 24px;
            transition: transform 0.3s ease;
        }
        .error-card:hover {
            transform: scale(1.02) translateX(5px);
            box-shadow: 0 6px 12px var(--card-hover-shadow);
            background: var(--surface);
            border-left: 5px solid var(--heading-primary);
        }
        .error-card:hover::before {
            transform: rotate(15deg) scale(1.2);
            animation: bounce 0.8s infinite;
        }
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-5px); }
            75% { transform: translateX(5px); }
            animation-timing-function: ease-in-out;
        }
        @keyframes bounce {
            0%, 100% { transform: translateY(0) rotate(15deg); }
            50% { transform: translateY(-5px) rotate(15deg); }
        }
        .copy-btn {
            position: absolute;
            right: 40px;
            top: 50%;
            transform: translateY(-50%);
            padding: 5px 10px;
            background: var(--accent);
            border: none;
            border-radius: 5px;
            color: var(--error-text);
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .copy-btn:hover {
            background: var(--accent-strong);
            color: var(--surface);
        }
        .custom_link {
            color: var(--link);
            text-decoration: underline;
            transition: all 0.3s ease;
            display: inline-block;
        }
        .custom_link:hover {
            color: var(--link-hover);
            transform: translateY(-2px);
            text-shadow: 0 0 8px rgba(255,255,255,0.5);
            animation: jump 0.5s ease;
        }
        @keyframes jump {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-2px); }
        }
        """
    )

class Output:
    """Singleton class managing EnneadTab's output system.
    
    This class handles the generation and display of formatted output through HTML reports
    and console output. It supports rich text formatting, error highlighting, and
    interactive features like search and copy functionality.

    Attributes:
        _instance (Output): Singleton instance of the Output class
        _out (list): Container for output content and styling
        _report_path (str): Path to the HTML report file
        _graphic_settings (dict): Visual styling configuration
        _is_print_out (bool): Flag controlling console output based on environment
        _footer_messages (list): List of messages to rotate in the footer
    """

    _instance = None
    _out = [] # the container for everything that iEnneadTabng
    _report_path = FOLDER.get_local_dump_folder_file("EnneadTab Output.html")
    # Active theme name (preset key in THEMES). Lazily resolved against CONFIG
    # the first time the HTML is built, so a user setting written via
    # CONFIG.set_setting("output_html_theme", ...) is picked up automatically.
    _active_theme_name = None
    # Optional dict of token-level overrides applied on top of the preset at
    # render time. Populated via apply_theme_overrides().
    _theme_overrides = None
    # Legacy alias kept for backward compatibility with any external readers.
    _graphic_settings = {
            'background_color': 'rgb(50, 50, 50)',
            'font_family': 'Helvetica, Arial, sans-serif',
            'text_color': 'white'
        }
    input_1 = [
        "EnneadTab | Made with Love and Duck",
        "Generated at {}".format(TIME.get_formatted_current_time())
    ]
    try:
        import JOKE
        input_2 = JOKE.get_all_loading_screen_message()
    except:
        input_2 = input_1[:]
    random.shuffle(input_2)
    _footer_messages = []
    for x in input_2:
        _footer_messages.extend(input_1)
        _footer_messages.append(x)


    
    _footer_messages = [sanitize_message(msg) for msg in _footer_messages]
    
    # when in Reivit, do not print to pollute the nice pyrevit console
    _is_print_out = not (ENVIRONMENT.IS_REVIT_ENVIRONMENT or ENVIRONMENT.IS_RHINO_ENVIRONMENT)
    
    def __new__(cls, *args, **kwargs):
        """Implements the singleton pattern for Output class.

        Returns:
            Output: The single instance of the Output class.
        """
        if not cls._instance:
            cls._instance = super(Output, cls).__new__(cls)
        return cls._instance

    def write(self, content, style = Style.MainBody, as_str=False):
        """Writes content to the output buffer with specified styling.

        Args:
            content: The content to write (can be any type)
            style: The style to apply (default: Style.MainBody)
            as_str (bool): Whether to force convert content to string (default: False)

        Note:
            Content is stored in the output buffer and will be displayed when plot() is called.
            If _is_print_out is True, content is also printed to console.
        """
        if as_str:
            content = str(content)
        Output._out.append((style, content))
        if Output._is_print_out:
            print (content)

    def reset_output(self):
        """Clears the output buffer.
        
        Removes all content from the output buffer without affecting the HTML report.
        """
        Output._out = []

    def is_empty(self):
        """Checks if the output buffer is empty.

        Returns:
            bool: True if no content in output buffer, False otherwise.
        """
        return not Output._out

    def plot(self, theme=None, event=None):
        """Generates and displays the HTML report if output buffer is not empty.

        This method:
        1. Checks if there is content to display
        2. Generates the HTML report with current content
        3. Opens the report in the default web browser

        Args:
            theme (str or None): Optional preset name from THEMES (same keys as
                THEME_NAMES). When given, this single render uses that palette
                only; the globally active theme from set_theme() / CONFIG is
                unchanged. Wins over `event` if both are provided.
            event (str or None): Semantic event name from EVENT_THEME_MAP
                (e.g. "error", "tip", "warning", "qaqc"). Looked up via
                get_event_theme(); the resulting preset is used for this
                render only. Use this in production code rather than naming
                colors directly - it keeps the meaning visible and lets you
                rebind a class of events centrally via CONFIG
                "output_event_theme_map".

        Resolution order if both are None: set_theme() override -> CONFIG
        "output_html_theme" -> DEFAULT_THEME_NAME.
        """
        if self.is_empty():
            return
        resolved = theme
        if resolved is None and event is not None:
            resolved = get_event_theme(event)
        self._generate_html_report(theme_name=resolved)
        self._print_html_report()

    @classmethod
    def _current_theme_name(cls):
        """Resolve the active theme name.

        Order of precedence:
            1. A name explicitly set via set_theme()
            2. CONFIG setting "output_html_theme" (per-user)
            3. DEFAULT_THEME_NAME
        """
        if cls._active_theme_name:
            return cls._active_theme_name
        try:
            import CONFIG
            name = CONFIG.get_setting("output_html_theme", DEFAULT_THEME_NAME)
            if name in THEMES:
                return name
        except Exception:
            pass
        return DEFAULT_THEME_NAME

    @classmethod
    def set_theme(cls, theme_name, persist=False):
        """Set the active theme for subsequent output renders.

        Args:
            theme_name (str): Key in THEMES (e.g. "classic", "console_dark").
            persist (bool): If True, also write the choice to CONFIG so the
                preference survives across sessions. Defaults to False.
        """
        if theme_name not in THEMES:
            raise ValueError(
                "Unknown output theme '{0}'. Available: {1}".format(
                    theme_name, ", ".join(THEME_NAMES)
                )
            )
        cls._active_theme_name = theme_name
        if persist:
            try:
                import CONFIG
                CONFIG.set_setting("output_html_theme", theme_name)
            except Exception:
                pass

    @classmethod
    def get_theme(cls):
        """Return the resolved theme as (name, token_dict)."""
        name = cls._current_theme_name()
        return name, _resolve_theme(name, cls._theme_overrides)

    @classmethod
    def apply_theme_overrides(cls, overrides):
        """Layer ad-hoc token overrides on top of the active preset.

        Args:
            overrides (dict): Mapping of token name -> CSS value. Unknown keys
                are ignored. Pass None or {} to clear.
        """
        if not overrides:
            cls._theme_overrides = None
            return
        clean = {}
        for k, v in overrides.items():
            if k in THEME_TOKEN_KEYS and isinstance(v, _STRING_TYPES):
                clean[k] = v
        cls._theme_overrides = clean or None

    def _generate_html_report(self, save_path=None, theme_name=None):
        """Generates the HTML report with current output content.
        
        Creates a styled HTML file with:
            - Search functionality
            - Error highlighting
            - Copy buttons for error messages
            - Responsive design
            - EnneadTab branding

        Args:
            save_path (str or None): Output HTML path; default is Output._report_path.
            theme_name (str or None): When set, use this THEMES key for CSS tokens
                for this file only. When None, use Output._current_theme_name().
        """
        if save_path is None:
            save_path = Output._report_path
        if theme_name is None:
            resolved_name = self._current_theme_name()
        else:
            if theme_name not in THEMES:
                raise ValueError(
                    "Unknown output theme '{0}'. Available: {1}".format(
                        theme_name, ", ".join(THEME_NAMES)
                    )
                )
            resolved_name = theme_name
        theme = _resolve_theme(resolved_name, Output._theme_overrides)
        with io.open(save_path, 'w', encoding='utf-8') as report_file:
            report_file.write("<html><head><title>EnneadTab Output</title></head><body>")
            report_file.write("<style>")
            report_file.write(_emit_theme_css(theme))
            report_file.write(_emit_static_css())
            report_file.write("</style>")

            report_file.write(FUNCS)

            # Add the search box
            report_file.write("""
            <div style='text-align: center;'>
                <input type='text' id='searchBox' onkeyup='highlightSearch()' placeholder='Search...'>
            </div>
            """)


            # Add the floating logo that follows mouse cursor
            report_file.write("""
            <div id="floating-logo-container">
                <img id="floating-logo" src="file://{}/logo_outline_white.png" height="0">
            </div>
            """.format(ENVIRONMENT.IMAGE_FOLDER))
            
            if Output._out and Output._out[0][1] != "<hr>":
                report_file.write("<hr>")

            for item_style, content in Output._out:
                if isinstance(content, list):
                    report_file.write("<ul>")
                    for i, item in enumerate(content):
                        report_file.write("<li>{0} : {1}</li>".format(i+1,
                                                                    Output.format_content(item)))                      
                    report_file.write("</ul>")
                else:
                    # Make error detection more flexible
                    error_keywords = ["error", "exception", "failed", "crash"]
                    is_error = any(keyword in str(content).lower() for keyword in error_keywords)
                    
                    if is_error:
                        report_file.write("<div class='error-card'>{}<button class='copy-btn' onclick='copyErrorCard(this)'>Copy</button></div>".format(
                            Output.format_content(content)))
                    else:
                        report_file.write("<{0}>{1}</{0}>".format(item_style, Output.format_content(content)))
                    
                
            # Add floating footer that always shows at bottom
            sanitized_messages = json.dumps(Output._footer_messages, ensure_ascii=False)
            report_file.write("<div class='floating-footer' data-messages='{}'></div>".format(sanitized_messages))
            report_file.write("</body></html>")


    @staticmethod
    def format_content(input):
        """Formats input content for HTML display.

        Args:
            input: Content to be formatted (any type)

        Returns:
            str: HTML-safe formatted string representation of the input
        """
        if "bt_" in str(input):
            return "<button onclick='return sample_func(this)'>{}</button>".format(input.split("bt_")[1])
        
        if os.path.exists(str(input)):
            # Special case image sizes
            if "_large" in str(input):
                return "<img src='file://{}' height='800'>".format(input)
            elif "icon" in str(input):
                return "<img src='file://{}' height='80'>".format(input)
            elif "Click.png" in str(input):
                return "<img src='file://{}' height='30'>".format(input)
            
            # Default case: full width with maintained aspect ratio
            return "<img src='file://{}' style='width: 100%; height: auto;'>".format(input)
            
        # Handle hyperlinks (http/https and file://). Use _STRING_TYPES so the
        # check also accepts `unicode` under IronPython 2.7.
        if isinstance(input, _STRING_TYPES):
            if "http" in input:
                return "<a href='{}' target='_blank' class='custom_link'>{}</a>".format(input, input)
            if input.startswith("file://"):
                return "<a href='{}' target='_blank' class='custom_link'>Open file</a>".format(input)
            
        return str(input).replace("\n", "<br>")

    def print_md(self, content):
        """Prints content in markdown format.

        Args:
            content: Content to be displayed in markdown format
        """
        print (content)

    def print_html(self, content):
        """Prints raw HTML content.

        Args:
            content: HTML content to be displayed directly
        """
        print (content)

    def _print_html_report(self):
        """Opens the generated HTML report in the default web browser."""
        webbrowser.open("file://{}".format(Output._report_path))

    def insert_divider(self):
        """Inserts a horizontal line divider in the output."""
        if not Output._out or Output._out[-1][0] != "<hr>":
            self.write("<hr>")

    def reset(self):
        """Resets the output system.
        
        Clears the output buffer and removes the existing HTML report file.
        """
        Output._out = []






####################################################
def get_output():
    """Returns the singleton instance of the Output class.

    Returns:
        Output: The single instance of the Output class
    """
    return Output()


def unit_test():
    """Runs a comprehensive test of the output system.
    
    Tests:
        - Basic output functionality
        - Different style outputs
        - Error message formatting
        - List output
        - Divider insertion
        - HTML report generation
    """
    output = get_output()
    output.write("Sample text in 'Title' style",Style.Title)
    output.write("Sample text in 'Subtitle' style",Style.Subtitle)
    output.write("Sample text in default style")
    output.write("sample text in foot note style(this is not working yet)", Style.Footnote)

    output.insert_divider()
    output.write("\n\n")
    output.insert_divider()
    
    output.write("Trying to print list as item list")
    test_list = ["A", "B", "C", 99, 440, 123]
    output.write(test_list)
    output.write("Trying to print list as str")
    output.write(test_list, as_str=True)
    
    output.insert_divider()

    
    # output.write("Trying to print a random meme image")
    # output.write(IMAGE.get_one_image_path_by_prefix("meme"))

    output.write("https://www.google.com", Style.Link)


    output.insert_divider()

    output.write("Trying to print an error:\nThis is a fake error msg but ususaly trigger by try-except")

    output.insert_divider()


    output.write("Trying to print a button")
    output.write("bt_sample button")


    output.insert_divider()
    new_output = get_output()
    new_output.write("This is a new output object but should write to same old output window")
    new_output.plot()



def generate_theme_preview_html(save_path=None, open_in_browser=True):
    """Render a single HTML page that demonstrates every preset theme.

    The page includes a top-right dropdown that switches the active theme by
    flipping ``document.body.dataset.theme``; each theme's tokens are scoped to
    a ``body[data-theme="..."]`` selector so the same CSS rules render with
    different variables. Use this to compare and approve color schemes before
    promoting one to the default or persisting via CONFIG.

    Args:
        save_path (str): Optional output path. Defaults to a file in the
            EnneadTab dump folder.
        open_in_browser (bool): Open the file after writing it. Default True.

    Returns:
        str: Absolute path to the written HTML file.
    """
    if save_path is None:
        save_path = FOLDER.get_local_dump_folder_file(
            "EnneadTab Output Theme Preview.html"
        )

    theme_names = list(THEMES.keys())
    initial = DEFAULT_THEME_NAME if DEFAULT_THEME_NAME in THEMES else theme_names[0]

    with io.open(save_path, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'>")
        f.write("<title>EnneadTab Output - Theme Preview</title></head>")
        f.write("<body data-theme='{0}'>".format(initial))
        f.write("<style>")
        for name in theme_names:
            theme = _resolve_theme(name)
            f.write(_emit_theme_css(theme, "body[data-theme=\"{0}\"]".format(name)))
        f.write(_emit_static_css())
        f.write(
            """
            .theme-switcher {
                position: fixed;
                top: 12px;
                right: 12px;
                z-index: 10000;
                background: var(--surface);
                color: var(--text-primary);
                border: 1px solid var(--heading-secondary);
                border-radius: 6px;
                padding: 8px 12px;
                font-family: var(--font-family);
                box-shadow: 0 4px 10px rgba(0,0,0,0.35);
            }
            .theme-switcher label {
                margin-right: 8px;
                font-size: 13px;
                color: var(--text-muted);
            }
            .theme-switcher select {
                background: var(--surface);
                color: var(--text-primary);
                border: 1px solid var(--accent);
                border-radius: 4px;
                padding: 4px 8px;
                font-family: var(--font-family);
            }
            .swatches {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin: 16px 0 24px 0;
            }
            .swatch {
                display: flex;
                align-items: center;
                gap: 6px;
                font-size: 12px;
                color: var(--text-muted);
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 4px;
                padding: 4px 8px;
                font-family: var(--font-family);
            }
            .swatch-chip {
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid rgba(0,0,0,0.4);
            }
            """
        )
        f.write("</style>")

        f.write("<div class='theme-switcher'>")
        f.write("<label for='themeSelect'>Theme:</label>")
        f.write(
            "<select id='themeSelect' "
            "onchange='document.body.dataset.theme = this.value'>"
        )
        for name in theme_names:
            sel = " selected" if name == initial else ""
            f.write("<option value='{0}'{1}>{0}</option>".format(name, sel))
        f.write("</select>")
        f.write("</div>")

        f.write("<h1>EnneadTab Output - Theme Preview</h1>")
        f.write(
            "<p>Use the dropdown in the top-right to switch themes. "
            "All sample content below is rendered with the active palette.</p>"
        )

        # Event -> Theme contract table. This is the answer to "which event
        # uses which theme?" - it's data, the table renders the live mapping.
        f.write("<h2>Event &rarr; Theme contract</h2>")
        f.write(
            "<p>Scripts should call <code>output.plot(event=&quot;...&quot;)</code> "
            "with one of the event names below. OUTPUT.py looks the event up in "
            "<code>EVENT_THEME_MAP</code> and renders with the matching preset. "
            "To rebind without editing source, set CONFIG "
            "<code>output_event_theme_map</code>.</p>"
        )
        f.write(
            "<table style='border-collapse: collapse; margin: 16px 0; "
            "font-family: var(--font-family); color: var(--text-primary);'>"
        )
        f.write(
            "<thead><tr>"
            "<th style='text-align:left; padding:6px 14px; "
            "border-bottom:1px solid var(--text-muted);'>event=</th>"
            "<th style='text-align:left; padding:6px 14px; "
            "border-bottom:1px solid var(--text-muted);'>theme</th>"
            "<th style='text-align:left; padding:6px 14px; "
            "border-bottom:1px solid var(--text-muted);'>swatch</th>"
            "</tr></thead><tbody>"
        )
        for event_name in sorted(EVENT_THEME_MAP.keys()):
            mapped_theme = EVENT_THEME_MAP[event_name]
            swatch_hex = THEMES[mapped_theme]["surface"]
            border_hex = THEMES[mapped_theme]["error_border"]
            f.write(
                "<tr>"
                "<td style='padding:6px 14px;'><code>&quot;{0}&quot;</code></td>"
                "<td style='padding:6px 14px;'>{1}</td>"
                "<td style='padding:6px 14px;'>"
                "<span style='display:inline-block; width:22px; height:14px; "
                "background:{2}; border:1px solid {3}; border-radius:3px; "
                "vertical-align:middle;'></span></td>"
                "</tr>".format(event_name, mapped_theme, swatch_hex, border_hex)
            )
        f.write("</tbody></table>")

        f.write("<div class='swatches'>")
        for token in (
            "surface", "text_primary", "heading_primary", "heading_secondary",
            "link", "accent", "error_surface", "error_border",
        ):
            label = token.replace("_", " ")
            f.write(
                "<span class='swatch'>"
                "<span class='swatch-chip' style='background: var(--{0});'></span>"
                "{1}</span>".format(token.replace("_", "-"), label)
            )
        f.write("</div>")

        f.write("<hr>")
        f.write("<h1>Title style (h1)</h1>")
        f.write("<h2>Subtitle style (h2)</h2>")
        f.write("<h3>SubSubtitle style (h3)</h3>")
        f.write(
            "<p>Default body text. This paragraph shows how everyday output "
            "reads against the surface color on the active theme.</p>"
        )
        f.write(
            "<foot_note>Footnote style - small ancillary annotations</foot_note>"
        )

        f.write("<hr>")
        f.write("<p>List sample:</p>")
        f.write("<ul>")
        for i, v in enumerate(["alpha", "beta", "gamma", 99, 440, 123]):
            f.write("<li>{0} : {1}</li>".format(i + 1, v))
        f.write("</ul>")

        f.write("<hr>")
        f.write(
            "<p>Link sample: "
            "<a href='https://www.google.com' class='custom_link'>"
            "https://www.google.com</a></p>"
        )

        f.write("<hr>")
        f.write(
            "<div class='error-card'>Sample error: this is a fake error "
            "message - the kind typically raised by a try/except block."
            "<button class='copy-btn' "
            "onclick=\"this.textContent='Copied!'\">Copy</button></div>"
        )
        f.write("<hr>")
        f.write("</body></html>")

    if open_in_browser:
        webbrowser.open("file://{0}".format(save_path))
    return save_path


def display_output_on_browser():
    """Forces the current output to be displayed in the browser.
    
    Note:
        This is a convenience function that creates an Output instance
        and calls its plot() method.
    """
    if not ENVIRONMENT.IS_REVIT_ENVIRONMENT:
        import NOTIFICATION
        NOTIFICATION.messenger("currently only support Revit Env")
        return
    try:
        from pyrevit import script
        dest_file = FOLDER.get_local_dump_folder_file("EnneadTab Output.html")
        output = script.get_output()
        output.save_contents(dest_file)
        output.close()
        os.startfile(dest_file)
    except Exception as e:
        return
      
#######################################################
if __name__ == "__main__":
    import sys
    if "--preview" in sys.argv or "preview" in sys.argv:
        path = generate_theme_preview_html()
        print("Theme preview written to:")
        print(path)
    else:
        unit_test()
