"""Architecture acceptance also runs with no GUI extra installed."""

import ast
import subprocess
import sys
from pathlib import Path


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


def test_dependency_boundaries():
    root = Path(__file__).parents[1] / "src"
    for directory in (root / "splatforge/core", root / "splatforge/application"):
        for file in directory.rglob("*.py"):
            assert "PySide6" not in file.read_text(encoding="utf-8"), file
    for file in (root / "splatforge_gui").rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(
                any(
                    part in name
                    for part in (
                        "subprocess",
                        "process_runner",
                        "adapters",
                        "torch",
                        "gsplat",
                        "QtWidgets",
                    )
                )
                for name in names
            ), (file, names)
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
