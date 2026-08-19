"""Frameless stacked toast card widgets for NotificationHost."""

from __future__ import print_function

import os
import webbrowser

from PyQt5.QtCore import (
    Qt,
    QEvent,
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
    QHBoxLayout,
    QVBoxLayout,
    QApplication,
    QGraphicsDropShadowEffect,
    QSizePolicy,
)

import styles
import error_report
import youtube_thumb

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


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

        self._build_ui(font_family, font_size)
        self.setStyleSheet(
            styles.build_card_stylesheet(
                level, font_family, font_size,
                has_title=bool(self._title_text),
            )
        )

        # Use windowOpacity for fade so the card can keep a drop-shadow effect.
        self.setWindowOpacity(1.0)
        # HoverEnter/Leave treat children as part of this widget (needed for
        # clicking action buttons without a false leave).
        self.setAttribute(Qt.WA_Hover, True)

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
        shadow.setColor(styles.level_glow_color(self.level))
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
                btn.clicked.connect(
                    lambda _checked=False, a=action: self._run_action(a)
                )
                row.addWidget(btn)
                any_btn = True
            if any_btn:
                row.addStretch(1)
                mid.addWidget(bar)
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

        icon_col.hide()
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
        self.setMinimumHeight(self.sizeHint().height())

    def event(self, event):
        # WA_Hover: enter/leave fire for the whole card including children.
        if event.type() == QEvent.HoverEnter:
            self._set_hover_chrome_visible(True)
            self._on_hover_enter()
        elif event.type() == QEvent.HoverLeave:
            self._set_hover_chrome_visible(False)
            self._on_hover_leave()
        return super(ToastCard, self).event(event)

    def _set_hover_chrome_visible(self, visible):
        """Show/hide corner icons + optional action buttons on card hover.

        Sticky cards keep their action bar always visible (see _build_ui) —
        only the icon column stays hover-gated for them.
        """
        if self._closing:
            return
        changed = False
        widgets = (self._icon_col,) if self.sticky else (self._icon_col, self._action_bar)
        for widget in widgets:
            if widget is None:
                continue
            if widget.isVisible() == visible:
                continue
            widget.setVisible(visible)
            changed = True
        if not changed:
            return
        # Action bar height change needs restack; icons alone usually do not,
        # but adjust anyway so sizeHint stays honest.
        self.adjustSize()
        self.setMinimumHeight(self.sizeHint().height())
        if self._action_bar is not None:
            self.layout_needed.emit()

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
            self.setMinimumHeight(self.sizeHint().height())
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
        # no-op; it dispatches normal -> auto-close lifetime, sticky -> idle dim.
        QTimer.singleShot(styles.SLIDE_IN_MS, self._begin_dwell)

    def move_to(self, x, y, animate=True):
        self._target_pos = QPoint(x, y)
        if not animate or not self.isVisible() or self._closing:
            self.move(x, y)
            return
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(styles.SLIDE_MS)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(x, y))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._reposition_anim = anim

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
        for attr in ("_slide", "_reposition_anim", "_enter_group", "_opacity_anim"):
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
