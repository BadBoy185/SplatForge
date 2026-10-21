"""Versioned narrow parsers for bounded COLMAP CLI evidence (no execution)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from splatforge.core.capabilities import CapabilityStatus

_MAX_HELP = 512 * 1024
_OPTION = re.compile(r"(?m)^\s*--([A-Za-z][A-Za-z0-9_.]*)\b([^\n]*(?:\n(?!\s*--)[^\n]*)*)")
_TOKEN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


@dataclass(frozen=True)
class ParsedOptionHelp:
    recognized: bool
    tokens: tuple[str, ...]
    option_names: tuple[str, ...]
    model_defaults: tuple[tuple[str, str], ...]
    profile: str = "unknown"


def parse_command_listing(text: str) -> tuple[bool, tuple[str, ...]]:
    """V1 accepts a complete Available commands section, never a partial prefix."""

    if len(text) > _MAX_HELP:
        return False, ()
    match = re.search(r"(?m)^\s*Available commands:\s*$", text)
    if match is None:
        return False, ()
    lines = text[match.end() :].strip().splitlines()
    commands = tuple(line.strip() for line in lines if line.strip())
    if not commands or len(commands) > 256:
        return False, ()
    recognized = all(re.fullmatch(r"[a-z][a-z0-9_]{0,127}", item) for item in commands)
    raw = tuple(
        dict.fromkeys(item for item in commands if re.fullmatch(r"[a-z][a-z0-9_]{0,127}", item))
    )
    return recognized, raw


def parse_option_help(text: str, option: str) -> ParsedOptionHelp:
    """V1 parses enums within a single option block, or a known legacy SIFT shape."""

    if len(text) > _MAX_HELP:
        return ParsedOptionHelp(False, (), (), ())
    blocks = [(match.group(1), match.group(2)) for match in _OPTION.finditer(text)]
    names = tuple(dict.fromkeys(name for name, _ in blocks))
    if len(names) > 512 or any(len(name) > 128 for name in names):
        return ParsedOptionHelp(False, (), (), ())
    defaults = []
    for name, block in blocks:
        if name.endswith("model_path"):
            default = re.search(r"^\s+arg\s+\(=([^\n)]*)\)", block)
            if default and len(default.group(1)) <= 1024:
                defaults.append((name, default.group(1).strip()))
    selected = [block for name, block in blocks if name == option]
    if len(selected) == 1:
        enum = re.fullmatch(
            r"\s+arg(?:\s+\(=[^\n)]*\))?\s*\{([^{}]+)\}\s*",
            selected[0],
        )
        if enum:
            tokens = tuple(item.strip() for item in enum.group(1).split(","))
            if 0 < len(tokens) <= 128 and all(_TOKEN.fullmatch(item) for item in tokens):
                return ParsedOptionHelp(
                    True, tuple(dict.fromkeys(tokens)), names, tuple(defaults), "typed_enum_v1"
                )
        return ParsedOptionHelp(False, (), names, tuple(defaults))
    if option not in names and "-h [ --help ]" in text:
        if option == "FeatureExtraction.type":
            required = {
                "database_path",
                "image_path",
                "SiftExtraction.use_gpu",
                "SiftExtraction.max_num_features",
                "SiftExtraction.num_threads",
            }
            token = "SIFT"
        else:
            required = {"database_path", "SiftMatching.use_gpu", "SiftMatching.max_ratio"}
            token = "SIFT_BRUTEFORCE"
        if required <= set(names):
            return ParsedOptionHelp(True, (token,), names, tuple(defaults), "legacy_sift_v1")
    return ParsedOptionHelp(False, (), names, tuple(defaults))


def parse_build_support(text: str, component: str) -> CapabilityStatus:
    """Only explicit build flags are proof; learned enums alone do not certify ONNX."""

    values = {
        value.upper()
        for value in re.findall(
            rf"(?im)^\s*(?:COLMAP_)?{re.escape(component)}_ENABLED\s*[=:]\s*(ON|OFF|1|0)\s*$",
            text,
        )
    }
    if values:
        enabled = values <= {"ON", "1"}
        disabled = values <= {"OFF", "0"}
        if enabled:
            return CapabilityStatus.AVAILABLE
        if disabled:
            return CapabilityStatus.UNAVAILABLE
        return CapabilityStatus.UNKNOWN
    if component == "CUDA":
        for line in text.splitlines():
            if line.startswith("COLMAP ") and "(Commit " in line:
                if " with CUDA" in line:
                    return CapabilityStatus.AVAILABLE
                if "without GPU support" in line or " with HIP" in line:
                    return CapabilityStatus.UNAVAILABLE
    return CapabilityStatus.UNKNOWN
