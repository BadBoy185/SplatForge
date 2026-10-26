"""Check local Markdown destinations without network access or third-party packages."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s()]*(?:\([^()]*\)[^\s()]*)*)")
REFERENCE = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE)
LINK_EXAMPLES = re.compile(
    r"<!--.*?(?:-->|$)|(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL
)


def prose(text: str) -> str:
    """Keep line positions while excluding fenced code examples."""
    lines = []
    fence = ""
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            token = match[1]
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            lines.append("")
        else:
            lines.append("" if fence else line)
    return "\n".join(lines)


def link_prose(text: str) -> str:
    """Mask comments/code spans for link search, preserving diagnostic line numbers.

    Anchors use prose() directly so heading text inside code spans is retained.
    """
    return LINK_EXAMPLES.sub(lambda match: re.sub(r"[^\n]", " ", match[0]), prose(text))


def anchors(text: str) -> set[str]:
    """GitHub-style ATX heading fragments, including duplicate-heading suffixes."""
    found: set[str] = set()
    for line in prose(text).splitlines():
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", match[1]).lower()
        slug = re.sub(r"[^\w\-\s]", "", title).replace(" ", "-")
        candidate = slug
        suffix = 0
        while candidate in found:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        found.add(candidate)
    return found


def exact_case_exists(target: Path) -> bool:
    """Catch links that work on Windows but fail on a case-sensitive checkout."""
    if not target.exists():
        return False
    for child in (target, *target.parents):
        if child == child.parent:
            break
        if child.name not in {entry.name for entry in child.parent.iterdir()}:
            return False
    return True


def check_file(source: Path) -> list[str]:
    text = link_prose(source.read_text(encoding="utf-8"))
    errors = []
    for match in (*INLINE_LINK.finditer(text), *REFERENCE.finditer(text)):
        destination = match[1].strip("<>")
        parts = urlsplit(destination)
        if parts.scheme or parts.netloc:
            continue
        # absolute() preserves spelling on Windows; resolve() can conceal case errors.
        target = (source.parent / unquote(parts.path) if parts.path else source).absolute()
        # Collapse .. lexically without resolving symlinks or correcting case.
        target = Path(os.path.normpath(target))
        line = text.count("\n", 0, match.start()) + 1
        error = ""
        if not exact_case_exists(target):
            error = "missing path or case mismatch"
        elif (
            parts.fragment
            and target.suffix.lower() == ".md"
            and unquote(parts.fragment) not in anchors(target.read_text(encoding="utf-8"))
        ):
            error = "missing heading fragment"
        if error:
            errors.append(f"{source}:{line}: {error}: {destination}")
    return errors


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        {
            *root.glob("*.md"),
            *(root / "docs").rglob("*.md"),
            *(root / ".agents" / "skills").rglob("*.md"),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Markdown files; default: repo docs")
    args = parser.parse_args()
    sources = args.paths or markdown_files(ROOT)
    errors = []
    for source in sources:
        try:
            errors.extend(check_file(source))
        except (OSError, ValueError) as exc:
            errors.append(f"{source}: {exc}")
    for error in errors:
        print(error)
    print(f"Checked {len(sources)} Markdown files; {len(errors)} errors.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
