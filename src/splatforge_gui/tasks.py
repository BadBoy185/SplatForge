"""One disposable runnable per callable; all delivery is queued to the owner thread."""

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot


@dataclass(frozen=True)
class TaskError:
    message: str
    category: str
    traceback: str
    stage: str


class _Signals(QObject):
    started = Signal(str, str)
    result = Signal(str, object)
    error = Signal(str, object)
    finished = Signal(str)


class _Task(QRunnable):
    def __init__(self, identity: str, stage: str, action: Callable, signals: _Signals) -> None:
        super().__init__()
        self.identity, self.stage, self.action, self.signals = identity, stage, action, signals

    @Slot()
    def run(self) -> None:
        self.signals.started.emit(self.identity, self.stage)
        try:
            self.signals.result.emit(self.identity, self.action())
        except Exception as exc:
            self.signals.error.emit(
                self.identity,
                TaskError(str(exc), type(exc).__name__, traceback.format_exc(), self.stage),
            )
        finally:
            self.signals.finished.emit(self.identity)


class TaskExecutor(QObject):
    started = Signal(str, str)
    result = Signal(str, object)
    error = Signal(str, object)
    finished = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.control_pool = QThreadPool(self)
        self.control_pool.setMaxThreadCount(2)
        self._signals: dict[str, _Signals] = {}

    def submit(self, stage: str, action: Callable, *, control: bool = False) -> str:
        identity, signals = uuid4().hex, _Signals(self)
        self._signals[identity] = signals
        signals.started.connect(self.started, Qt.ConnectionType.QueuedConnection)
        signals.result.connect(self.result, Qt.ConnectionType.QueuedConnection)
        signals.error.connect(self.error, Qt.ConnectionType.QueuedConnection)
        signals.finished.connect(self._finish, Qt.ConnectionType.QueuedConnection)
        pool = self.control_pool if control else self.pool
        pool.start(_Task(identity, stage, action, signals))
        return identity

    @Slot(str)
    def _finish(self, identity: str) -> None:
        signals = self._signals.pop(identity)
        self.finished.emit(identity)
        signals.deleteLater()

    @property
    def busy(self) -> bool:
        return bool(self._signals)
