"""
Tiled texture preview with face outline overlay.
Supports drag-to-offset and scroll-to-zoom.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget


class TexturePreviewWidget(QWidget):
    offset_changed = Signal(float, float)
    tiling_changed = Signal(float, float)
    rotation_changed = Signal(float)

    _PREVIEW_HEIGHT = 200
    _BG_COLOR = QColor(50, 50, 50)
    _OUTLINE_COLOR = QColor(255, 255, 0)
    _OUTLINE_WIDTH = 2
    _ZOOM_FACTOR = 1.1
    _FIT_PADDING = 0.80
    _ROTATION_HANDLE_RADIUS = 40
    _ROTATION_HANDLE_INNER = 30
    _LERP_FACTOR = 0.15

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self._PREVIEW_HEIGHT)
        self.setMinimumWidth(100)

        self._texture_pixmap: QPixmap | None = None
        self._tile_u = 1.0
        self._tile_v = 1.0
        self._rotation = 0.0
        self._offset_u = 0.0
        self._offset_v = 0.0
        self._face_shape: list[tuple] = []
        self._last_scale = 1.0

        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._target_offset_u = 0.0
        self._target_offset_v = 0.0

        self._rotation_dragging = False
        self._rotation_start_angle = 0
        self._rotation_start_rotation = 0.0

    def set_texture(self, path: str):
        if not path:
            self._texture_pixmap = None
        else:
            px = QPixmap(path)
            self._texture_pixmap = px if not px.isNull() else None
        self.update()

    def set_uv_params(
        self,
        tile_u: float,
        tile_v: float,
        rotation: float,
        offset_u: float,
        offset_v: float,
    ):
        self._tile_u = tile_u
        self._tile_v = tile_v
        self._rotation = rotation
        self._offset_u = offset_u
        self._offset_v = offset_v
        self.update()

    def set_face_shape(self, verts_2d: list[tuple]):
        self._face_shape = list(verts_2d)
        self.update()

    def clear(self):
        self._texture_pixmap = None
        self._face_shape = []
        self._tile_u = 1.0
        self._tile_v = 1.0
        self._rotation = 0.0
        self._offset_u = 0.0
        self._offset_v = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w = self.width()
        h = self.height()
        p.fillRect(0, 0, w, h, self._BG_COLOR)

        if not self._face_shape or len(self._face_shape) < 3:
            p.end()
            return

        xs = [v[0] for v in self._face_shape]
        ys = [v[1] for v in self._face_shape]
        face_w = max(xs) - min(xs)
        face_h = max(ys) - min(ys)
        face_cx = (max(xs) + min(xs)) * 0.5
        face_cy = (max(ys) + min(ys)) * 0.5

        if face_w < 1e-6 and face_h < 1e-6:
            p.end()
            return
        if face_w < 1e-6:
            scale = h * self._FIT_PADDING / face_h
        elif face_h < 1e-6:
            scale = w * self._FIT_PADDING / face_w
        else:
            scale = min(w * self._FIT_PADDING / face_w, h * self._FIT_PADDING / face_h)
        self._last_scale = scale

        if self._texture_pixmap is not None and not self._texture_pixmap.isNull():
            tile_w = max(1, scale / max(self._tile_u, 0.01))
            tile_h = max(1, scale / max(self._tile_v, 0.01))

            scaled_tex = self._texture_pixmap.scaled(
                int(tile_w),
                int(tile_h),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )

            tw = int(tile_w)
            th = int(tile_h)
            if tw >= 1 and th >= 1:
                p.save()
                p.translate(w / 2, h / 2)
                p.rotate(self._rotation)
                p.translate(-w / 2, -h / 2)

                origin_px = w / 2 - face_cx * scale
                origin_py = h / 2 + face_cy * scale

                pix_off_x = self._offset_u * scale
                pix_off_y = -self._offset_v * scale

                base_x = origin_px + pix_off_x
                base_y = origin_py + pix_off_y
                start_x = int(base_x % tw - tw)
                start_y = int(base_y % th - th)

                x = start_x
                while x < w + tw:
                    y = start_y
                    while y < h + th:
                        p.drawPixmap(x, y, scaled_tex)
                        y += th
                    x += tw

                p.restore()

        pen = QPen(self._OUTLINE_COLOR, self._OUTLINE_WIDTH)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QColor(255, 255, 0, 30))

        points = []
        for fx, fy in self._face_shape:
            px_x = (fx - face_cx) * scale + w / 2
            px_y = (fy - face_cy) * -scale + h / 2
            points.append(QPointF(px_x, px_y))

        p.drawPolygon(QPolygonF(points))

        center_x, center_y = w / 2, h / 2

        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.setBrush(QBrush(QColor(255, 255, 255, 0)))
        p.drawEllipse(
            QRectF(
                center_x - self._ROTATION_HANDLE_RADIUS,
                center_y - self._ROTATION_HANDLE_RADIUS,
                self._ROTATION_HANDLE_RADIUS * 2,
                self._ROTATION_HANDLE_RADIUS * 2,
            )
        )

        handle_angle_rad = self._rotation * math.pi / 180.0
        handle_radius = (self._ROTATION_HANDLE_INNER + self._ROTATION_HANDLE_RADIUS) / 2
        handle_x = center_x + handle_radius * math.cos(handle_angle_rad)
        handle_y = center_y + handle_radius * math.sin(handle_angle_rad)

        p.setBrush(QBrush(QColor(100, 150, 255)))
        p.setPen(QPen(QColor(50, 100, 200), 2))
        p.drawEllipse(QRectF(handle_x - 6, handle_y - 6, 12, 12))

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            center_x, center_y = self.width() / 2, self.height() / 2
            dx = event.x() - center_x
            dy = event.y() - center_y
            dist = (dx * dx + dy * dy) ** 0.5

            if dist <= self._ROTATION_HANDLE_RADIUS:
                if dist >= self._ROTATION_HANDLE_INNER:
                    angle = math.degrees(math.atan2(dy, dx))
                    self._rotation_dragging = True
                    self._rotation_start_angle = angle
                    self._rotation_start_rotation = self._rotation
                    event.accept()
                    return

            self._dragging = True
            self._drag_start_x = event.x()
            self._drag_start_y = event.y()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._rotation_dragging:
            center_x, center_y = self.width() / 2, self.height() / 2
            dx = event.x() - center_x
            dy = event.y() - center_y
            new_angle = math.degrees(math.atan2(dy, dx))
            angle_diff = new_angle - self._rotation_start_angle
            new_rotation = self._rotation_start_rotation + angle_diff
            self._rotation = new_rotation
            self.update()
            self.rotation_changed.emit(new_rotation)
            event.accept()
            return

        if self._dragging:
            dx = event.x() - self._drag_start_x
            dy = event.y() - self._drag_start_y
            self._drag_start_x = event.x()
            self._drag_start_y = event.y()

            rot_rad = self._rotation * math.pi / 180.0
            cos_r = math.cos(-rot_rad)
            sin_r = math.sin(-rot_rad)
            uv_dx = dx * cos_r - dy * sin_r
            uv_dy = dx * sin_r + dy * cos_r

            new_offset_u = self._offset_u + uv_dx / self._last_scale
            new_offset_v = self._offset_v - uv_dy / self._last_scale
            self._offset_u = new_offset_u
            self._offset_v = new_offset_v
            self.update()
            self.offset_changed.emit(new_offset_u, new_offset_v)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._rotation_dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return

        if delta > 0:
            factor = 1.0 / self._ZOOM_FACTOR
        else:
            factor = self._ZOOM_FACTOR

        self._tile_u = max(0.01, min(100.0, self._tile_u * factor))
        self._tile_v = max(0.01, min(100.0, self._tile_v * factor))
        self.update()
        self.tiling_changed.emit(self._tile_u, self._tile_v)
        event.accept()
