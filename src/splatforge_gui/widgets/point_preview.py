"""Lightweight QPainter orbit preview of bounded centers, with no numerical backend."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class PointPreview(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pointCenterPreview")
        self.setAccessibleName(
            "Point centers: drag to orbit, wheel or plus/minus to zoom, R to reset"
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(240)
        self.points, self.cameras = (), ()
        self.label = "Empty — inspect a reconstruction or Gaussian scene."
        self.last = None
        self.reset()

    def reset(self) -> None:
        self.yaw, self.pitch, self.zoom = 0.3, -0.2, 1.0
        self.update()

    def set_data(self, data) -> None:
        values = data.points + data.cameras
        if values:
            bounds = [(min(v[i] for v in values), max(v[i] for v in values)) for i in range(3)]
            center = [(low + high) / 2 for low, high in bounds]
            radius = max(max(high - low for low, high in bounds) / 2, 1e-12)
            self.points = tuple(
                tuple((v[i] - center[i]) / radius for i in range(3)) for v in data.points
            )
            self.cameras = tuple(
                tuple((v[i] - center[i]) / radius for i in range(3)) for v in data.cameras
            )
        else:
            self.points, self.cameras = (), ()
        self.label = data.label
        self.reset()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        painter.drawText(10, 20, self.label)
        scale = min(self.width(), self.height()) * 0.38 * self.zoom
        cy, sy, cp, sp = (
            math.cos(self.yaw),
            math.sin(self.yaw),
            math.cos(self.pitch),
            math.sin(self.pitch),
        )
        for values, color in (
            (self.points, QColor(70, 140, 210)),
            (self.cameras, QColor(220, 120, 40)),
        ):
            painter.setPen(color)
            projected = []
            for x, y, z in values:
                xx, zz = cy * x + sy * z, -sy * x + cy * z
                yy = cp * y - sp * zz
                projected.append(
                    QPointF(self.width() / 2 + xx * scale, self.height() / 2 + yy * scale)
                )
            if projected:
                painter.drawPoints(projected)
        painter.end()

    def mousePressEvent(self, event) -> None:
        self.last = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self.last is not None:
            delta = event.position() - self.last
            self.yaw += delta.x() * 0.01
            self.pitch += delta.y() * 0.01
            self.last = event.position()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        self.last = None

    def wheelEvent(self, event) -> None:
        self.zoom = max(0.05, min(20, self.zoom * 1.1 ** (event.angleDelta().y() / 120)))
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_R:
            self.reset()
        elif event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom = max(
                0.05, min(20, self.zoom * (0.9 if event.key() == Qt.Key.Key_Minus else 1.1))
            )
            self.update()
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.yaw += (
                0.1
                if event.key() == Qt.Key.Key_Right
                else -0.1
                if event.key() == Qt.Key.Key_Left
                else 0
            )
            self.pitch += (
                0.1
                if event.key() == Qt.Key.Key_Down
                else -0.1
                if event.key() == Qt.Key.Key_Up
                else 0
            )
            self.update()
        else:
            super().keyPressEvent(event)
