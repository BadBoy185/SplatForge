"""Stable-identity Qt models for growing indexed collections."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class RecordModel(QAbstractTableModel):
    def __init__(self, columns: tuple[tuple[str, str], ...], parent=None) -> None:
        super().__init__(parent)
        self.columns, self.rows = columns, ()

    def rowCount(self, parent=None) -> int:
        return 0 if parent and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None) -> int:
        return 0 if parent and parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row.identity
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            key = self.columns[index.column()][0]
            value = row.identity if key == "identity" else row.values.get(key)
            return "—" if value is None else str(value)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section][1]
        return None

    def replace(self, rows, view=None) -> None:
        if rows == self.rows:
            return
        selected = view.currentIndex().data(Qt.ItemDataRole.UserRole) if view else None
        self.beginResetModel()
        self.rows = tuple(rows)
        self.endResetModel()
        if view and selected:
            for i, row in enumerate(self.rows):
                if row.identity == selected:
                    view.setCurrentIndex(self.index(i, 0))
                    break


SOURCE_COLUMNS = (
    ("filename", "Filename"),
    ("type", "Type"),
    ("bytes", "Bytes"),
    ("verification", "Verification"),
    ("group", "Source group"),
    ("dimensions", "Dimensions"),
)
RUN_COLUMNS = (
    ("identity", "Run"),
    ("stage", "Stage"),
    ("status", "Status"),
    ("started_at", "Started"),
    ("finished_at", "Finished"),
    ("cache", "Cache"),
    ("duration_seconds", "Duration (s)"),
    ("failure_category", "Failure category"),
    ("failure_json", "Failure"),
)
ARTIFACT_COLUMNS = (
    ("artifact_type", "Type"),
    ("identity", "Artifact"),
    ("semantic_digest", "Semantic digest"),
    ("producer_run_id", "Producer"),
    ("storage_status", "Storage"),
    ("pinned", "Pinned"),
)
