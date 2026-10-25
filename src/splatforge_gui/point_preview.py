"""Bounded QPainter center preview in Qt Quick; no Gaussian rasterizer or CUDA state."""

import math

from PySide6.QtCore import Property, QObject, QPointF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtQuick import QQuickPaintedItem


class PointPreview(QQuickPaintedItem):
    sourceChanged = Signal()
    appearanceChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(self.Flag.ItemIsFocusScope, True)
        self.setActiveFocusOnTab(True)
        self._source = None
        self._dark = True
        self.points, self.cameras = (), ()
        self.last = None
        self.reset()

    @Property(QObject, notify=sourceChanged)
    def source(self) -> QObject:
        return self._source

    @source.setter
    def source(self, value) -> None:
        if self._source:
            self._source.previewChanged.disconnect(self._load)
        self._source = value
        if value:
            value.previewChanged.connect(self._load)
        self._load()
        self.sourceChanged.emit()

    @Property(bool, notify=appearanceChanged)
    def dark(self) -> bool:
        return self._dark

    @dark.setter
    def dark(self, value: bool) -> None:
        self._dark = value
        self.appearanceChanged.emit()
        self.update()

    def _load(self) -> None:
        data = self._source._preview if self._source else None
        self.set_data(data)

    def set_data(self, data) -> None:
        self.points, self.cameras = (), ()
        if data and (data.points or data.cameras):
            values = data.points + data.cameras
            bounds = [(min(v[i] for v in values), max(v[i] for v in values)) for i in range(3)]
            center = [(low + high) / 2 for low, high in bounds]
            radius = max(max(high - low for low, high in bounds) / 2, 1e-12)
            self.points = tuple(
                tuple((v[i] - center[i]) / radius for i in range(3)) for v in data.points[:20000]
            )
            self.cameras = tuple(
                tuple((v[i] - center[i]) / radius for i in range(3)) for v in data.cameras[:2000]
            )
        self.reset()

    @Slot()
    def reset(self) -> None:
        self.yaw, self.pitch, self.zoom = 0.3, -0.2, 1.0
        self.update()

    def paint(self, painter: QPainter) -> None:
        background = QColor("#0e141c" if self._dark else "#e9eef5")
        painter.fillRect(self.boundingRect(), background)
        painter.setPen(QColor("#19232f" if self._dark else "#d8e0eb"))
        for x in range(0, int(self.width()), 40):
            painter.drawLine(x, 0, x, int(self.height()))
        for y in range(0, int(self.height()), 40):
            painter.drawLine(0, y, int(self.width()), y)
        scale = min(self.width(), self.height()) * 0.38 * self.zoom
        center_x, center_y = self.width() / 2, self.height() / 2
        cy, sy, cp, sp = (
            math.cos(self.yaw),
            math.sin(self.yaw),
            math.cos(self.pitch),
            math.sin(self.pitch),
        )
        for values, color, size in (
            (self.points, "#69b4ff" if self._dark else "#216bb8", 2),
            (self.cameras, "#e7ac43" if self._dark else "#9a6415", 5),
        ):
            painter.setPen(QPen(QColor(color), size))
            projected = []
            for x, y, z in values:
                xx, zz = cy * x + sy * z, -sy * x + cy * z
                yy = cp * y - sp * zz
                projected.append(QPointF(center_x + xx * scale, center_y + yy * scale))
            if projected:
                painter.drawPoints(projected)

    def mousePressEvent(self, event) -> None:
        self.forceActiveFocus()
        self.last = event.position()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.last is not None:
            delta = event.position() - self.last
            self.yaw += delta.x() * 0.01
            self.pitch += delta.y() * 0.01
            self.last = event.position()
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.last = None
        event.accept()

    def wheelEvent(self, event) -> None:
        self.zoom = max(0.05, min(20, self.zoom * 1.1 ** (event.angleDelta().y() / 120)))
        self.update()
        event.accept()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_R:
            self.reset()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus):
            self.zoom = max(0.05, min(20, self.zoom * (0.9 if key == Qt.Key.Key_Minus else 1.1)))
            self.update()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.yaw += {Qt.Key.Key_Left: -0.1, Qt.Key.Key_Right: 0.1}.get(key, 0)
            self.pitch += {Qt.Key.Key_Up: -0.1, Qt.Key.Key_Down: 0.1}.get(key, 0)
            self.update()
        else:
            super().keyPressEvent(event)
            return
        event.accept()
