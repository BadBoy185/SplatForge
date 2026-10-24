"""Desktop shell. Widgets delegate every application operation to a controller."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from splatforge_gui.controller import ProjectController
from splatforge_gui.models import SOURCE_COLUMNS, RecordModel
from splatforge_gui.preferences import Preferences, apply_theme
from splatforge_gui.thumbnails import ThumbnailModel
from splatforge_gui.widgets.common import ErrorDialog, JsonEditor, ProgressPanel
from splatforge_gui.widgets.inspection import DiagnosticsPage, ResultsPage
from splatforge_gui.widgets.workflow import (
    DatasetPage,
    ReconstructionPage,
    TrainingPage,
    refill_runs,
)


class MainWindow(QMainWindow):
    def __init__(
        self, controller: ProjectController | None = None, preferences: Preferences | None = None
    ) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("SplatForge")
        self.resize(1200, 820)
        self.controller = controller or ProjectController(self)
        self.preferences = preferences or Preferences()
        self.pending_close = False
        self.project_identity = None
        self.opened_page = max(0, min(6, int(self.preferences.get("page", 0))))
        self._after_save = None
        self.setAcceptDrops(True)
        self._build()
        self.controller.changed.connect(self._overview)
        self.controller.progress_changed.connect(self._progress)
        self.controller.metrics_changed.connect(self._metrics)
        self.controller.completed.connect(self._completed)
        self.controller.error.connect(self._error)
        self.controller.dirty_changed.connect(self._dirty)
        self.controller.busy_changed.connect(self._busy)
        geometry = self.preferences.get("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.theme.setCurrentText(self.preferences.get("theme", "System"))
        self._theme(self.theme.currentText())
        self.sidebar.setCurrentRow(0)
        self._recents()

    def _button(self, text: str, name: str, callback, layout) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _build(self) -> None:
        toolbar = QToolBar("Project")
        toolbar.setObjectName("projectToolbar")
        self.addToolBar(toolbar)
        for label, name, shortcut, callback in (
            ("Create Project", "createProjectAction", "Ctrl+N", self._create),
            ("Open Project", "openProjectAction", "Ctrl+O", self._open),
            ("Refresh", "refreshProjectAction", "F5", self.controller.refresh),
            ("Save", "saveProjectAction", "Ctrl+S", self.controller.save),
            ("Project intent…", "projectIntentAction", "Ctrl+,", self._edit),
        ):
            action = toolbar.addAction(label)
            action.setObjectName(name)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            control = toolbar.widgetForAction(action)
            control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            control.setAccessibleName(label)
        self.project_label = QLabel("No project")
        toolbar.addWidget(self.project_label)
        self.mode = QComboBox()
        self.mode.setObjectName("uiMode")
        self.mode.addItems(["Guided", "Advanced"])
        self.mode.setCurrentText(self.preferences.get("mode", "Guided"))
        self.mode.currentTextChanged.connect(lambda value: self.preferences.set("mode", value))
        self.mode.currentTextChanged.connect(self._mode)
        toolbar.addWidget(self.mode)
        self.theme = QComboBox()
        self.theme.setObjectName("themeChoice")
        self.theme.addItems(["System", "Light", "Dark"])
        self.theme.currentTextChanged.connect(self._theme)
        toolbar.addWidget(self.theme)
        central = QWidget()
        outer = QVBoxLayout(central)
        horizontal = QHBoxLayout()
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("navigation")
        self.sidebar.addItems(
            ["Home", "Sources", "Reconstruct", "Dataset", "Train", "Results", "Diagnostics"]
        )
        self.sidebar.setMaximumWidth(180)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        self.sidebar.currentRowChanged.connect(self._page)
        horizontal.addWidget(self.sidebar)
        horizontal.addWidget(self.stack, 1)
        outer.addLayout(horizontal, 1)
        self.progress = ProgressPanel()
        outer.addWidget(self.progress)
        self.cancel_button = self._button("Cancel active run", "cancelRun", self._cancel, outer)
        self.cancel_button.setEnabled(False)
        self.setCentralWidget(central)
        self.home = QWidget()
        home = QVBoxLayout(self.home)
        self.home_summary = QLabel("Create or open a project to begin.")
        self.home_summary.setWordWrap(True)
        home.addWidget(self.home_summary)
        self._button("Create Project", "createProject", self._create, home)
        self._button("Open Project", "openProject", self._open, home)
        self._button("Add Sources", "homeAddSources", lambda: self.sidebar.setCurrentRow(1), home)
        self._button("Continue", "continueWorkflow", lambda: self.sidebar.setCurrentRow(2), home)
        self._button("View Result", "viewResult", lambda: self.sidebar.setCurrentRow(5), home)
        self._button("Diagnose", "diagnose", lambda: self.sidebar.setCurrentRow(6), home)
        self.recent = QListWidget()
        self.recent.setObjectName("recentProjects")
        self.recent.itemActivated.connect(self._open_recent)
        home.addWidget(self.recent)
        self._button("Remove selected recent", "removeRecent", self._remove_recent, home)
        self.stack.addWidget(self.home)
        self.sources = QWidget()
        source_layout = QVBoxLayout(self.sources)
        self.source_summary = QLabel("Empty — open a project, then add media.")
        source_layout.addWidget(self.source_summary)
        self._button("Add Files", "addFiles", self._add_files, source_layout)
        self._button("Add Folder (nonrecursive)", "addFolder", self._add_folder, source_layout)
        self._button(
            "Verify sources (Balanced/local)",
            "verifySources",
            self.controller.verify_sources,
            source_layout,
        )
        self.source_model = RecordModel(SOURCE_COLUMNS, self)
        self.source_table = QTableView()
        self.source_table.setObjectName("sourceTable")
        self.source_table.setModel(self.source_model)
        self.source_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        source_layout.addWidget(self.source_table)
        self.gallery_run = QComboBox()
        self.gallery_run.setObjectName("galleryViewsRun")
        source_layout.addWidget(self.gallery_run)
        self.gallery_offset = 0
        self._button(
            "Load materialized views (100 at a time)",
            "loadGallery",
            lambda: self._load_gallery(0),
            source_layout,
        )
        self._button("Next 100 views", "nextGallery", self._next_gallery, source_layout)
        self._button("Previous 100 views", "previousGallery", self._previous_gallery, source_layout)
        self.thumbnail_model = ThumbnailModel(self)
        self.gallery = QListView()
        self.gallery.setObjectName("imageGallery")
        self.gallery.setModel(self.thumbnail_model)
        self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setUniformItemSizes(True)
        self.gallery.setIconSize(QSize(192, 192))
        self.gallery.activated.connect(self._larger_preview)
        source_layout.addWidget(self.gallery)
        self.source_table.clicked.connect(self._source_preview)
        source_scroll = QScrollArea()
        source_scroll.setWidgetResizable(True)
        source_scroll.setWidget(self.sources)
        self.stack.addWidget(source_scroll)
        self.page_details = {}
        self.workflow_pages = [
            kind(self.controller, self.preferences, self)
            for kind in (
                ReconstructionPage,
                DatasetPage,
                TrainingPage,
                ResultsPage,
                DiagnosticsPage,
            )
        ]
        for page in self.workflow_pages:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self._mode(self.mode.currentText())
        self.statusBar().showMessage("Ready")

    def _mode(self, mode: str) -> None:
        if hasattr(self, "workflow_pages"):
            for page in self.workflow_pages:
                page.set_advanced(mode == "Advanced")

    def _page(self, index: int) -> None:
        if index >= 0:
            self.stack.setCurrentIndex(index)
            if self.controller.overview is not None:
                self.preferences.set("page", index)

    def _theme(self, choice: str) -> None:
        self.preferences.set("theme", choice)
        apply_theme(QApplication.instance(), choice)

    def _recents(self) -> None:
        self.recent.clear()
        for path in self.preferences.recent():
            self.recent.addItem(path + ("" if Path(path).is_dir() else " [Unavailable]"))
            self.recent.item(self.recent.count() - 1).setData(Qt.ItemDataRole.UserRole, path)

    def _remove_recent(self) -> None:
        item = self.recent.currentItem()
        if item:
            self.preferences.remove(item.data(Qt.ItemDataRole.UserRole))
            self._recents()

    def _open_recent(self, item) -> None:
        self.open_project(Path(item.data(Qt.ItemDataRole.UserRole)))

    def _create(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose an empty project directory")
        if path:
            label, ok = QInputDialog.getText(self, "Create Project", "Project label")
            if (
                ok
                and label.strip()
                and self._can_switch(lambda: self.controller.create(Path(path), label.strip()))
            ):
                self.controller.create(Path(path), label.strip())
                self.statusBar().showMessage("Creating project…")

    def _open(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open SplatForge project")
        if path:
            self.open_project(Path(path))

    def open_project(self, root: Path) -> None:
        if self._can_switch(lambda: self.open_project(root)):
            self.statusBar().showMessage("Loading project…")
            self.controller.open(root)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add read-only sources", "", "Media (*.jpg *.jpeg *.png *.mp4 *.mov)"
        )
        if paths:
            self.controller.ingest(tuple(Path(p) for p in paths))

    def _add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Add folder — top level only")
        if directory:
            self.controller.scan_folder(Path(directory))

    def _source_preview(self, index) -> None:
        from splatforge.application.desktop import ThumbnailReference

        row = self.source_model.rows[index.row()]
        if row.values["type"] == "photo":
            self.thumbnail_model.replace(
                (
                    ThumbnailReference(
                        identity=str(row.identity),
                        path=Path(row.values["locator"]),
                        caption=row.values["filename"],
                    ),
                )
            )
        else:
            self.source_summary.setText(
                "Video preview uses materialized views; prepare views first."
            )

    def _load_gallery(self, offset):
        run = self.gallery_run.currentData()
        if run:
            self.gallery_offset = offset
            self.controller.gallery(run, offset)

    def _next_gallery(self):
        self._load_gallery(self.gallery_offset + 100)

    def _previous_gallery(self):
        self._load_gallery(max(0, self.gallery_offset - 100))

    def _larger_preview(self, index) -> None:
        reference = index.data(Qt.ItemDataRole.UserRole)
        if reference:
            self.controller.preview_image(reference)

    def _can_switch(self, after_save=None) -> bool:
        if self.controller.mutating or self.controller.active:
            QMessageBox.information(
                self, "Processing active", "Finish or cancel active work first."
            )
            return False
        return self._resolve_unsaved(after_save)

    def _edit(self) -> None:
        overview = self.controller.overview
        if overview is None:
            return
        value = self.controller.draft or overview.document
        editor = JsonEditor("Saved project intent", value.settings, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.controller.edit(value.model_copy(update={"settings": editor.value}))

    def _overview(self, value) -> None:
        first_project = self.project_identity is None
        if self.project_identity != value.document.project_id:
            self.project_identity = value.document.project_id
            self.workflow_pages[0].request = None
            self.workflow_pages[0].report = self.workflow_pages[0].metrics = None
        for page in self.workflow_pages:
            page.overview(value)
        if first_project and self.sidebar.currentRow() == 0:
            self.sidebar.setCurrentRow(self.opened_page)
        self.preferences.remember(self.controller.root)
        self._recents()
        self.project_label.setText(value.document.label + (" *" if self.controller.dirty else ""))
        self.home_summary.setText(
            f"{value.document.label}\n{self.controller.root}\n{len(value.sources)} sources\n"
            f"Latest validation: {value.index.validation_status}\n"
            + "\n".join(f"{w.name.title()}: {w.status} — {w.detail}" for w in value.workflow)
        )
        self.source_model.replace(value.sources, self.source_table)
        refill_runs(self.gallery_run, value, "views.selected_set")
        self.source_summary.setText(
            f"Ready — {len(value.sources)} sources"
            if value.sources
            else "Empty — add ordinary JPEG, PNG, MP4 or MOV media."
        )
        self._progress(value.active)
        self.statusBar().showMessage("Project refreshed")
        if self.pending_close and not self.controller.mutating and not value.active:
            self.pending_close = False
            if self.controller.has_unresolved:
                self.statusBar().showMessage("Recovery required — teardown remains unresolved")
                self.sidebar.setCurrentRow(6)
            else:
                QTimer.singleShot(0, self.close)

    def _progress(self, value) -> None:
        self.progress.update_progress(value)
        if not value and self.controller.mutating:
            self.progress.label.setText(
                f"Working — {self.controller.operation}; progress unavailable"
            )
            self.progress.bar.setRange(0, 0)
        if not value and self.controller.has_unresolved:
            self.progress.label.setText(
                "Recovery required — interrupted/unresolved work; inspect Diagnostics"
            )
        self.cancel_button.setEnabled(self.controller.can_cancel)

    def _metrics(self, metrics) -> None:
        if metrics:
            text = "\n".join(
                f"{metric['name']}: {metric['value']}"
                for observation in metrics.values()
                for metric in observation.get("diagnostics", [])
            )
            self.statusBar().showMessage(text or "Progress phase updated")

    def _cancel(self) -> None:
        self.cancel_button.setText("Cancelling…")
        self.controller.cancel()

    def _completed(self, name: str, value) -> None:
        if name == "create":
            self.opened_page = 0
        if name == "cancelled":
            self.statusBar().showMessage("Cancelled — application teardown confirmed")
        if name == "folder":
            text = (
                f"{len(value.supported)} supported files; {value.ignored} unsupported entries "
                "ignored. Subfolders are not traversed. Add these files?"
            )
            if (
                value.supported
                and QMessageBox.question(self, "Folder inventory", text)
                == QMessageBox.StandardButton.Yes
            ):
                self.controller.ingest(value.supported)
            elif not value.supported:
                QMessageBox.information(self, "Folder inventory", text)
        if name == "gallery":
            self.thumbnail_model.replace(value)
            self.source_summary.setText(
                f"Gallery — {len(value)} bounded thumbnails, offset {self.gallery_offset}"
            )
        if name == "image":
            from PySide6.QtGui import QPixmap

            dialog = QDialog(self)
            dialog.setWindowTitle("Read-only bounded image preview")
            layout = QVBoxLayout(dialog)
            image = QLabel()
            image.setPixmap(QPixmap.fromImage(value))
            layout.addWidget(image)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.show()
        if name == "save" and self._after_save:
            callback, self._after_save = self._after_save, None
            QTimer.singleShot(0, callback)
        if name == "progress" and not value and not self.controller.mutating:
            self.cancel_button.setText("Cancel active run")
            if self.pending_close and not self.controller.mutating:
                self.controller.refresh()

    def _error(self, error) -> None:
        self.pending_close, self._after_save = False, None
        if error.stage == "cancel":
            self.cancel_button.setText("Cancel active run")
        self.statusBar().showMessage(f"Failed: {error.message}")
        dialog = ErrorDialog(error, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def _dirty(self, dirty: bool) -> None:
        label = (
            self.controller.overview.document.label if self.controller.overview else "SplatForge"
        )
        self.project_label.setText(label + (" * Unsaved" if dirty else ""))

    def _busy(self, busy: bool) -> None:
        self.statusBar().showMessage("Operation running…" if busy else "Ready")

    def _resolve_unsaved(self, after_save=None) -> bool:
        if not self.controller.dirty:
            return True
        result = QMessageBox.warning(
            self,
            "Unsaved project intent",
            "Save edited project intent?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Save:
            self._after_save = after_save
            self.controller.save()
            return False
        if result == QMessageBox.StandardButton.Discard:
            self.controller.discard()
            return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.mutating or self.controller.active:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Processing active")
            dialog.setText(
                "This GUI owns orchestration. Work cannot continue after it exits.\n"
                "Cancellation waits for backend teardown confirmation."
            )
            cancel = None
            if self.controller.can_cancel:
                cancel = dialog.addButton(
                    "Cancel run and close", QMessageBox.ButtonRole.DestructiveRole
                )
            else:
                dialog.setText(
                    f"{self.controller.operation} must finish before closing. "
                    "This application operation has no mid-call cancellation contract."
                )
            back = dialog.addButton("Return", QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(back)
            dialog.exec()
            event.ignore()
            if cancel is not None and dialog.clickedButton() == cancel:
                self.pending_close = True
                self._cancel()
            return
        if not self._resolve_unsaved(self.close):
            event.ignore()
            return
        if self.controller.executor.busy or self.thumbnail_model.executor.busy:
            self.controller.timer.stop()
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        self.preferences.set("geometry", self.saveGeometry())
        self.controller.timer.stop()
        event.accept()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if len(paths) == 1 and paths[0].is_dir():
            self.open_project(paths[0])
        elif paths and self.controller.root:
            supported = tuple(
                p for p in paths if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".mp4", ".mov"}
            )
            if len(supported) != len(paths):
                QMessageBox.information(
                    self,
                    "Unsupported media",
                    f"Ignored {len(paths) - len(supported)} unsupported entries.",
                )
            if supported:
                self.controller.ingest(supported)
