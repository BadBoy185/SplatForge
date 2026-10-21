from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from splatforge.adapters.colmap_capabilities import (
    ColmapCapabilityAdapter,
    ColmapExecutableLocator,
    inspect_colmap_database,
    parse_command_listing,
    parse_option_help,
    validate_sift_probe_output,
)
from splatforge.adapters.process_runner import (
    ExecutableNotFoundError,
    ProcessBoundaryError,
    ProcessRequest,
)
from splatforge.application.doctor_contracts import DoctorTeardownError
from splatforge.core.capabilities import CapabilityStatus, ColmapProbeReport, FreshnessPolicy
from splatforge.core.media import ExecutableIdentity
from splatforge.core.process import ProcessResult

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
IDENTITY = ExecutableIdentity(
    resolved_path="C:/Tools/COLMAP ž/colmap.exe",
    size=123,
    last_write_ns=456,
    volume_id="volume",
    file_id="file",
    change_time_ns=789,
    sha256="a" * 64,
)
COMMANDS = (
    "database_creator",
    "feature_extractor",
    "exhaustive_matcher",
    "sequential_matcher",
    "global_mapper",
    "mapper",
    "hierarchical_mapper",
    "model_converter",
)
TOP_HELP = (
    "COLMAP 4.2.1 (Commit synthetic on 2026-10-21 with CUDA)\n"
    "ONNX_ENABLED=ON\n"
    "Usage: colmap [command] [options]\n"
    "Available commands:\n  " + "\n  ".join(COMMANDS) + "\n"
)
FEATURE_HELP = """Options:
--database_path arg
--image_path arg
--FeatureExtraction.type arg (=SIFT) {SIFT, ALIKED_N16ROT, ALIKED_N32, LOMA_B128}
--FeatureExtraction.use_gpu arg (=1)
--FeatureExtraction.num_threads arg (=-1)
--AlikedExtraction.n16rot_model_path arg (=https://models.invalid/aliked-n16rot.onnx)
--AlikedExtraction.n32_model_path arg (=https://models.invalid/aliked-n32.onnx)
"""
MATCHER_HELP = """Options:
--FeatureMatching.type arg (=SIFT_BRUTEFORCE) {SIFT_BRUTEFORCE, SIFT_LIGHTGLUE,
ALIKED_BRUTEFORCE, ALIKED_LIGHTGLUE, LOMA_B128}
--SiftMatching.lightglue_model_path arg (=https://models.invalid/lightglue-sift.onnx)
--AlikedMatching.lightglue_model_path arg (=https://models.invalid/lightglue-aliked.onnx)
--AlikedMatching.bruteforce_model_path arg (=https://models.invalid/aliked-bruteforce.onnx)
"""


class FakeResolver:
    def __init__(self, identity: ExecutableIdentity = IDENTITY) -> None:
        self.identity = identity
        self.requests: list[str] = []
        self.valid = True

    def resolve(self, requested: str, *, environment=None) -> ExecutableIdentity:  # type: ignore[no-untyped-def]
        self.requests.append(requested)
        return self.identity

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool:
        return self.valid and expected.model_copy(update={"version_line": None}) == (
            self.identity.model_copy(update={"version_line": None})
        )


def process_result(
    request: ProcessRequest,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int | None = 0,
    timed_out: bool = False,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    identity: ExecutableIdentity = IDENTITY,
) -> ProcessResult:
    return ProcessResult(
        executable=identity,
        argv=request.argv,
        working_directory=str(request.working_directory),
        exit_code=exit_code,
        elapsed_seconds=0.01,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=timed_out,
        cancelled=False,
        teardown_confirmed=True,
        forced_tree_termination=timed_out,
    )


class FakeRunner:
    def __init__(self, callback=None) -> None:  # type: ignore[no-untyped-def]
        self.callback = callback
        self.requests: list[ProcessRequest] = []

    def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult:
        self.requests.append(request)
        if self.callback is not None:
            return self.callback(request)
        if request.argv == ("help",):
            return process_result(request, stdout=TOP_HELP.encode())
        if request.argv == ("feature_extractor", "-h"):
            return process_result(request, stdout=FEATURE_HELP.encode())
        if request.argv[0] in {"exhaustive_matcher", "sequential_matcher"}:
            return process_result(request, stdout=MATCHER_HELP.encode())
        raise AssertionError(f"unexpected request: {request.argv}")


def adapter(runner: FakeRunner, *, environment=None) -> ColmapCapabilityAdapter:  # type: ignore[no-untyped-def]
    return ColmapCapabilityAdapter(
        runner=runner,
        resolver=FakeResolver(),
        environment=environment or {},
    )


def create_schema(
    path: Path,
    *,
    missing_table: str | None = None,
    missing_column: tuple[str, str] | None = None,
) -> None:
    columns = {
        "cameras": [
            "camera_id INTEGER PRIMARY KEY",
            "model INTEGER",
            "width INTEGER",
            "height INTEGER",
            "params BLOB",
            "prior_focal_length INTEGER",
        ],
        "images": [
            "image_id INTEGER PRIMARY KEY",
            "name TEXT NOT NULL UNIQUE",
            "camera_id INTEGER",
        ],
        "keypoints": [
            "image_id INTEGER PRIMARY KEY",
            "rows INTEGER",
            "cols INTEGER",
            "data BLOB",
        ],
        "descriptors": [
            "image_id INTEGER PRIMARY KEY",
            "rows INTEGER",
            "cols INTEGER",
            "data BLOB",
        ],
        "matches": [
            "pair_id INTEGER PRIMARY KEY",
            "rows INTEGER",
            "cols INTEGER",
            "data BLOB",
        ],
        "two_view_geometries": [
            "pair_id INTEGER PRIMARY KEY",
            "rows INTEGER",
            "cols INTEGER",
            "data BLOB",
            "config INTEGER",
            "F BLOB",
            "E BLOB",
            "H BLOB",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        for table, definitions in columns.items():
            if table == missing_table:
                continue
            selected = [
                item
                for item in definitions
                if missing_column is None
                or table != missing_column[0]
                or not item.startswith(missing_column[1] + " ")
            ]
            connection.execute(f'CREATE TABLE "{table}" ({", ".join(selected)})')
        connection.commit()


def test_parsers_preserve_unknown_tokens_and_fail_closed() -> None:
    recognized, commands = parse_command_listing(TOP_HELP)
    assert recognized is True
    assert "global_mapper" in commands
    feature = parse_option_help(FEATURE_HELP, "FeatureExtraction.type")
    matcher = parse_option_help(MATCHER_HELP, "FeatureMatching.type")
    assert feature.recognized is True
    assert "LOMA_B128" in feature.tokens
    assert "ALIKED_N16ROT" in feature.tokens
    assert "LOMA_B128" in matcher.tokens
    assert "SIFT_LIGHTGLUE" in matcher.tokens
    assert parse_command_listing("Usage changed completely") == (False, ())
    malformed = parse_option_help(
        "--FeatureExtraction.type SIFT",
        "FeatureExtraction.type",
    )
    assert malformed.recognized is False


def test_locator_precedence_and_safe_path_input(tmp_path: Path) -> None:
    resolver = FakeResolver()
    explicit = tmp_path / "space ž" / "colmap.exe"
    locator = ColmapExecutableLocator(
        resolver,  # type: ignore[arg-type]
        environment={
            "SPLATFORGE_COLMAP": "C:/Environment/colmap.exe",
            "PATH": f"{os.pathsep}.",
        },
    )
    selection = locator.locate(explicit=explicit.absolute(), bundled=Path("C:/Bundle/colmap.exe"))
    assert selection.source == "explicit"
    assert resolver.requests == [str(explicit.absolute())]

    resolver.requests.clear()
    selection = locator.locate(explicit=None, bundled=Path("C:/Bundle/colmap.exe"))
    assert selection.source == "environment"
    assert resolver.requests == ["C:/Environment/colmap.exe"]


@pytest.mark.parametrize(
    "bundled,expected_source,requested",
    [
        (Path("C:/Bundle/colmap.exe"), "bundled", "C:/Bundle/colmap.exe"),
        (None, "path", "colmap"),
    ],
)
def test_locator_bundled_candidate_and_safe_path_fallback(
    bundled, expected_source, requested
) -> None:
    resolver = FakeResolver()
    selected = ColmapExecutableLocator(resolver, environment={}).locate(
        explicit=None, bundled=bundled
    )
    assert selected.source == expected_source
    assert Path(resolver.requests[0]) == Path(requested)


@pytest.mark.skipif(os.name != "nt", reason="Windows native executable contract")
def test_colmap_locator_refuses_batch_wrapper_identity() -> None:
    resolver = FakeResolver(IDENTITY.model_copy(update={"resolved_path": "C:/Tools/colmap.bat"}))
    with pytest.raises(ProcessBoundaryError, match="native COLMAP"):
        ColmapExecutableLocator(resolver, environment={}).locate(
            explicit=Path("C:/Tools/colmap.bat"), bundled=None
        )


def test_lightweight_discovery_maps_static_capabilities_without_functional_probe() -> None:
    runner = FakeRunner()
    report = adapter(runner).probe(
        explicit_executable=Path("C:/Tools/COLMAP ž/colmap.exe"),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.binary.status == CapabilityStatus.AVAILABLE
    assert report.selected_executable is not None
    assert report.selected_executable.identity.version_line.startswith("COLMAP 4.2.1")
    assert "LOMA_B128" in report.command_discovery.feature_tokens
    assert report.capability("colmap.mapper.global").status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.feature.sift.cpu").status == CapabilityStatus.UNKNOWN
    assert report.capability("colmap.feature.sift.gpu").status == CapabilityStatus.UNKNOWN
    assert report.capability("colmap.onnx").status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.feature.aliked").status == CapabilityStatus.UNAVAILABLE
    assert not any(
        request.argv[0] == "feature_extractor" and request.argv != ("feature_extractor", "-h")
        for request in runner.requests
    )


def test_missing_global_mapper_and_sift_only_are_distinct() -> None:
    top = TOP_HELP.replace("  global_mapper\n", "")
    feature = "--FeatureExtraction.type arg (=SIFT) {SIFT}\n--FeatureExtraction.use_gpu arg (=1)\n"
    matcher = "--FeatureMatching.type arg (=SIFT_BRUTEFORCE) {SIFT_BRUTEFORCE}\n"

    def callback(request: ProcessRequest) -> ProcessResult:
        outputs = {
            ("help",): top,
            ("feature_extractor", "-h"): feature,
            ("exhaustive_matcher", "-h"): matcher,
            ("sequential_matcher", "-h"): matcher,
        }
        return process_result(request, stdout=outputs[request.argv].encode())

    report = adapter(FakeRunner(callback)).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.capability("colmap.mapper.global").status == CapabilityStatus.UNAVAILABLE
    assert report.capability("colmap.match.sift_bruteforce").status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.feature.aliked").status == CapabilityStatus.UNAVAILABLE
    assert report.capability("colmap.match.sift_lightglue").status == CapabilityStatus.UNAVAILABLE


def test_malformed_subcommand_help_is_unknown_not_available() -> None:
    def callback(request: ProcessRequest) -> ProcessResult:
        if request.argv == ("help",):
            return process_result(request, stdout=TOP_HELP.encode())
        return process_result(request, stdout=b"new opaque format")

    report = adapter(FakeRunner(callback)).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.capability("colmap.feature.sift.cpu").status == CapabilityStatus.UNKNOWN
    assert report.capability("colmap.onnx").status == CapabilityStatus.UNKNOWN
    assert report.capability("colmap.match.sift_bruteforce").status == CapabilityStatus.UNKNOWN


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"exit_code": 2, "stderr": b"crashed"}, "colmap.probe_failed"),
        ({"exit_code": None, "timed_out": True}, "colmap.probe_timeout"),
        ({"stdout_truncated": True}, "colmap.probe_output_truncated"),
        (
            {"exit_code": 127, "stderr": b"SplatForge process worker: backend launch failed: DLL"},
            "colmap.loader_failure",
        ),
    ],
)
def test_top_level_probe_failures_are_structured(
    updates: dict[str, object],
    expected_code: str,
) -> None:
    runner = FakeRunner(lambda request: process_result(request, **updates))
    report = adapter(runner).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.binary.diagnostic_code == expected_code
    assert report.binary.status != CapabilityStatus.AVAILABLE


def test_concrete_model_files_are_hashed_and_enable_learned_routes(tmp_path: Path) -> None:
    for name in (
        "aliked-n16rot.onnx",
        "aliked-n32.onnx",
        "lightglue-sift.onnx",
        "lightglue-aliked.onnx",
    ):
        (tmp_path / name).write_bytes(("model-" + name).encode())
    report = adapter(FakeRunner()).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=tmp_path,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    by_role = {item.role: item for item in report.models}
    expected = hashlib.sha256(b"model-aliked-n16rot.onnx").hexdigest()
    assert by_role["aliked.n16rot"].sha256 == expected
    assert by_role["aliked.n16rot"].evidence.status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.feature.aliked").status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.match.sift_lightglue").status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.match.aliked_lightglue").status == CapabilityStatus.AVAILABLE


def test_configured_but_missing_model_is_unavailable(tmp_path: Path) -> None:
    report = adapter(FakeRunner()).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=tmp_path,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    model = next(item for item in report.models if item.role == "aliked.n16rot")
    assert model.evidence.status == CapabilityStatus.UNAVAILABLE
    assert model.evidence.diagnostic_code == "colmap.model_unreadable"


def test_binary_replacement_during_help_does_not_reuse_version_text() -> None:
    changed = IDENTITY.model_copy(update={"sha256": "f" * 64})

    def callback(request: ProcessRequest) -> ProcessResult:
        return process_result(request, stdout=TOP_HELP.encode(), identity=changed)

    report = adapter(FakeRunner(callback)).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.binary.status == CapabilityStatus.UNKNOWN
    assert report.binary.diagnostic_code == "colmap.identity_changed"
    assert report.selected_executable is not None
    assert report.selected_executable.identity.version_line is None


def test_native_database_schema_compatibility_and_failures(tmp_path: Path) -> None:
    valid = tmp_path / "valid.db"
    create_schema(valid)
    _, _, tables = inspect_colmap_database(valid)
    assert {table.name for table in tables} == set(
        ("cameras", "images", "keypoints", "descriptors", "matches", "two_view_geometries")
    )

    missing_table = tmp_path / "missing-table.db"
    create_schema(missing_table, missing_table="matches")
    with pytest.raises(ValueError, match="missing required tables"):
        inspect_colmap_database(missing_table)

    missing_column = tmp_path / "missing-column.db"
    create_schema(missing_column, missing_column=("descriptors", "data"))
    with pytest.raises(ValueError, match="missing columns"):
        inspect_colmap_database(missing_column)

    malformed = tmp_path / "malformed.db"
    malformed.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(sqlite3.DatabaseError):
        inspect_colmap_database(malformed)


def test_database_probe_uses_owned_workspace_and_cleans_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "splatforge-colmap-db-owned"
    workspace.mkdir()
    monkeypatch.setattr(
        "splatforge.adapters.colmap_capabilities.tempfile.mkdtemp",
        lambda prefix: str(workspace),
    )
    monkeypatch.setattr(
        "splatforge.adapters.colmap_capabilities.tempfile.gettempdir",
        lambda: str(tmp_path),
    )

    def callback(request: ProcessRequest) -> ProcessResult:
        database = Path(request.argv[request.argv.index("--database_path") + 1])
        create_schema(database)
        return process_result(request)

    report = adapter(FakeRunner(callback))._probe_database(
        IDENTITY,
        COMMANDS,
        NOW,
        FreshnessPolicy(),
    )
    assert report.evidence.status == CapabilityStatus.AVAILABLE
    assert not workspace.exists()


def test_database_probe_missing_command_timeout_and_malformed_output() -> None:
    instance = adapter(FakeRunner())
    missing = instance._probe_database(
        IDENTITY,
        tuple(item for item in COMMANDS if item != "database_creator"),
        NOW,
        FreshnessPolicy(),
    )
    assert missing.evidence.status == CapabilityStatus.UNAVAILABLE
    assert missing.evidence.diagnostic_code == "colmap.operation_missing"

    timed_out = adapter(
        FakeRunner(lambda request: process_result(request, exit_code=None, timed_out=True))
    )._probe_database(IDENTITY, COMMANDS, NOW, FreshnessPolicy())
    assert timed_out.evidence.status == CapabilityStatus.UNKNOWN
    assert timed_out.evidence.diagnostic_code == "colmap.probe_timeout"

    def malformed(request: ProcessRequest) -> ProcessResult:
        database = Path(request.argv[request.argv.index("--database_path") + 1])
        database.write_text("not sqlite", encoding="utf-8")
        return process_result(request)

    incompatible = adapter(FakeRunner(malformed))._probe_database(
        IDENTITY,
        COMMANDS,
        NOW,
        FreshnessPolicy(),
    )
    assert incompatible.evidence.status == CapabilityStatus.UNAVAILABLE
    assert incompatible.evidence.diagnostic_code == "colmap.database_incompatible"


def test_deep_cpu_succeeds_while_gpu_failure_remains_separate() -> None:
    def callback(request: ProcessRequest) -> ProcessResult:
        if request.argv == ("help",):
            return process_result(request, stdout=TOP_HELP.encode())
        if request.argv == ("feature_extractor", "-h"):
            return process_result(request, stdout=FEATURE_HELP.encode())
        if request.argv[0] in {"exhaustive_matcher", "sequential_matcher"}:
            return process_result(request, stdout=MATCHER_HELP.encode())
        if request.argv[0] == "database_creator":
            database = Path(request.argv[request.argv.index("--database_path") + 1])
            create_schema(database)
            return process_result(request)
        if request.argv[0] == "feature_extractor":
            if request.argv[request.argv.index("--FeatureExtraction.use_gpu") + 1] == "1":
                return process_result(request, exit_code=2, stderr=b"CUDA no device")
            database = Path(request.argv[request.argv.index("--database_path") + 1])
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("INSERT INTO cameras VALUES (1, 0, 192, 192, X'', 0)")
                connection.execute("INSERT INTO images VALUES (1, 'probe.png', 1)")
                connection.execute("INSERT INTO keypoints VALUES (1, 1, 2, ?)", (bytes(8),))
                connection.execute("INSERT INTO descriptors VALUES (1, 1, 128, ?)", (bytes(128),))
                connection.commit()
            return process_result(request)
        raise AssertionError(request.argv)

    report = adapter(FakeRunner(callback)).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=True,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.database.evidence.status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.feature.sift.cpu").status == CapabilityStatus.AVAILABLE
    gpu = report.capability("colmap.feature.sift.gpu")
    assert gpu.status == CapabilityStatus.UNAVAILABLE
    assert gpu.diagnostic_code == "colmap.cuda_unavailable"


def test_deep_gpu_sift_smoke_success_requires_validated_database_output() -> None:
    def callback(request: ProcessRequest) -> ProcessResult:
        if request.argv == ("help",):
            return process_result(request, stdout=TOP_HELP.encode())
        if request.argv == ("feature_extractor", "-h"):
            return process_result(request, stdout=FEATURE_HELP.encode())
        if request.argv[0] in {"exhaustive_matcher", "sequential_matcher"}:
            return process_result(request, stdout=MATCHER_HELP.encode())
        if request.argv[0] == "database_creator":
            create_schema(Path(request.argv[request.argv.index("--database_path") + 1]))
            return process_result(request)
        if request.argv[0] == "feature_extractor":
            database = Path(request.argv[request.argv.index("--database_path") + 1])
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("INSERT INTO cameras VALUES (1, 0, 192, 192, X'', 0)")
                connection.execute("INSERT INTO images VALUES (1, 'probe.png', 1)")
                connection.execute("INSERT INTO keypoints VALUES (1, 1, 2, ?)", (bytes(8),))
                connection.execute("INSERT INTO descriptors VALUES (1, 1, 128, ?)", (bytes(128),))
                connection.commit()
            return process_result(request, stderr=b"Creating SIFT GPU feature extractor\n")
        raise AssertionError(request.argv)

    report = adapter(FakeRunner(callback)).probe(
        explicit_executable=Path("C:/Tools/colmap.exe"),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=True,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.capability("colmap.feature.sift.cpu").status == CapabilityStatus.AVAILABLE
    assert report.capability("colmap.feature.sift.gpu").status == CapabilityStatus.AVAILABLE


def probe_with_overrides(
    overrides: dict[tuple[str, ...], dict[str, object]],
    *,
    model_directory: Path | None = None,
) -> ColmapProbeReport:
    defaults = FakeRunner()

    def callback(request: ProcessRequest) -> ProcessResult:
        if request.argv in overrides:
            return process_result(request, **overrides[request.argv])
        return defaults.run(request)

    return adapter(FakeRunner(callback)).probe(
        explicit_executable=Path(IDENTITY.resolved_path),
        explicit_model_directory=model_directory,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )


@pytest.mark.parametrize(
    "flag,expected",
    [
        ("", CapabilityStatus.UNKNOWN),
        ("ONNX_ENABLED=OFF\n", CapabilityStatus.UNAVAILABLE),
        ("ONNX_ENABLED=ON\n", CapabilityStatus.AVAILABLE),
    ],
)
def test_learned_tokens_require_separate_onnx_build_evidence(flag, expected) -> None:
    top = TOP_HELP.replace("ONNX_ENABLED=ON\n", flag)
    report = probe_with_overrides({("help",): {"stdout": top.encode()}})
    assert report.capability("colmap.onnx").status == expected
    assert report.capability("colmap.feature.aliked").status != CapabilityStatus.AVAILABLE


def test_aliked_never_implies_lightglue_and_model_variants_do_not_cross(tmp_path: Path) -> None:
    (tmp_path / "aliked-n32.onnx").write_bytes(b"synthetic model")
    feature = FEATURE_HELP.replace("ALIKED_N16ROT, ALIKED_N32", "ALIKED_N16ROT")
    matcher = MATCHER_HELP.replace("SIFT_LIGHTGLUE,", "").replace("ALIKED_LIGHTGLUE,", "")
    report = probe_with_overrides(
        {
            ("feature_extractor", "-h"): {"stdout": feature.encode()},
            ("exhaustive_matcher", "-h"): {"stdout": matcher.encode()},
            ("sequential_matcher", "-h"): {"stdout": matcher.encode()},
        },
        model_directory=tmp_path,
    )
    assert report.capability("colmap.feature.aliked").status == CapabilityStatus.UNAVAILABLE
    assert report.capability("colmap.match.aliked_lightglue").status == CapabilityStatus.UNAVAILABLE
    assert report.capability("colmap.match.sift_lightglue").status == CapabilityStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"exit_code": 1, "stderr": b"no help"}, "colmap.probe_failed"),
        ({"timed_out": True, "exit_code": None}, "colmap.probe_timeout"),
        ({"stdout_truncated": True}, "colmap.probe_output_truncated"),
        ({"stderr_truncated": True}, "colmap.probe_output_truncated"),
        ({"exit_code": 0xC0000135}, "colmap.loader_failure"),
        ({"exit_code": 0xC0000005}, "colmap.probe_crash"),
    ],
)
def test_subcommand_failures_keep_codes_and_cannot_advertise_tokens(updates, code) -> None:
    report = probe_with_overrides(
        {("feature_extractor", "-h"): {"stdout": FEATURE_HELP.encode(), **updates}}
    )
    feature = report.command_discovery.subcommands[0]
    assert feature.evidence.diagnostic_code == code
    assert feature.tokens == ()
    assert report.capability("colmap.feature.sift.gpu").status != CapabilityStatus.AVAILABLE


def test_failed_matcher_help_is_not_concatenated_with_successful_help() -> None:
    report = probe_with_overrides(
        {
            ("exhaustive_matcher", "-h"): {"stdout": MATCHER_HELP.encode(), "exit_code": 1},
        }
    )
    by_command = {item.command: item for item in report.command_discovery.subcommands}
    assert by_command["exhaustive_matcher"].tokens == ()
    assert "SIFT_LIGHTGLUE" in by_command["sequential_matcher"].tokens
    assert report.capability("colmap.match.sift_bruteforce").status == CapabilityStatus.AVAILABLE


def test_unrecognized_enum_cannot_borrow_braces_from_the_next_option() -> None:
    text = (
        "--FeatureExtraction.type arg (=SIFT)\n"
        "--ImageReader.camera_model arg (=PINHOLE) {SIFT, ALIKED_N16ROT}\n"
    )
    assert parse_option_help(text, "FeatureExtraction.type").recognized is False
    assert parse_command_listing(TOP_HELP + "unrecognized command syntax here")[0] is False


def test_supported_legacy_sift_shape_is_recognized_without_version_guessing() -> None:
    legacy = (
        "-h [ --help ]\n--database_path arg\n--image_path arg\n"
        "--SiftExtraction.use_gpu arg (=1)\n"
        "--SiftExtraction.num_threads arg (=-1)\n"
        "--SiftExtraction.max_num_features arg (=8192)\n"
    )
    parsed = parse_option_help(legacy, "FeatureExtraction.type")
    assert parsed.profile == "legacy_sift_v1"
    assert parsed.tokens == ("SIFT",)
    assert "SiftExtraction.use_gpu" in parsed.option_names


def test_existing_path_boundary_failure_is_not_executable_missing() -> None:
    class BrokenRunner:
        def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult:
            raise ProcessBoundaryError("contained startup failed")

    report = adapter(BrokenRunner()).probe(
        explicit_executable=Path(IDENTITY.resolved_path),
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.binary.diagnostic_code == "colmap.process_boundary_failure"


def test_missing_colmap_adapter_returns_valid_complete_report() -> None:
    class MissingResolver(FakeResolver):
        def resolve(self, requested: str, *, environment=None) -> ExecutableIdentity:
            raise ExecutableNotFoundError("not installed")

    report = ColmapCapabilityAdapter(
        runner=FakeRunner(), resolver=MissingResolver(), environment={}
    ).probe(
        explicit_executable=None,
        explicit_model_directory=None,
        bundled_executable=None,
        bundled_model_directory=None,
        deep=False,
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.selected_executable is None
    assert report.binary.diagnostic_code == "colmap.executable_missing"
    assert report.capability("colmap.mapper.global").status == CapabilityStatus.UNAVAILABLE


def test_unconfirmed_teardown_stops_further_probes_and_retains_workspace() -> None:
    workspaces = []

    def callback(request: ProcessRequest) -> ProcessResult:
        workspaces.append(request.working_directory)
        return process_result(request).model_copy(update={"teardown_confirmed": False})

    runner = FakeRunner(callback)
    with pytest.raises(DoctorTeardownError, match="quarantine workspace"):
        adapter(runner).probe(
            explicit_executable=Path(IDENTITY.resolved_path),
            explicit_model_directory=None,
            bundled_executable=None,
            bundled_model_directory=None,
            deep=False,
            observed_at=NOW,
            freshness=FreshnessPolicy(),
        )
    assert len(runner.requests) == 1
    assert workspaces[0].is_dir()
    ColmapCapabilityAdapter._cleanup_workspace(workspaces[0])


def test_cleanup_refuses_redirects_and_protects_the_target(tmp_path: Path) -> None:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="splatforge-colmap-safety-"))
    target = tmp_path / "target"
    target.mkdir()
    protected = target / "keep.txt"
    protected.write_text("user data", encoding="utf-8")
    try:
        try:
            (root / "redirect").symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")
        with pytest.raises(OSError, match="redirect"):
            ColmapCapabilityAdapter._cleanup_workspace(root)
        assert protected.read_text(encoding="utf-8") == "user data"
    finally:
        if (root / "redirect").is_symlink():
            (root / "redirect").unlink()
        ColmapCapabilityAdapter._cleanup_workspace(root)


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"timed_out": True, "exit_code": None}, "colmap.probe_timeout"),
        ({"exit_code": 0xC0000135}, "colmap.loader_failure"),
        ({"exit_code": 0, "forced_tree_termination": True}, "colmap.probe_teardown_failed"),
        ({"exit_code": 0}, "colmap.cuda_probe_failed"),
    ],
)
def test_gpu_smoke_failure_does_not_publish_success_or_leave_probe_files(updates, code) -> None:
    workspaces = []

    def callback(request: ProcessRequest) -> ProcessResult:
        workspaces.append(request.working_directory)
        if request.argv[0] == "database_creator":
            create_schema(Path(request.argv[request.argv.index("--database_path") + 1]))
            return process_result(request)
        return process_result(request).model_copy(update=updates)

    report = adapter(FakeRunner(callback))._probe_sift(
        IDENTITY,
        COMMANDS,
        use_gpu=True,
        options=parse_option_help(FEATURE_HELP, "FeatureExtraction.type"),
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert report.status != CapabilityStatus.AVAILABLE
    assert report.diagnostic_code == code
    assert all(not path.exists() for path in workspaces)


def test_database_command_failure_and_cleanup_failure_have_bounded_diagnostics(monkeypatch) -> None:
    instance = adapter(
        FakeRunner(
            lambda request: process_result(
                request, exit_code=1, stderr=b"bounded database failure" * 1000
            )
        )
    )
    report = instance._probe_database(IDENTITY, COMMANDS, NOW, FreshnessPolicy())
    assert report.evidence.diagnostic_code == "colmap.database_creation_failed"
    assert len(report.evidence.message) <= 1024

    workspaces = []

    def callback(request: ProcessRequest) -> ProcessResult:
        workspaces.append(request.working_directory)
        create_schema(Path(request.argv[request.argv.index("--database_path") + 1]))
        return process_result(request)

    instance = adapter(FakeRunner(callback))
    cleanup = instance._cleanup_workspace

    def fail_cleanup(*args) -> None:
        raise OSError("simulated sharing violation")

    monkeypatch.setattr(instance, "_cleanup_workspace", fail_cleanup)
    try:
        failed = instance._probe_database(IDENTITY, COMMANDS, NOW, FreshnessPolicy())
        assert failed.evidence.diagnostic_code == "colmap.probe_cleanup_failed"
    finally:
        for workspace in workspaces:
            cleanup(workspace)


def test_unreadable_model_and_network_prohibition_are_reported(tmp_path: Path, monkeypatch) -> None:
    import socket

    model = tmp_path / "aliked-n16rot.onnx"
    model.write_bytes(b"synthetic")

    def forbid_network(*args, **kwargs):
        raise AssertionError("M5 must never use the network")

    def unreadable(path):
        raise PermissionError("model file is locked")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(ColmapCapabilityAdapter, "_hash_file", staticmethod(unreadable))
    report = probe_with_overrides({}, model_directory=tmp_path)
    record = next(item for item in report.models if item.role == "aliked.n16rot")
    assert record.evidence.diagnostic_code == "colmap.model_unreadable"
    assert record.compatibility_verified is False


def test_unknown_raw_features_never_mutate_the_method_catalog() -> None:
    from splatforge.core.builtin_methods import build_builtin_registry

    registry = build_builtin_registry()
    before = registry.list()
    report = probe_with_overrides({})
    assert "LOMA_B128" in report.command_discovery.feature_tokens
    assert registry.list() == before
    assert all("loma" not in method.id for method in registry.list())


def test_unknown_aliked_variant_remains_raw_with_unknown_model_mapping() -> None:
    feature = FEATURE_HELP.replace("ALIKED_N16ROT, ALIKED_N32", "ALIKED_FUTURE")
    report = probe_with_overrides({("feature_extractor", "-h"): {"stdout": feature.encode()}})
    assert "ALIKED_FUTURE" in report.command_discovery.feature_tokens
    assert report.capability("colmap.feature.aliked").status == CapabilityStatus.UNKNOWN


def test_unrecognized_binary_build_cannot_yield_available_typed_mapper() -> None:
    top = TOP_HELP.replace("COLMAP 4.2.1", "Unrecognized build")
    report = probe_with_overrides({("help",): {"stdout": top.encode()}})
    assert report.binary.status == CapabilityStatus.UNKNOWN
    assert report.capability("colmap.mapper.global").status == CapabilityStatus.UNKNOWN


@pytest.mark.parametrize(
    "stderr,code",
    [
        (
            b"Qt could not connect to display; OpenGL initialization failed",
            "colmap.opengl_display_unavailable",
        ),
        (b"generic feature computation failure", "colmap.cuda_probe_failed"),
    ],
)
def test_headless_display_failure_is_distinct_from_cuda_health(stderr, code) -> None:
    def callback(request: ProcessRequest) -> ProcessResult:
        if request.argv[0] == "database_creator":
            create_schema(Path(request.argv[request.argv.index("--database_path") + 1]))
            return process_result(request)
        return process_result(request, exit_code=1, stderr=stderr)

    result = adapter(FakeRunner(callback))._probe_sift(
        IDENTITY,
        COMMANDS,
        use_gpu=True,
        options=parse_option_help(FEATURE_HELP, "FeatureExtraction.type"),
        observed_at=NOW,
        freshness=FreshnessPolicy(),
    )
    assert result.status == CapabilityStatus.UNAVAILABLE
    assert result.diagnostic_code == code


@pytest.mark.parametrize("rows", [None, "invalid count"])
def test_malformed_native_feature_rows_are_output_errors_not_type_errors(
    tmp_path: Path, rows
) -> None:
    database = tmp_path / "malformed-features.db"
    create_schema(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO cameras VALUES (1, 0, 192, 192, X'', 0)")
        connection.execute("INSERT INTO images VALUES (1, 'probe.png', 1)")
        connection.execute("INSERT INTO keypoints VALUES (1, ?, 2, X'00')", (rows,))
        connection.execute("INSERT INTO descriptors VALUES (1, 1, 128, X'00')")
        connection.commit()
    with pytest.raises(ValueError, match="not integers"):
        validate_sift_probe_output(database)
