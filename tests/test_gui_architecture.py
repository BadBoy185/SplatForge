"""Architecture acceptance also runs with no GUI extra installed."""

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

HEAVY_IMPORTS = ("torch", "gsplat", "pycolmap", "onnxruntime", "cv2", "ffmpeg", "colmap")


def test_base_cli_does_not_import_qt():
    code = """
import sys
class BlockQt:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide6', 'splatforge_gui')):
            raise AssertionError('Base import requires GUI: ' + fullname)
sys.meta_path.insert(0, BlockQt())
import splatforge
import splatforge.cli.app
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)


def imported_modules(tree: ast.AST, package: str) -> list[str]:
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = importlib.util.resolve_name("." * node.level + module, package)
            modules.append(module)
            # Also catch `from splatforge import adapters` and `from .. import cli`.
            modules.extend(f"{module}.{alias.name}" for alias in node.names)
    return modules


def forbidden_gui_imports(tree: ast.AST, package: str) -> list[str]:
    forbidden_roots = {*HEAVY_IMPORTS, "subprocess", "process_runner"}
    forbidden_packages = ("splatforge.adapters", "PySide6.QtWidgets")
    return [
        name
        for name in imported_modules(tree, package)
        if name.split(".")[0] in forbidden_roots
        or any(name == target or name.startswith(target + ".") for target in forbidden_packages)
    ]


@pytest.mark.parametrize(
    "source",
    [
        "from splatforge_gui.ffmpeg_status import StatusViewModel",
        "import splatforge_gui.colmap_status as status",
        "from .ffmpeg_status import StatusViewModel",
        "from .. import colmap_status as status",
        "from splatforge.core import process",
    ],
)
def test_gui_presentation_imports_with_backend_names_are_allowed(source: str) -> None:
    assert forbidden_gui_imports(ast.parse(source), "splatforge_gui.widgets") == []


@pytest.mark.parametrize(
    "source",
    [
        "import torch",
        "import torch.cuda as backend",
        "from gsplat import rasterization as render",
        "import subprocess as process",
        "from splatforge.adapters import process_runner",
        "from splatforge import adapters as backend",
        "from PySide6.QtWidgets import QWidget",
        "from PySide6 import QtWidgets as widgets",
    ],
)
def test_gui_backend_process_and_widgets_imports_are_forbidden(source: str) -> None:
    assert forbidden_gui_imports(ast.parse(source), "splatforge_gui")


@pytest.mark.parametrize("layer", ["core", "application"])
def test_inward_imports_and_no_processing_libraries(layer: str) -> None:
    root = Path(__file__).parents[1] / "src"
    allowed = {"core"} if layer == "core" else {"core", "application"}
    forbidden = (
        *HEAVY_IMPORTS, "PySide6", "splatforge_gui", "subprocess", "multiprocessing", "sqlite3"
    )
    for file in (root / "splatforge" / layer).rglob("*.py"):
        relative = file.relative_to(root).with_suffix("")
        package = ".".join(relative.parts[:-1])
        for module in imported_modules(ast.parse(file.read_text(encoding="utf-8")), package):
            assert module.split(".")[0] not in forbidden, (file, module)
            if module.startswith("splatforge."):
                assert module.split(".")[1] in allowed, (file, module)


@pytest.mark.parametrize("client", ["splatforge.cli.app", "splatforge_gui.app"])
def test_client_entry_imports_do_not_load_heavy_libraries(client: str) -> None:
    code = f"""
import sys
class BlockHeavy:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {HEAVY_IMPORTS!r}:
            raise AssertionError('Client import requires heavy library: ' + fullname)
sys.meta_path.insert(0, BlockHeavy())
__import__({client!r})
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import splatforge.adapters.storage", "splatforge.adapters.storage"),
        ("from splatforge import adapters", "splatforge.adapters"),
        ("from ..adapters import storage", "splatforge.adapters"),
        ("from .. import cli", "splatforge.cli"),
        ("from . import views", "splatforge.core.views"),
    ],
)
def test_import_resolution_includes_aliases_and_relative_imports(
    source: str, expected: str
) -> None:
    assert expected in imported_modules(ast.parse(source), "splatforge.core")


def test_dependency_boundaries():
    root = Path(__file__).parents[1] / "src"
    for directory in (root / "splatforge/core", root / "splatforge/application"):
        for file in directory.rglob("*.py"):
            assert "PySide6" not in file.read_text(encoding="utf-8"), file
    for file in (root / "splatforge_gui").rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        package = ".".join(file.relative_to(root).with_suffix("").parts[:-1])
        assert not (forbidden := forbidden_gui_imports(tree, package)), (file, forbidden)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and (
                node.name.endswith("Event") or node.name.startswith("paint")
            ):
                assert not any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"service", "prepare", "extract", "run"}
                    for call in ast.walk(node)
                ), (file, node.name)
