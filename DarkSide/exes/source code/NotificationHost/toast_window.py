"""Frameless stacked toast card widgets for NotificationHost."""

from __future__ import print_function

import os
import webbrowser

from PyQt5.QtCore import (
    Qt,
    QEvent,
    QObject,
    QPropertyAnimation,
    QEasingCurve,
    QTimer,
    QPoint,
    QRectF,
    QParallelAnimationGroup,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QCursor,
    QGuiApplication,
    QFont,
    QFontDatabase,
    QPixmap,
    QMovie,
    QColor,
    QPainterPath,
    QRegion,
)
from PyQt5.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QPushButton,
    QProgressBar,
    QHBoxLayout,
    QVBoxLayout,
    QApplication,
    QGraphicsDropShadowEffect,
    QSizePolicy,
    QToolTip,
    QStyleFactory,
)

import styles
import error_report
import youtube_thumb

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


class _ManualTooltipFilter(QObject):
    """Show tooltips on Enter/Leave + a timer, not Qt's native ToolTip event.

    This card's window flags (Qt.Tool | Qt.WindowDoesNotAcceptFocus +
    WA_ShowWithoutActivating, needed so a toast never steals focus) are a
    documented Windows Qt combination where native tooltips silently never
    appear. Intercepting QEvent.ToolTip (Qt's usual workaround for that bug)
    still did not work here - confirmed live, no tooltip - which means on
    this window QEvent.ToolTip itself is never being synthesized in the
    first place, not just failing to render once synthesized: Qt's internal
    hover-tracking that generates that event likely rides the same
    activation plumbing this window opts out of. QEvent.Enter/Leave are a
    different, more primitive mechanism (already proven reliable - the
    card's own enterEvent/leaveEvent use the equivalent at the window
    level), so drive the tooltip off those instead: start a delay timer on
    Enter, show via QToolTip.showText() when it fires, cancel on Leave.
    """

    _DELAY_MS = 500

    def __init__(self, parent=None):
        super(_ManualTooltipFilter, self).__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show)
        self._pending = None

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Enter:
            self._pending = obj
            self._timer.start(self._DELAY_MS)
        elif et in (QEvent.Leave, QEvent.MouseButtonPress):
            self._timer.stop()
            self._pending = None
            QToolTip.hideText()
        return False

    def _show(self):
        obj = self._pending
        if obj is not None and obj.isVisible():
            QToolTip.showText(QCursor.pos(), obj.toolTip(), obj)


def screen_for_cursor():
    """Anchor screen: the screen containing the cursor (bottom-left stack)."""
    pos = QCursor.pos()
    screen = QGuiApplication.screenAt(pos)
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    return screen


def anchor_geometry():
    screen = screen_for_cursor()
    return screen.availableGeometry()


def _rounded_top_mask(width, height, radius):
    """QRegion clipping a rect to rounded top corners, square bottom edge.

    Used to make a full-bleed hero image seat flush inside the card's own
    rounded corners without a mismatched hard-edged rectangle poking out.
    """
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    # addRoundedRect rounds all four corners; squaring the bottom two means
    # covering where their rounding would be with a flat rect.
    if height > radius:
        bottom = QPainterPath()
        bottom.addRect(QRectF(0, height - radius, width, radius))
        path = path.united(bottom)
    return QRegion(path.toFillPolygon().toPolygon())


def _icon_font():
    """Monochrome Segoe MDL2 Assets when present; else Segoe UI Symbol."""
    families = QFontDatabase().families()
    if styles.ICON_FONT_FAMILY in families:
        return QFont(styles.ICON_FONT_FAMILY, 11)
    if "Segoe UI Symbol" in families:
        return QFont("Segoe UI Symbol", 11)
    return QFont(styles.DEFAULT_FONT_FAMILY, 11)


class ToastCard(QWidget):
    """One opaque frameless toast with corner icon actions + optional buttons."""

    closed = pyqtSignal(object)
    mute_requested = pyqtSignal()
    # Fired when hover shows/hides action buttons (card height may change).
    layout_needed = pyqtSignal()

    def __init__(self, payload, parent=None):
        super(ToastCard, self).__init__(parent)
        # Caller (host) should already enrich YouTube; keep cached-only as safety.
        self.payload = youtube_thumb.enrich_payload(payload or {}, allow_network=False)
        self._closing = False
        self._target_pos = None
        self._action_bar = None
        self._icon_col = None
        self._countdown_bar = None
        self._countdown_anim = None
        self._countdown_pause_remaining_ms = None
        self._body_text = self.payload.get("main_text") or ""
        self._title_text = self.payload.get("title") or ""
        self.sticky = bool(self.payload.get("sticky"))

        level = (self.payload.get("level") or styles.DEFAULT_LEVEL).lower()
        if level not in styles.LEVEL_ACCENT:
            level = styles.DEFAULT_LEVEL
        self.level = level

        font_family = (
            self.payload.get("font_family") or styles.resolve_default_font_family()
        )
        font_size = self.payload.get("font_size") or styles.DEFAULT_FONT_SIZE
        try:
            font_size = int(font_size)
        except (TypeError, ValueError):
            font_size = styles.DEFAULT_FONT_SIZE

        stay = self.payload.get("animation_stay_duration")
        if stay is not None:
            try:
                stay_f = float(stay)
                self.stay_ms = int(stay_f * 1000) if stay_f < 100 else int(stay_f)
            except (TypeError, ValueError):
                self.stay_ms = styles.stay_ms_for_level(level)
        else:
            self.stay_ms = styles.stay_ms_for_level(level)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Translucent so the soft drop shadow around the card is visible.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(styles.window_width())

        # Shared across every tooltip-bearing button on this card - see
        # _ManualTooltipFilter's docstring for why native tooltips need this
        # workaround on this window's flag combination.
        self._tooltip_filter = _ManualTooltipFilter(self)

        self._build_ui(font_family, font_size)
        self.setStyleSheet(
            styles.build_card_stylesheet(
                level, font_family, font_size,
                has_title=bool(self._title_text),
                has_countdown_bar=not self.sticky,
            )
        )

        # Use windowOpacity for fade so the card can keep a drop-shadow effect.
        self.setWindowOpacity(1.0)

        self._lifetime = QTimer(self)
        self._lifetime.setSingleShot(True)
        self._lifetime.timeout.connect(self.begin_close)

        # A sticky card never auto-closes (see show_at); instead it rests at a
        # low opacity after a quiet interval and returns to full opacity on
        # hover. _dim_timer is the idle countdown; _opacity_anim owns the fade
        # so a hover can interrupt it mid-transition.
        self._opacity_anim = None
        self._dim_timer = QTimer(self)
        self._dim_timer.setSingleShot(True)
        self._dim_timer.timeout.connect(self._dim)

    def _make_icon_btn(self, glyph, tooltip, object_name="IconBtn"):
        btn = QPushButton(glyph)
        btn.setObjectName(object_name)
        btn.setFixedSize(28, 26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.installEventFilter(self._tooltip_filter)
        btn.setFont(_icon_font())
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    def _resolve_image_path(self):
        raw = self.payload.get("image")
        if not raw:
            return None
        path = str(raw).strip()
        if not path or not os.path.isfile(path):
            return None
        ext = os.path.splitext(path)[1].lower()
        if ext not in _IMAGE_EXTS:
            return None
        return path

    def _add_hero_image(self, card_layout):
        """Full-bleed image/gif at the top of the card: edge-to-edge width,
        height follows source aspect ratio uncapped, rounded to the card's
        own top corners (square bottom edge, text content follows below).
        Animated gif via QMovie. Keeps refs on self."""
        path = self._resolve_image_path()
        if not path:
            return

        width = styles.CARD_WIDTH
        label = QLabel()
        label.setObjectName("ToastImage")
        label.setAlignment(Qt.AlignCenter)
        label.setScaledContents(False)

        ext = os.path.splitext(path)[1].lower()
        if ext == ".gif":
            movie = QMovie(path)
            if not movie.isValid():
                error_report.report(
                    "Invalid GIF: {}".format(path),
                    func_name="ToastCard._add_hero_image",
                )
                return
            movie.jumpToFrame(0)
            frame = movie.currentPixmap()
            if frame.isNull():
                return
            scaled = frame.scaledToWidth(width, Qt.SmoothTransformation)
            movie.setScaledSize(scaled.size())
            height = scaled.height()
            label.setFixedSize(width, height)
            label.setMask(_rounded_top_mask(width, height, styles.CARD_RADIUS))
            label.setMovie(movie)
            movie.start()
            self._movie = movie
        else:
            pix = QPixmap(path)
            if pix.isNull():
                return
            scaled = pix.scaledToWidth(width, Qt.SmoothTransformation)
            height = scaled.height()
            label.setFixedSize(width, height)
            label.setMask(_rounded_top_mask(width, height, styles.CARD_RADIUS))
            label.setPixmap(scaled)
            self._pixmap = scaled

        card_layout.addWidget(label)

    def _build_ui(self, font_family, font_size):
        root = QHBoxLayout(self)
        # Padding so the drop shadow is not clipped by the frameless window.
        pad = styles.SHADOW_PAD
        root.setContentsMargins(pad, pad, pad, pad)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("ToastCard")
        root.addWidget(card)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(styles.SHADOW_BLUR)
        shadow.setOffset(0, styles.SHADOW_OFFSET_Y)
        # Neutral, subtle elevation only - the per-level color cue now lives
        # in the card's thin border (styles.level_border_color) instead of
        # a level-tinted ambient glow.
        shadow.setColor(styles.neutral_shadow_color())
        card.setGraphicsEffect(shadow)
        self._shadow = shadow

        # Vertical: optional full-bleed hero image row, then the
        # text/actions + icon-column row below it.
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self._add_hero_image(card_layout)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)
        card_layout.addLayout(content_row, 1)

        if not self.sticky:
            # Thin bottom bar hinting at time left before auto-dismiss.
            # Sticky cards never auto-dismiss, so they get no bar at all.
            bar = QProgressBar()
            bar.setObjectName("CountdownBar")
            bar.setTextVisible(False)
            bar.setRange(0, styles.COUNTDOWN_RANGE_MAX)
            bar.setValue(styles.COUNTDOWN_RANGE_MAX)
            bar.setFixedHeight(styles.COUNTDOWN_BAR_HEIGHT)
            bar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            # Windows' default "windowsvista" QStyle renders QProgressBar via
            # native uxtheme APIs and silently ignores the QSS ::chunk
            # background-color entirely - the bar exists, is visible, and
            # animates correctly (confirmed via debug instrumentation), it
            # just never paints the level-tinted fill. Scope a Fusion style
            # to this one widget (not QApplication.setStyle() globally,
            # which would also reskin the tray context menu and every other
            # native-themed widget) - Fusion is the standard style that
            # fully respects QSS.
            #
            # QStyleFactory.create() returns a new QStyle with no Qt-side
            # ownership transfer to the widget - if nothing in Python keeps
            # a reference, the interpreter garbage-collects the underlying
            # C++ object almost immediately while bar.style() still points
            # at it, and repaints silently stop working (the bar's first
            # paint can still look right, but it never visually updates
            # again - exactly the "not counting down" symptom this caused).
            # self._countdown_bar_style keeps it alive for the card's
            # lifetime, the same "keep a strong reference" pattern this file
            # already uses for animations (self._xxx_anim).
            self._countdown_bar_style = QStyleFactory.create("Fusion")
            bar.setStyle(self._countdown_bar_style)
            card_layout.addWidget(bar)
            self._countdown_bar = bar

        mid = QVBoxLayout()
        mid.setContentsMargins(18, 12, 4, 12)
        mid.setSpacing(8)
        content_row.addLayout(mid, 1)

        wrap_w = styles.body_max_width()

        if self._title_text:
            title = QLabel(self._title_text)
            title.setObjectName("ToastTitle")
            title.setWordWrap(True)
            title.setFont(QFont(font_family, font_size + 1, QFont.DemiBold))
            title.setMaximumWidth(wrap_w)
            title.setFixedWidth(wrap_w)
            mid.addWidget(title)

        body = QLabel(self._body_text)
        body.setObjectName("ToastBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setFont(QFont(font_family, font_size))
        body.setMaximumWidth(wrap_w)
        body.setMinimumWidth(min(120, wrap_w))
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # Force layout to respect wrap width (QLabel otherwise grows wide).
        body.setFixedWidth(wrap_w)
        mid.addWidget(body)

        actions = self.payload.get("actions") or []
        if actions:
            # Hidden until card hover; shown via HoverEnter (see event()).
            bar = QWidget()
            bar.setObjectName("ActionBar")
            row = QHBoxLayout(bar)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            any_btn = False
            for action in actions[:2]:
                if not isinstance(action, dict):
                    continue
                label = action.get("label") or action.get("id") or "Action"
                btn = QPushButton(str(label))
                btn.setObjectName("ActionBtn")
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(self._action_tooltip(action))
                btn.installEventFilter(self._tooltip_filter)
                btn.clicked.connect(
                    lambda _checked=False, a=action: self._run_action(a)
                )
                row.addWidget(btn)
                any_btn = True
            if any_btn:
                row.addStretch(1)
                mid.addWidget(bar)
                # Reserve this row's layout space even while hidden: toggling
                # setVisible() on hover would otherwise change the window's
                # sizeHint, and the resulting adjustSize()/setFixedHeight()
                # resize/reposition out from under the cursor makes Windows
                # fire a spurious leaveEvent, which re-shows -> resizes again
                # -> fires again, forever. See _set_hover_chrome_visible.
                sp = bar.sizePolicy()
                sp.setRetainSizeWhenHidden(True)
                bar.setSizePolicy(sp)
                # Sticky CTAs show their actions immediately — a persistent
                # card that hides its own buttons until hover is a poor
                # pattern for "waiting on a response". Non-sticky cards keep
                # the actions hover-gated like the icon column.
                bar.setVisible(self.sticky)
                self._action_bar = bar

        # Corner icon column: close / copy / mute — hidden until hover.
        icon_col = QWidget()
        icon_col.setObjectName("IconCol")
        icon_col.setFixedWidth(styles.ICON_COL_WIDTH)
        icons = QVBoxLayout(icon_col)
        icons.setContentsMargins(2, 8, 8, 8)
        icons.setSpacing(2)
        content_row.addWidget(icon_col)

        close_btn = self._make_icon_btn(
            styles.SYM_CLOSE, "Dismiss", "IconBtnClose"
        )
        close_btn.setObjectName("IconBtnClose")
        close_btn.clicked.connect(self.begin_close)
        icons.addWidget(close_btn, 0, Qt.AlignTop | Qt.AlignHCenter)

        copy_btn = self._make_icon_btn(
            styles.SYM_COPY, "Copy message", "IconBtn"
        )
        copy_btn.clicked.connect(self._copy_body)
        icons.addWidget(copy_btn, 0, Qt.AlignHCenter)

        mute_btn = self._make_icon_btn(
            styles.SYM_MUTE, "Mute notifications for 1 hour", "IconBtnMute"
        )
        mute_btn.setObjectName("IconBtnMute")
        mute_btn.clicked.connect(self._request_mute)
        icons.addWidget(mute_btn, 0, Qt.AlignHCenter)
        icons.addStretch(1)

        # Reserve layout space while hidden - see the ActionBar comment above
        # for why (same resize/reposition -> spurious-leaveEvent feedback
        # loop, just for the icon column instead of the action row).
        sp = icon_col.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        icon_col.setSizePolicy(sp)
        # Plain setVisible(False), not a QGraphicsOpacityEffect: wrapping a
        # widget with interactive QPushButton children in an opacity effect
        # is a known Qt bug (effect's cached pixmap doesn't repaint on a
        # child's own hover-triggered paint event) - the buttons visually
        # vanish the instant the cursor reaches them. Confirmed against this
        # exact symptom; do not reintroduce a QGraphicsOpacityEffect here.
        icon_col.setVisible(False)
        self._icon_col = icon_col

        # Force immediate layout computation now, before this window is ever
        # shown. Qt can otherwise defer layout activation until show(), which
        # left a sticky card's pre-shown action bar (visible from the start,
        # see above) out of the sizeHint the host reads via card_height() for
        # its very first stacking pass — undersizing the card and letting the
        # button row visually overlap the body text.
        card.layout().activate()
        self.adjustSize()
        # Height follows wrapped text.
        # setFixedHeight (not setMinimumHeight): leaving maximumHeight at its
        # default (QWIDGETSIZE_MAX) while only minimumHeight is pinned made
        # Qt's WM_GETMINMAXINFO handler for this frameless Qt.Tool window
        # report a contradictory maxTrackSize.y of 0 to Windows (min=132,
        # "max"=0), confirmed via Qt's own QWindowsWindow::setGeometry
        # stderr warning firing on every card creation. Locking min=max
        # (both pinned to the same value) sidesteps that broken negotiation.
        self.setFixedHeight(self.sizeHint().height())

    def enterEvent(self, event):
        # enterEvent/leaveEvent fire on the whole card's geometric bounds and
        # are unaffected by children's own hover state, unlike
        # QEvent.HoverEnter/HoverLeave (WA_Hover): the icon/action buttons
        # each carry a ":hover" QSS rule, which makes Qt's style engine set
        # WA_Hover on THEM too - once visible, moving onto a button steals
        # hover from the card and fires HoverLeave on it, hiding the very
        # buttons the cursor just reached. enterEvent/leaveEvent don't have
        # that failure mode. Also drives the sticky-card idle-dim wake
        # (_on_hover_enter/_on_hover_leave) that used to hang off the old
        # event()/HoverEnter dispatch - moved here for the same reason.
        self._set_hover_chrome_visible(True)
        self._set_countdown_paused(True)
        self._on_hover_enter()
        super(ToastCard, self).enterEvent(event)

    def leaveEvent(self, event):
        self._set_hover_chrome_visible(False)
        self._set_countdown_paused(False)
        self._on_hover_leave()
        super(ToastCard, self).leaveEvent(event)

    def _set_countdown_paused(self, paused):
        """Pause/resume the auto-dismiss timer and its bar together on hover.

        QTimer has no native pause/resume, so remainingTime() is captured
        before stopping and used to restart with the correct time left.
        QPropertyAnimation.pause()/.resume() do this natively for the bar.
        No-op for sticky cards (no timer, no bar) and once closing.
        """
        if self.sticky or self._closing or self._countdown_bar is None:
            return
        if paused:
            if self._lifetime.isActive():
                self._countdown_pause_remaining_ms = self._lifetime.remainingTime()
                self._lifetime.stop()
            if self._countdown_anim is not None:
                self._countdown_anim.pause()
        else:
            remaining = self._countdown_pause_remaining_ms
            if remaining is not None and remaining > 0:
                self._lifetime.start(remaining)
            self._countdown_pause_remaining_ms = None
            if self._countdown_anim is not None:
                self._countdown_anim.resume()

    def _set_hover_chrome_visible(self, visible):
        """Show/hide corner icons + optional action buttons on card hover.

        Sticky cards keep their action bar always visible (see _build_ui) —
        only the icon column stays hover-gated for them.

        Plain setVisible() toggle, deliberately NOT a QGraphicsOpacityEffect
        fade: wrapping a widget with interactive QPushButton children in an
        opacity effect is a known Qt bug (the effect's cached pixmap is not
        correctly repainted when a child's own hover state triggers its
        paint event) - the buttons visually disappear the instant the
        cursor reaches them. Confirmed against this exact symptom on this
        card; do not reintroduce a QGraphicsOpacityEffect here.

        Both hover-gated widgets keep their layout space reserved via
        sizePolicy().setRetainSizeWhenHidden(True) (set in _build_ui) even
        while hidden, so toggling setVisible() here does not change the
        card's sizeHint() and does not trigger a resize/reposition - that
        was the original resize-out-from-under-the-cursor bug this design
        already fixed, and retainSizeWhenHidden is what keeps it fixed
        regardless of whether the reveal itself fades or cuts.
        """
        if self._closing:
            return
        widgets = (self._icon_col,) if self.sticky else (self._icon_col, self._action_bar)
        for widget in widgets:
            if widget is None:
                continue
            widget.setVisible(visible)

    # ---- sticky-card idle dim / hover undim ------------------------------
    def _begin_dwell(self):
        """Entrance settled: a sticky card starts its idle dim countdown (it
        never auto-closes); a normal card starts its auto-close lifetime."""
        if self._closing:
            return
        if self.sticky:
            self._arm_dim_countdown()
        else:
            self._lifetime.start(self.stay_ms)
            self._start_countdown_bar(self.stay_ms)

    def _arm_dim_countdown(self):
        """Start (or restart) the idle countdown after which a sticky card
        fades to rest. No-op for a normal (auto-closing) card."""
        if self._closing or not self.sticky:
            return
        self._dim_timer.start(styles.STICKY_DIM_DELAY_MS)

    def _animate_opacity(self, target, duration):
        if self._closing:
            return
        if self._opacity_anim is not None:
            self._opacity_anim.stop()
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(duration)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start()
        self._opacity_anim = anim

    def _dim(self):
        """Idle timeout fired: fade a sticky card to its resting opacity."""
        if self._closing or not self.sticky:
            return
        self._animate_opacity(styles.STICKY_DIM_OPACITY, styles.STICKY_DIM_FADE_MS)

    def _on_hover_enter(self):
        """Hover wakes a dimmed sticky card back to full opacity."""
        if self._closing or not self.sticky:
            return
        self._dim_timer.stop()
        self._animate_opacity(1.0, styles.STICKY_DIM_FADE_MS)

    def _on_hover_leave(self):
        # Re-arm the idle countdown; dim again after another quiet interval.
        self._arm_dim_countdown()

    def _copy_body(self):
        try:
            QApplication.clipboard().setText(self._body_text)
        except Exception as e:
            print("Copy failed: {}".format(e))

    def _request_mute(self):
        self.mute_requested.emit()
        self.begin_close()

    def _action_tooltip(self, action):
        """Tooltip text for an action/CTA button. An explicit
        action["tooltip"] always wins; otherwise fall back to a short
        default derived from the action's type."""
        explicit = action.get("tooltip")
        if explicit:
            return str(explicit)
        action_type = (action.get("type") or "").lower()
        payload = action.get("payload")
        if action_type == "open_path":
            if payload:
                name = os.path.basename(str(payload))
                if name and len(name) <= 40:
                    return "Open {}".format(name)
            return "Open file"
        if action_type == "open_url":
            return "Open link"
        if action_type == "copy":
            return "Copy to clipboard"
        if action_type == "dismiss":
            return "Dismiss this notification"
        return "Run this action"

    def _run_action(self, action):
        action_type = (action.get("type") or "").lower()
        payload = action.get("payload")
        try:
            if action_type == "dismiss":
                pass
            elif action_type == "open_path" and payload:
                os.startfile(str(payload))
            elif action_type == "open_url" and payload:
                webbrowser.open(str(payload))
            elif action_type == "copy" and payload:
                QApplication.clipboard().setText(str(payload))
        except Exception as e:
            print("Action failed: {}".format(e))
        self.begin_close()

    def _play_audio_cue(self):
        """Optional wav cue from payload['audio']. Async winsound; never blocks UI."""
        path = self.payload.get("audio")
        if not path:
            return
        path = str(path)
        if not os.path.isfile(path):
            return
        try:
            import winsound
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME
                | winsound.SND_ASYNC
                | winsound.SND_NODEFAULT,
            )
        except Exception:
            try:
                error_report.report_exc("ToastCard._play_audio_cue")
            except Exception:
                pass

    def show_at(self, x, y, animate=True):
        self._target_pos = QPoint(x, y)
        # Materialize in from the left (off-screen): slide + fade, no bounce.
        start_x = x - styles.ENTER_OFFSET_X
        self.move(start_x if animate else x, y)
        self.setWindowOpacity(0.0 if animate else 1.0)
        self.show()
        self.raise_()
        if self.sticky and self._action_bar is not None:
            # The action bar was made visible pre-show (in _build_ui), before
            # Qt's layout for this window was ever activated - sizeHint() at
            # that point can be stale and undersize the card, so the button
            # row visually overlaps the body text. Re-run the exact same
            # visible-then-resize sequence the hover path already uses
            # correctly, but now that the window is actually shown.
            self.adjustSize()
            # setFixedHeight, not setMinimumHeight - see _build_ui for why.
            self.setFixedHeight(self.sizeHint().height())
        self._play_audio_cue()

        if not animate:
            self.move(x, y)
            self.setWindowOpacity(1.0)
            self._begin_dwell()
            return

        slide = QPropertyAnimation(self, b"pos")
        slide.setDuration(styles.SLIDE_IN_MS)
        slide.setStartValue(QPoint(start_x, y))
        slide.setEndValue(QPoint(x, y))
        slide.setEasingCurve(QEasingCurve.OutCubic)

        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(styles.SLIDE_IN_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(slide)
        group.addAnimation(fade)
        group.start()
        # Kept as self._slide: begin_close() stops whatever is in-flight
        # under this name, and QParallelAnimationGroup supports .stop() too.
        self._slide = group

        # Start the post-entrance dwell off a plain wall-clock singleShot, NOT
        # group.finished: if a sibling card joins the stack while this entrance
        # is still in-flight, the host's _layout_stack() reshuffles this card via
        # move_to(), which starts its own QPropertyAnimation on the same "pos"
        # property concurrently with this group's slide. That collision can keep
        # the group from ever reaching Stopped and emitting finished - so a hook
        # gated on finished silently never fires, leaving a normal card on screen
        # forever (and a sticky card never arming its dim). A singleShot keyed off
        # wall-clock time has no dependency on the group's internal state. Found
        # via dogfood: firing two toasts within SLIDE_IN_MS reproducibly stuck the
        # earlier one, confirmed after ruling out a stale PyInstaller build cache.
        # _begin_dwell is _closing-guarded, so a card closed during the delay is a
        # no-op; it dispatches normal -> auto-close lifetime + countdown bar,
        # sticky -> idle dim.
        QTimer.singleShot(styles.SLIDE_IN_MS, self._begin_dwell)

    def _start_countdown_bar(self, duration_ms):
        """(Re)start the bottom countdown bar animating full -> empty over
        duration_ms, in lockstep with self._lifetime. Linear, not eased -
        a countdown should read as mechanical time, not a decorative curve."""
        if self._countdown_bar is None:
            return
        # _begin_dwell (this method's only caller) can itself be invoked more
        # than once for the same card in edge cases - e.g. the host briefly
        # sees isVisible() as False on a card whose show() hasn't been
        # processed by the event loop yet and calls show_at() again. Without
        # stopping a still-running prior animation first, two
        # QPropertyAnimations would race the same QProgressBar "value"
        # property - the same class of bug already fixed for move_to()'s
        # "pos" animation and the hover-chrome fades elsewhere in this file.
        old = getattr(self, "_countdown_anim", None)
        if old is not None:
            old.stop()
        self._countdown_bar.setValue(styles.COUNTDOWN_RANGE_MAX)
        anim = QPropertyAnimation(self._countdown_bar, b"value")
        anim.setDuration(duration_ms)
        anim.setStartValue(styles.COUNTDOWN_RANGE_MAX)
        anim.setEndValue(0)
        anim.start()
        self._countdown_anim = anim

    def move_to(self, x, y, animate=True):
        self._target_pos = QPoint(x, y)
        if not animate or not self.isVisible() or self._closing:
            self.move(x, y)
            return
        # Several cards can arrive in the same poll tick, each triggering a
        # full restack: this card's move_to() can be called 2-3x in a row
        # before the event loop ever runs a frame of the first animation. A
        # QPropertyAnimation targets self but has no Qt parent (self is the
        # animation TARGET, not a QObject parent), so it lives only via the
        # self._reposition_anim reference - overwriting that reference while
        # the old animation is still running drops its only reference and
        # CPython's refcounting destroys the still-active C++ object
        # mid-flight. Stop it first, same pattern as begin_close() already
        # uses for the same class of animation.
        old = getattr(self, "_reposition_anim", None)
        if old is not None:
            old.stop()
        # A sibling card can arrive while THIS card's own entrance animation
        # (show_at's self._slide QParallelAnimationGroup, sliding pos from
        # off-screen + fading opacity) is still mid-flight - well within
        # SLIDE_IN_MS=420ms in a tight back-to-back sequence of messenger()
        # calls. Without stopping it, that entrance group and this
        # reposition's own "pos" animation both drive the same property
        # concurrently, and Qt does not arbitrate between two independent
        # QPropertyAnimations racing the same property: the card can end up
        # at neither intended position, sometimes never reaching fully
        # on-screen. Reproduced via two sticky (non-expiring) cards fired
        # back-to-back - the earlier one silently never became visible.
        slide = getattr(self, "_slide", None)
        if slide is not None:
            slide.stop()
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(styles.SLIDE_MS)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(x, y))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._reposition_anim = anim
        # The entrance group's fade (opacity 0->1) may also still be
        # mid-flight; stopping the group above halts it too, so make sure
        # this card ends up fully opaque rather than stuck part-faded.
        self.setWindowOpacity(1.0)

    def begin_close(self):
        if self._closing:
            return
        self._closing = True
        self._lifetime.stop()
        self._dim_timer.stop()
        movie = getattr(self, "_movie", None)
        if movie is not None:
            try:
                movie.stop()
            except Exception:
                pass

        # Stop any in-flight enter/restack anim so exit owns the window.
        for attr in ("_slide", "_reposition_anim", "_enter_group", "_opacity_anim", "_countdown_anim"):
            anim = getattr(self, attr, None)
            if anim is not None:
                try:
                    anim.stop()
                except Exception:
                    pass

        start = self.pos()
        end = QPoint(start.x() - styles.EXIT_OFFSET_X, start.y())

        slide = QPropertyAnimation(self, b"pos")
        slide.setDuration(styles.SLIDE_OUT_MS)
        slide.setStartValue(start)
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.InCubic)

        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(styles.FADE_MS)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InQuad)

        group = QParallelAnimationGroup(self)
        group.addAnimation(slide)
        group.addAnimation(fade)
        group.finished.connect(self._finish_close)
        group.start()
        self._exit_group = group

    def _finish_close(self):
        self.hide()
        self.closed.emit(self)
        self.deleteLater()

    def card_height(self):
        return max(self.height(), self.sizeHint().height())
