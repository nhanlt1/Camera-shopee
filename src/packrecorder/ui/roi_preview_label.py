"""Preview: full camera frame + draggable normalized ROI (green) for station recording.

Tọa độ chuột và vẽ dùng **hệ logic** của QWidget (giống event.position()), tránh lệch DPI
trên Windows khi nhân devicePixelRatio với pixmap có DPR.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

import cv2

from packrecorder.record_roi import clamp_norm_rect, norm_to_pixels, pixels_to_norm


def _letterbox_transform(
    src_w: int, src_h: int, dst_w: int, dst_h: int
) -> tuple[float, float, float, float, float]:
    """Returns scale, ox, oy, dw, dh in destination space (logical pixels)."""
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return (1.0, 0.0, 0.0, float(dst_w), float(dst_h))
    sc = min(dst_w / src_w, dst_h / src_h)
    dw = src_w * sc
    dh = src_h * sc
    ox = (dst_w - dw) * 0.5
    oy = (dst_h - dh) * 0.5
    return (sc, ox, oy, dw, dh)


class RoiPreviewLabel(QWidget):
    """Hiển thị khung camera đầy đủ, ROI màu xanh; kéo khi không khóa."""

    roi_changed = Signal()

    _HANDLE = 12.0
    _MIN_NORM = 0.05

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 200)
        self.setStyleSheet(
            "background:#1a1a1a;color:#888;border:1px solid #424242;border-radius:6px;"
        )
        self._bgr: bytes | None = None
        self._src_w = 0
        self._src_h = 0
        self._roi_norm: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
        self._roi_none_means_full = True
        self._locked = False
        self._fast_scale = True
        self._drag_mode: str | None = None
        self._drag_corner: str | None = None
        self._move_start_roi: tuple[float, float, float, float] | None = None
        self._move_anchor_norm: tuple[float, float] | None = None
        self._resize_start_roi_px: tuple[int, int, int, int] | None = None
        self._rubber_a: tuple[float, float] | None = None
        self._rubber_b: tuple[float, float] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def set_fast_scale(self, fast: bool) -> None:
        self._fast_scale = fast

    def set_roi_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self.setCursor(
            Qt.CursorShape.ArrowCursor if self._locked else Qt.CursorShape.CrossCursor
        )

    def set_roi_norm(self, roi: tuple[float, float, float, float] | None) -> None:
        if roi is None:
            self._roi_norm = (0.0, 0.0, 1.0, 1.0)
            self._roi_none_means_full = True
        else:
            self._roi_norm = clamp_norm_rect(roi[0], roi[1], roi[2], roi[3])
            self._roi_none_means_full = False
        self.update()

    def get_roi_norm(self) -> tuple[float, float, float, float] | None:
        x, y, w, h = self._roi_norm
        if self._roi_none_means_full and abs(x) < 1e-6 and abs(y) < 1e-6:
            if abs(w - 1.0) < 1e-6 and abs(h - 1.0) < 1e-6:
                return None
        return clamp_norm_rect(x, y, w, h)

    def clear_frame(self) -> None:
        self._bgr = None
        self._src_w = 0
        self._src_h = 0
        self.update()

    def set_full_frame_bgr(
        self,
        bgr: bytes | None,
        src_w: int,
        src_h: int,
    ) -> None:
        if (
            bgr is None
            or src_w <= 0
            or src_h <= 0
            or len(bgr) != src_w * src_h * 3
        ):
            self.clear_frame()
            return
        self._bgr = bgr
        self._src_w = int(src_w)
        self._src_h = int(src_h)
        self.update()

    def _dest_size(self) -> tuple[int, int]:
        """Kích thước vùng vẽ = pixel logic widget (khớp event.position())."""
        return (max(1, int(self.width())), max(1, int(self.height())))

    def _letterbox_image_rect_f(self) -> QRectF | None:
        if self._bgr is None or self._src_w <= 0 or self._src_h <= 0:
            return None
        tw, th = self._dest_size()
        sc, ox, oy, dw, dh = _letterbox_transform(
            self._src_w, self._src_h, tw, th
        )
        return QRectF(ox, oy, dw, dh)

    def _roi_screen_rect_f(self) -> QRectF | None:
        if self._bgr is None or self._src_w <= 0 or self._src_h <= 0:
            return None
        tw, th = self._dest_size()
        sc, ox, oy, _, _ = _letterbox_transform(
            self._src_w, self._src_h, tw, th
        )
        x, y, w, h = self._roi_norm
        px, py, pw, ph = norm_to_pixels(
            x, y, w, h, self._src_w, self._src_h, even=False
        )
        return QRectF(
            ox + px * sc,
            oy + py * sc,
            pw * sc,
            ph * sc,
        )

    def _widget_to_norm_point(self, wx: float, wy: float) -> tuple[float, float] | None:
        if self._bgr is None or self._src_w <= 0 or self._src_h <= 0:
            return None
        tw, th = self._dest_size()
        sc, ox, oy, _, _ = _letterbox_transform(
            self._src_w, self._src_h, tw, th
        )
        px = (wx - ox) / sc
        py = (wy - oy) / sc
        if px < -1.0 or py < -1.0 or px > self._src_w + 1.0 or py > self._src_h + 1.0:
            return None
        return (px / self._src_w, py / self._src_h)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tw, th = self._dest_size()
        canvas = QPixmap(tw, th)
        canvas.fill(QColor(0x1A, 0x1A, 0x1A))
        cp = QPainter(canvas)
        if self._bgr is not None and self._src_w > 0 and self._src_h > 0:
            try:
                bgr = np.frombuffer(self._bgr, dtype=np.uint8).reshape(
                    (self._src_h, self._src_w, 3)
                )
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                rgb = np.ascontiguousarray(rgb)
                h, w = rgb.shape[:2]
                qimg = QImage(
                    rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888
                )
                pix = QPixmap.fromImage(qimg)
                mode = (
                    Qt.TransformationMode.FastTransformation
                    if self._fast_scale
                    else Qt.TransformationMode.SmoothTransformation
                )
                sc, ox, oy, dw, dh = _letterbox_transform(w, h, tw, th)
                scaled = pix.scaled(
                    int(dw),
                    int(dh),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    mode,
                )
                cp.drawPixmap(int(ox), int(oy), scaled)
            except Exception:
                pass
        r = self._roi_screen_rect_f()
        if r is not None and r.width() > 2 and r.height() > 2:
            pen = QPen(QColor(0x4C, 0xAF, 0x50))
            pen.setWidthF(2.0)
            cp.setPen(pen)
            cp.setBrush(Qt.BrushStyle.NoBrush)
            cp.drawRect(r)
        if self._rubber_a and self._rubber_b:
            pen_rb = QPen(QColor(0x81, 0xC7, 0x84))
            pen_rb.setStyle(Qt.PenStyle.DashLine)
            pen_rb.setWidthF(1.5)
            cp.setPen(pen_rb)
            ax, ay = self._rubber_a
            bx, by = self._rubber_b
            cp.drawRect(QRectF(ax, ay, bx - ax, by - ay).normalized())
        cp.end()
        painter.drawPixmap(0, 0, canvas)

    def mousePressEvent(self, event) -> None:
        if self._locked or self._bgr is None:
            super().mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        wx, wy = float(pos.x()), float(pos.y())
        img_rect = self._letterbox_image_rect_f()
        r = self._roi_screen_rect_f()
        if img_rect is None or r is None:
            super().mousePressEvent(event)
            return
        px, py = wx, wy
        hs = self._HANDLE
        eh = 10.0
        corners: dict[str, QRectF] = {
            "tl": QRectF(r.left(), r.top(), hs, hs),
            "tr": QRectF(r.right() - hs, r.top(), hs, hs),
            "bl": QRectF(r.left(), r.bottom() - hs, hs, hs),
            "br": QRectF(r.right() - hs, r.bottom() - hs, hs, hs),
        }
        for name, qr in corners.items():
            if qr.contains(QPointF(px, py)):
                self._drag_mode = "resize"
                self._drag_corner = name
                x, y, w, h = self._roi_norm
                self._resize_start_roi_px = norm_to_pixels(
                    x, y, w, h, self._src_w, self._src_h, even=False
                )
                self.grabMouse()
                return
        edges: dict[str, QRectF] = {
            "t": QRectF(r.left(), r.top() - eh / 2, r.width(), eh),
            "b": QRectF(r.left(), r.bottom() - eh / 2, r.width(), eh),
            "l": QRectF(r.left() - eh / 2, r.top(), eh, r.height()),
            "r": QRectF(r.right() - eh / 2, r.top(), eh, r.height()),
        }
        for name, qr in edges.items():
            if qr.contains(QPointF(px, py)):
                self._drag_mode = "resize"
                self._drag_corner = name
                x, y, w, h = self._roi_norm
                self._resize_start_roi_px = norm_to_pixels(
                    x, y, w, h, self._src_w, self._src_h, even=False
                )
                self.grabMouse()
                return
        pt = self._widget_to_norm_point(wx, wy)
        if pt is not None and r.contains(QPointF(px, py)):
            self._drag_mode = "move"
            rx, ry, rw, rh = self._roi_norm
            self._move_start_roi = (rx, ry, rw, rh)
            self._move_anchor_norm = (pt[0] - rx, pt[1] - ry)
            self.grabMouse()
            return
        if img_rect.contains(QPointF(px, py)):
            self._drag_mode = "rubber"
            self._rubber_a = (px, py)
            self._rubber_b = (px, py)
            self.grabMouse()
            self.update()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._locked or self._bgr is None:
            super().mouseMoveEvent(event)
            return
        pos = event.position()
        wx, wy = float(pos.x()), float(pos.y())
        px, py = wx, wy
        if self._drag_mode == "rubber" and self._rubber_a is not None:
            self._rubber_b = (px, py)
            self.update()
            return
        if self._drag_mode == "move" and self._move_start_roi and self._move_anchor_norm:
            cur = self._widget_to_norm_point(wx, wy)
            if cur is None:
                super().mouseMoveEvent(event)
                return
            ax, ay = self._move_anchor_norm
            _rx0, _ry0, rw, rh = self._move_start_roi
            nx = cur[0] - ax
            ny = cur[1] - ay
            nx = max(0.0, min(1.0 - rw, nx))
            ny = max(0.0, min(1.0 - rh, ny))
            self._roi_norm = clamp_norm_rect(nx, ny, rw, rh)
            self._roi_none_means_full = False
            self.update()
            return
        if (
            self._drag_mode == "resize"
            and self._drag_corner
            and self._resize_start_roi_px
        ):
            cur = self._widget_to_norm_point(wx, wy)
            if cur is None:
                super().mouseMoveEvent(event)
                return
            px0, py0, pw0, ph0 = self._resize_start_roi_px
            px1 = int(round(cur[0] * self._src_w))
            py1 = int(round(cur[1] * self._src_h))
            corner = self._drag_corner
            min_px = max(8, int(self._MIN_NORM * min(self._src_w, self._src_h)))
            if corner == "br":
                npx, npy = px0, py0
                npw = max(min_px, px1 - px0)
                nph = max(min_px, py1 - py0)
            elif corner == "tl":
                npx = min(px0 + pw0 - min_px, px1)
                npy = min(py0 + ph0 - min_px, py1)
                npw = max(min_px, px0 + pw0 - npx)
                nph = max(min_px, py0 + ph0 - npy)
            elif corner == "tr":
                npx = px0
                npy = min(py0 + ph0 - min_px, py1)
                npw = max(min_px, px1 - px0)
                nph = max(min_px, py0 + ph0 - npy)
            elif corner == "t":
                npx, npw = px0, pw0
                npy = min(py0 + ph0 - min_px, py1)
                nph = max(min_px, py0 + ph0 - npy)
            elif corner == "b":
                npx, npy = px0, py0
                npw = pw0
                nph = max(min_px, py1 - py0)
            elif corner == "l":
                npx = min(px0 + pw0 - min_px, px1)
                npy = py0
                npw = max(min_px, px0 + pw0 - npx)
                nph = ph0
            elif corner == "r":
                npx, npy = px0, py0
                npw = max(min_px, px1 - px0)
                nph = ph0
            else:  # bl
                npx = min(px0 + pw0 - min_px, px1)
                npy = py0
                npw = max(min_px, px0 + pw0 - npx)
                nph = max(min_px, py1 - py0)
            npx = max(0, min(self._src_w - min_px, npx))
            npy = max(0, min(self._src_h - min_px, npy))
            npw = max(min_px, min(self._src_w - npx, npw))
            nph = max(min_px, min(self._src_h - npy, nph))
            self._roi_norm = pixels_to_norm(
                npx, npy, npw, nph, self._src_w, self._src_h
            )
            self._roi_none_means_full = False
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # PySide6 không luôn có QWidget.hasMouseGrab(); releaseMouse() an toàn khi không đang grab.
        self.releaseMouse()
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode is not None:
            mode = self._drag_mode
            changed = mode in ("move", "resize")
            if mode == "rubber" and self._rubber_a and self._rubber_b:
                changed = self._apply_rubber_to_roi()
            self._drag_mode = None
            self._drag_corner = None
            self._move_start_roi = None
            self._move_anchor_norm = None
            self._resize_start_roi_px = None
            self._rubber_a = None
            self._rubber_b = None
            if changed:
                self.roi_changed.emit()
            self.update()
        super().mouseReleaseEvent(event)

    def _apply_rubber_to_roi(self) -> bool:
        if self._bgr is None or self._rubber_a is None or self._rubber_b is None:
            return False
        tw, th = self._dest_size()
        sc, ox, oy, _, _ = _letterbox_transform(
            self._src_w, self._src_h, tw, th
        )
        ax, ay = self._rubber_a
        bx, by = self._rubber_b
        rx = QRectF(ax, ay, bx - ax, by - ay).normalized()
        if rx.width() < 3 or rx.height() < 3:
            return False
        ix0 = (rx.left() - ox) / sc
        iy0 = (rx.top() - oy) / sc
        ix1 = (rx.right() - ox) / sc
        iy1 = (rx.bottom() - oy) / sc
        ix0 = max(0.0, min(float(self._src_w), ix0))
        iy0 = max(0.0, min(float(self._src_h), iy0))
        ix1 = max(0.0, min(float(self._src_w), ix1))
        iy1 = max(0.0, min(float(self._src_h), iy1))
        pw = max(1.0, ix1 - ix0)
        ph = max(1.0, iy1 - iy0)
        self._roi_norm = pixels_to_norm(
            int(ix0), int(iy0), int(round(pw)), int(round(ph)),
            self._src_w, self._src_h,
        )
        self._roi_none_means_full = False
        return True
