"""Documentation harness checks use synthetic files, not repository prose snapshots."""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_docs", Path(__file__).parents[1] / "scripts/check_docs.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_docs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_docs)


def test_links_anchors_reference_definitions_and_fences(tmp_path: Path) -> None:
    target = tmp_path / "Камеры space.md"
    target.write_text("# Camera / input\n## Repeat\n## Repeat\n", encoding="utf-8")
    source = tmp_path / "index.md"
    source.write_text(
        "[camera](<Камеры space.md#camera--input>)\n"
        "[again][ref]\n[ref]: <Камеры space.md#repeat-1>\n"
        "[web](https://example.invalid/no-network)\n"
        "# Map\n[self](#map)\n"
        "```md\n[example](missing.md)\n```\n",
        encoding="utf-8",
    )
    assert check_docs.check_file(source) == []


@pytest.mark.parametrize(
    ("destination", "error"),
    [
        ("missing.md", "missing path"),
        ("target.md#absent", "missing heading fragment"),
        ("Target.md", "case mismatch"),
        ("#absent", "missing heading fragment"),
    ],
)
def test_broken_destination_reports_source_line_and_target(
    tmp_path: Path, destination: str, error: str
) -> None:
    (tmp_path / "target.md").write_text("# Present\n", encoding="utf-8")
    source = tmp_path / "index.md"
    source.write_text(f"# Map\n\n[link]({destination})\n", encoding="utf-8")
    errors = check_docs.check_file(source)
    assert len(errors) == 1
    assert f"{source}:3:" in errors[0]
    assert error in errors[0]
    assert destination in errors[0]


def test_parent_paths_encoding_and_duplicate_headings(tmp_path: Path) -> None:
    (tmp_path / "guide").mkdir()
    (tmp_path / "a b.md").write_text("# `State`\n# State\n# State-1\n", encoding="utf-8")
    source = tmp_path / "guide/index.md"
    source.write_text("[owner](../a%20b.md#state-1-1)\n", encoding="utf-8")
    assert check_docs.check_file(source) == []


@pytest.mark.parametrize(
    "example",
    [
        "`[label](missing.md)`",
        "``[label](missing.md) and `literal` backticks``",
        "`code\n[label](missing.md)`",
        "<!-- [label](missing.md) -->",
        "<!--\n[label](missing.md)\n[ref]: absent.md\n-->",
    ],
)
def test_fake_links_are_ignored_but_adjacent_real_links_are_checked(
    tmp_path: Path, example: str
) -> None:
    source = tmp_path / "index.md"
    source.write_text(example + "\n", encoding="utf-8")
    assert check_docs.check_file(source) == []

    source.write_text(example + "\n[real](real-missing.md)\n", encoding="utf-8")
    errors = check_docs.check_file(source)
    assert len(errors) == 1
    real_line = example.count("\n") + 2
    assert f"{source}:{real_line}:" in errors[0]
    assert "real-missing.md" in errors[0]


def test_inline_code_heading_retains_its_anchor(tmp_path: Path) -> None:
    source = tmp_path / "index.md"
    source.write_text("# `State` ownership\n[self](#state-ownership)\n", encoding="utf-8")
    assert check_docs.check_file(source) == []


@pytest.mark.parametrize("valid", [True, False])
def test_command_exit_status_for_explicit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, valid: bool
) -> None:
    source = tmp_path / "map.md"
    source.write_text("# Map\n[self](#map)\n" if valid else "[bad](absent.md)\n")
    monkeypatch.setattr("sys.argv", ["check_docs.py", str(source)])
    assert check_docs.main() == (0 if valid else 1)
    assert f"{0 if valid else 1} errors" in capsys.readouterr().out
