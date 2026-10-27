"""QML roles and stable selection over bounded, adapter-owned index records."""

from PySide6.QtCore import Property, Qt, Signal, Slot

from splatforge_gui.models import RecordModel


class PresentationModel(RecordModel):
    selectionChanged = Signal()
    countChanged = Signal()
    IdentityRole = int(Qt.ItemDataRole.UserRole) + 1
    ValuesRole = IdentityRole + 1
    CellRole = ValuesRole + 1

    def __init__(self, columns=(), parent=None) -> None:
        super().__init__(columns, parent)
        self._selected = ""

    def roleNames(self) -> dict:
        return {
            int(Qt.ItemDataRole.DisplayRole): b"display",
            self.IdentityRole: b"recordId",
            self.ValuesRole: b"record",
            self.CellRole: b"cellText",
        }

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == self.IdentityRole:
            return str(row.identity)
        if role == self.ValuesRole:
            return {**row.values, "identity": str(row.identity)}
        if role == self.CellRole:
            return super().data(index, Qt.ItemDataRole.DisplayRole)
        return super().data(index, role)

    def columnCount(self, parent=None) -> int:
        return max(1, super().columnCount(parent))

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self.rows)

    @Property(str, notify=selectionChanged)
    def selectedId(self) -> str:
        return self._selected

    @Property(int, notify=selectionChanged)
    def selectedIndex(self) -> int:
        return next((i for i, r in enumerate(self.rows) if str(r.identity) == self._selected), -1)

    @Property("QVariantMap", notify=selectionChanged)
    def selected(self) -> dict:
        row = next((r for r in self.rows if str(r.identity) == self._selected), None)
        return {**row.values, "identity": str(row.identity)} if row else {}

    @Slot(str)
    def select(self, identity: str) -> None:
        self._selected = identity if any(str(r.identity) == identity for r in self.rows) else ""
        self.selectionChanged.emit()

    def replace(self, rows, view=None) -> None:
        super().replace(rows)
        self.select(self._selected)
        self.countChanged.emit()
