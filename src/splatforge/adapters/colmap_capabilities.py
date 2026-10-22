"""Contained COLMAP discovery and disposable compatibility probes."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse

from PIL import Image, ImageDraw

from splatforge.adapters.colmap_help import (
    ParsedOptionHelp,
    parse_build_support,
    parse_command_listing,
    parse_option_help,
)
from splatforge.adapters.colmap_runtime import (
    discover_runtime_layout,
    native_from_locator,
    scoped_runtime_environment,
)
from splatforge.adapters.process_runner import (
    ExecutableNotFoundError,
    ExecutableResolver,
    LocalProcessRunner,
    ProcessBoundaryError,
    ProcessCleanupError,
    ProcessRequest,
)
from splatforge.application.doctor_contracts import (
    DoctorTeardownError,
)
from splatforge.core.capabilities import (
    CapabilityEvidence,
    CapabilityStatus,
    ColmapProbeReport,
    CommandDiscovery,
    DatabaseCompatibility,
    DatabaseTableEvidence,
    EvidenceDetail,
    ExecutableSelection,
    ExecutableSource,
    FreshnessPolicy,
    ModelEvidence,
    SubcommandDiscovery,
    alternative_status,
    required_status,
)
from splatforge.core.media import ExecutableIdentity
from splatforge.core.process import ProcessResult

if TYPE_CHECKING:
    from splatforge.core.features import FeatureSettings
    from splatforge.core.matching import MatcherSettings

_REQUIRED_COMMANDS = (
    "database_creator",
    "feature_extractor",
    "exhaustive_matcher",
    "sequential_matcher",
    "global_mapper",
    "view_graph_calibrator",
    "mapper",
    "hierarchical_mapper",
    "model_converter",
    "matches_importer",
    "geometric_verifier",
)
_REQUIRED_SCHEMA = {
    "cameras": {"camera_id", "model", "width", "height", "params", "prior_focal_length"},
    "images": {"image_id", "name", "camera_id"},
    "keypoints": {"image_id", "rows", "cols", "data"},
    "descriptors": {"image_id", "rows", "cols", "data"},
    "matches": {"pair_id", "rows", "cols", "data"},
    "two_view_geometries": {"pair_id", "rows", "cols", "data", "config", "F", "E", "H"},
}
_MODEL_OPTIONS = {
    "aliked.n16rot": "AlikedExtraction.n16rot_model_path",
    "aliked.n32": "AlikedExtraction.n32_model_path",
    "lightglue.sift": "SiftMatching.lightglue_model_path",
    "lightglue.aliked": "AlikedMatching.lightglue_model_path",
    "bruteforce.aliked": "AlikedMatching.bruteforce_model_path",
    "loma.detector": "LomaExtraction.detector_model_path",
    "loma.b": "LomaExtraction.descriptor_model_path",
    "loma.b128": "LomaExtraction.descriptor_b128_model_path",
    "bruteforce.loma": "LomaMatching.brute_force_model_path",
    **{f"loma.matcher.{v}": f"LomaMatching.{v}_model_path" for v in ("b", "b128", "r", "l", "g")},
}
_CAPABILITY_IDS = (
    *(f"colmap.operation.{operation}" for operation in _REQUIRED_COMMANDS),
    "colmap.feature.sift.cpu",
    "colmap.feature.sift.gpu",
    "gpu.colmap_cuda",
    "colmap.onnx",
    "colmap.feature.aliked",
    *(f"colmap.feature.{variant}.{device}"
      for variant in ("aliked_n16rot", "aliked_n32", "loma_b", "loma_b128")
      for device in ("cpu", "gpu")),
    "colmap.match.sift_bruteforce",
    "colmap.match.aliked_bruteforce",
    "colmap.match.sift_lightglue",
    "colmap.match.aliked_lightglue",
    *(f"colmap.match.{token}.{device}" for token in (
        "sift_bruteforce", "sift_lightglue", "aliked_bruteforce", "aliked_lightglue",
        "loma_bruteforce", "loma_b", "loma_b128", "loma_r", "loma_l", "loma_g",
    ) for device in ("cpu", "gpu")),
    "colmap.verification.standalone",
    "colmap.mapper.global",
    "colmap.mapper.global.version",
    "colmap.mapper.global.integration",
    "colmap.calibration.view_graph",
    "colmap.mapper.incremental",
    "colmap.mapper.hierarchical",
)


class _Runner(Protocol):
    def run(self, request: ProcessRequest, *, cancellation=None) -> ProcessResult: ...


class ColmapExecutableLocator:
    def __init__(
        self,
        resolver: ExecutableResolver,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._resolver = resolver
        self._environment = os.environ if environment is None else environment

    def locate(
        self,
        *,
        explicit: Path | None,
        bundled: Path | None,
    ) -> ExecutableSelection:
        configured = self._environment.get("SPLATFORGE_COLMAP")
        if explicit is not None:
            source, requested = ExecutableSource.EXPLICIT, str(explicit)
        elif configured:
            source, requested = ExecutableSource.ENVIRONMENT, configured
        elif bundled is not None:
            source, requested = ExecutableSource.BUNDLED, str(bundled)
        else:
            source, requested = ExecutableSource.PATH, "colmap"
        candidate = Path(requested)
        if (
            source != ExecutableSource.PATH
            and candidate.parent != Path(".")
            and not candidate.is_absolute()
        ):
            raise ExecutableNotFoundError("Configured COLMAP executable path must be absolute")
        native_requested = requested
        if os.name == "nt" and candidate.suffix.lower() in {".bat", ".cmd"}:
            if source == ExecutableSource.PATH or candidate.name.lower() != "colmap.bat":
                raise ProcessBoundaryError(
                    "Select native COLMAP or the official COLMAP.bat locator"
                )
            if not candidate.is_absolute():
                raise ExecutableNotFoundError("COLMAP.bat installation locator must be absolute")
            native_requested = str(native_from_locator(candidate))
        lookup_environment = (
            {key.upper(): value for key, value in self._environment.items()}
            if os.name == "nt"
            else self._environment
        )
        identity = self._resolver.resolve(native_requested, environment=lookup_environment)
        if os.name == "nt" and Path(identity.resolved_path).suffix.lower() not in {".exe", ".com"}:
            raise ProcessBoundaryError(
                "Select the native COLMAP executable (colmap.exe), not a batch/script wrapper"
            )
        return ExecutableSelection(
            source=source,
            requested=requested,
            identity=identity,
            runtime_layout=discover_runtime_layout(Path(identity.resolved_path)),
        )


class ColmapCapabilityAdapter:
    def __init__(
        self,
        *,
        runner: _Runner | None = None,
        resolver: ExecutableResolver | None = None,
        environment: Mapping[str, str] | None = None,
        version_help_timeout_seconds: float = 10.0,
        database_timeout_seconds: float = 15.0,
        smoke_timeout_seconds: float = 45.0,
        maximum_output_bytes: int = 256 * 1024,
    ) -> None:
        self._resolver = resolver or ExecutableResolver()
        self._runner = runner or LocalProcessRunner(self._resolver)
        self._environment = os.environ if environment is None else environment
        self._locator = ColmapExecutableLocator(
            self._resolver,
            environment=self._environment,
        )
        self._version_help_timeout = version_help_timeout_seconds
        self._database_timeout = database_timeout_seconds
        self._smoke_timeout = smoke_timeout_seconds
        self._maximum_output = maximum_output_bytes

    def verify_expected_identity(self, expected: ExecutableIdentity) -> bool:
        return self._resolver.verify_expected_identity(expected)

    def verify_model_identities(self, models: tuple[ModelEvidence, ...]) -> bool:
        for model in models:
            if model.resolved_path:
                path = Path(model.resolved_path)
                try:
                    if model.sha256 is None:
                        if path.exists():
                            return False
                    elif (path.is_symlink() or path.is_junction()
                          or path.stat().st_size != model.size
                          or self._hash_file(path) != model.sha256):
                        return False
                except OSError:
                    return False
        return True

    def configuration_key(self) -> tuple[str, ...]:
        return tuple(
            self._environment.get(name, "")
            for name in (
                "SPLATFORGE_COLMAP",
                "SPLATFORGE_COLMAP_MODEL_DIR",
                "LOCALAPPDATA",
                "PATH",
                "PATHEXT",
                "QT_PLUGIN_PATH",
                "QT_QPA_PLATFORM_PLUGIN_PATH",
            )
        )

    def probe(
        self,
        *,
        explicit_executable: Path | None,
        explicit_model_directory: Path | None,
        bundled_executable: Path | None,
        bundled_model_directory: Path | None,
        deep: bool,
        observed_at: datetime,
        freshness: FreshnessPolicy,
        feature_settings: FeatureSettings | None = None,
        matching_settings: MatcherSettings | None = None,
        verification_only: bool = False,
    ) -> ColmapProbeReport:
        try:
            selection = self._locator.locate(
                explicit=explicit_executable,
                bundled=bundled_executable,
            )
        except ExecutableNotFoundError as exc:
            return self._missing_report(
                message=str(exc),
                deep=deep,
                observed_at=observed_at,
                freshness=freshness,
            )
        except (ProcessBoundaryError, OSError) as exc:
            return self._missing_report(
                message=f"Cannot establish executable file identity: {exc}",
                deep=deep,
                observed_at=observed_at,
                freshness=freshness,
                code="colmap.identity_unavailable",
                status=CapabilityStatus.UNKNOWN,
            )
        environment = scoped_runtime_environment(selection.runtime_layout, self._environment)
        try:
            top = self._run(
                selection.identity.resolved_path,
                ("help",),
                self._version_help_timeout,
                environment=environment,
            )
        except (ProcessBoundaryError, OSError) as exc:
            return self._failed_start_report(
                selection=selection,
                message=str(exc),
                deep=deep,
                observed_at=observed_at,
                freshness=freshness,
                code="colmap.process_boundary_failure",
                status=CapabilityStatus.UNKNOWN,
            )
        problem = self._process_problem(top, operation="help")
        if problem is not None:
            status, code, message = problem
            return self._failed_start_report(
                selection=selection,
                message=message,
                code=code,
                status=status,
                deep=deep,
                observed_at=observed_at,
                freshness=freshness,
            )
        if not self._same_identity(selection.identity, top.executable):
            return self._failed_start_report(
                selection=selection,
                message="COLMAP executable changed during discovery",
                code="colmap.identity_changed",
                status=CapabilityStatus.UNKNOWN,
                deep=deep,
                observed_at=observed_at,
                freshness=freshness,
            )
        combined = self._combined_text(top)
        version_line = next(
            (
                line.strip()[:1024]
                for line in combined.splitlines()
                if re.match(r"^COLMAP \d+\.\d+(?:\.\d+)?\b", line.strip())
            ),
            None,
        )
        identity = top.executable.model_copy(update={"version_line": version_line})
        selection = selection.model_copy(update={"identity": identity})
        binary_status = CapabilityStatus.AVAILABLE if version_line else CapabilityStatus.UNKNOWN
        binary = self._evidence(
            "colmap.binary",
            binary_status,
            "colmap.binary_available" if version_line else "colmap.version_unrecognized",
            (
                f"COLMAP executable is operational: {version_line}"
                if version_line
                else "Executable ran, but its COLMAP version/build line was not recognized"
            ),
            observed_at,
            freshness.static_cli_seconds,
            identity,
        )
        listing_ok, commands = parse_command_listing(combined)
        command_evidence = self._evidence(
            "colmap.commands",
            CapabilityStatus.AVAILABLE if listing_ok else CapabilityStatus.UNKNOWN,
            "colmap.commands_discovered" if listing_ok else "colmap.help_unrecognized",
            (
                f"Discovered {len(commands)} top-level COLMAP operations"
                if listing_ok
                else "COLMAP help format was not recognized; command support is unknown"
            ),
            observed_at,
            freshness.static_cli_seconds,
            identity,
            details=(("top_level_excerpt", self._excerpt(combined)),),
        )
        from splatforge.adapters.mapping_capabilities import supported_global_version

        help_results = tuple(
            self._probe_subcommand_help(
                identity, command, commands, listing_ok, observed_at, freshness, environment
            )
            for command in ("feature_extractor", "exhaustive_matcher", "sequential_matcher",
                            "matches_importer", "geometric_verifier") +
                           (("global_mapper", "view_graph_calibrator")
                            if supported_global_version(version_line) else ())
        )
        feature_parsed = help_results[0][2]
        matcher_parsed = next(
            (item[2] for item in (help_results[3],help_results[1],help_results[2])
             if item[2].recognized),
            ParsedOptionHelp(False, (), (), ()),
        )
        parsed_helps = tuple(item[2] for item in help_results)
        option_names = tuple(
            dict.fromkeys(name for parsed in parsed_helps for name in parsed.option_names)
        )
        model_defaults = tuple(
            dict(item for parsed in parsed_helps for item in parsed.model_defaults).items()
        )
        discovery = CommandDiscovery(
            evidence=command_evidence,
            commands=commands,
            feature_tokens=feature_parsed.tokens,
            matcher_tokens=tuple(
                dict.fromkeys(token for parsed in parsed_helps[1:] for token in parsed.tokens)
            ),
            option_names=option_names[:512],
            model_defaults=tuple(
                EvidenceDetail(key=key, value=value[:1024]) for key, value in model_defaults[:32]
            ),
            subcommands=tuple(item[1] for item in help_results),
            bounded_excerpts=(
                EvidenceDetail(key="top_level", value=self._excerpt(combined)),
                *(
                    EvidenceDetail(key=item[1].command, value=self._excerpt(item[0]))
                    for item in help_results
                    if item[0]
                ),
            ),
        )
        model_root, model_source = self._resolve_model_root(
            explicit_model_directory,
            bundled_model_directory,
        )
        models = self._inspect_models(
            model_defaults,
            model_root,
            model_source,
            identity,
            observed_at,
            freshness,
        )
        database = (
            self._probe_database(identity, commands, observed_at, freshness, environment)
            if deep
            else self._not_run_database(identity, observed_at, freshness)
        )
        capabilities = self._build_capabilities(
            identity=identity,
            commands=commands,
            listing_ok=listing_ok,
            feature=feature_parsed,
            matcher=matcher_parsed,
            models=models,
            database=database,
            deep=deep and not (verification_only or matching_settings is not None
                              or (feature_settings is not None
                                  and feature_settings.variant != "SIFT")),
            observed_at=observed_at,
            freshness=freshness,
            build_text=combined,
            environment=environment,
        )
        from splatforge.adapters.mapping_capabilities import mapping_evidence

        capabilities = mapping_evidence(self, capabilities, help_results, identity,
                                        observed_at, freshness)
        # M7a extends the existing discovery/probe lifecycle, including containment.
        from splatforge.adapters.learned_feature_probe import probe_feature_routes
        from splatforge.core.features import SiftExtractionSettings

        capabilities, models = probe_feature_routes(
            self, capabilities=capabilities, models=models, feature=feature_parsed,
            database=database, identity=identity, deep=deep, observed_at=observed_at,
            freshness=freshness, environment=environment,
            cuda_build=parse_build_support(combined, "CUDA"),
            requested=(
                SiftExtractionSettings()
                if verification_only or matching_settings is not None
                else feature_settings
            ),
        )
        from splatforge.adapters.matching_capabilities import probe_matching_routes

        capabilities, models = probe_matching_routes(
            self, capabilities=capabilities, models=models, helps=help_results,
            database=database, identity=identity, deep=deep, observed_at=observed_at,
            freshness=freshness, environment=environment, requested=matching_settings,
            feature_settings=feature_settings,
            verification_only=verification_only,
            cuda_build=parse_build_support(combined, "CUDA"),
        )
        if binary.status != CapabilityStatus.AVAILABLE:
            capabilities = tuple(
                item.model_copy(
                    update={
                        "status": CapabilityStatus.UNKNOWN,
                        "diagnostic_code": "colmap.binary_prerequisite_unverified",
                        "message": (
                            "COLMAP version/build identity is unrecognized; re-probe a known CLI"
                        ),
                    }
                )
                if item.status == CapabilityStatus.AVAILABLE
                else item
                for item in capabilities
            )
        if not self.verify_expected_identity(identity):
            return self._failed_start_report(
                selection=selection.model_copy(
                    update={"identity": identity.model_copy(update={"version_line": None})}
                ),
                message="COLMAP changed before Doctor could finish; re-run Doctor",
                code="colmap.identity_changed",
                status=CapabilityStatus.UNKNOWN,
                deep=deep,
                observed_at=observed_at,
                freshness=freshness,
            )
        return ColmapProbeReport(
            selected_executable=selection,
            binary=binary,
            command_discovery=discovery,
            capabilities=capabilities,
            database=database,
            models=models,
            deep=deep,
        )

    def _build_capabilities(
        self,
        *,
        identity: ExecutableIdentity,
        commands: tuple[str, ...],
        listing_ok: bool,
        feature: ParsedOptionHelp,
        matcher: ParsedOptionHelp,
        models: tuple[ModelEvidence, ...],
        database: DatabaseCompatibility,
        deep: bool,
        observed_at: datetime,
        freshness: FreshnessPolicy,
        build_text: str,
        environment: Mapping[str, str],
    ) -> tuple[CapabilityEvidence, ...]:
        results: list[CapabilityEvidence] = []
        for operation in _REQUIRED_COMMANDS:
            results.append(
                self._presence_evidence(
                    f"colmap.operation.{operation}",
                    operation,
                    commands,
                    listing_ok,
                    identity,
                    observed_at,
                    freshness,
                )
            )
        if listing_ok and "feature_extractor" not in commands:
            feature = ParsedOptionHelp(True, (), (), ())
        if listing_ok and not {"exhaustive_matcher", "sequential_matcher"}.intersection(commands):
            matcher = ParsedOptionHelp(True, (), (), ())
        feature_status = self._token_status(feature, "SIFT")
        gpu_options = {"FeatureExtraction.use_gpu", "SiftExtraction.use_gpu"}
        smoke_options_known = bool(gpu_options.intersection(feature.option_names))
        smoke_options_known &= {"database_path", "image_path"} <= set(feature.option_names)
        if feature_status == CapabilityStatus.AVAILABLE and deep and smoke_options_known:
            cpu = self._probe_sift(
                identity,
                commands,
                use_gpu=False,
                environment=environment,
                options=feature,
                observed_at=observed_at,
                freshness=freshness,
            )
        elif feature_status == CapabilityStatus.AVAILABLE:
            cpu = self._not_run(
                "colmap.feature.sift.cpu",
                "CPU SIFT functional probe requires --deep",
                identity,
                observed_at,
                freshness,
            )
        else:
            cpu = self._static_failure(
                "colmap.feature.sift.cpu",
                feature_status,
                "SIFT was not positively discovered in feature_extractor help",
                identity,
                observed_at,
                freshness,
            )
        results.append(cpu)
        gpu_option = any(
            name in feature.option_names
            for name in ("FeatureExtraction.use_gpu", "SiftExtraction.use_gpu")
        )
        if (
            feature_status == CapabilityStatus.AVAILABLE
            and gpu_option
            and deep
            and smoke_options_known
            and " with HIP" not in build_text
        ):
            gpu = self._probe_sift(
                identity,
                commands,
                use_gpu=True,
                environment=environment,
                options=feature,
                observed_at=observed_at,
                freshness=freshness,
            )
        elif feature_status == CapabilityStatus.AVAILABLE and gpu_option:
            gpu = self._not_run(
                "colmap.feature.sift.gpu",
                "COLMAP GPU SIFT health requires --deep; generic GPU detection is insufficient",
                identity,
                observed_at,
                freshness,
            )
        elif feature_status == CapabilityStatus.UNKNOWN:
            gpu = self._static_failure(
                "colmap.feature.sift.gpu",
                CapabilityStatus.UNKNOWN,
                "Feature help was not recognized, so GPU SIFT support is unknown",
                identity,
                observed_at,
                freshness,
            )
        else:
            gpu = self._static_failure(
                "colmap.feature.sift.gpu",
                CapabilityStatus.UNAVAILABLE,
                "SIFT or its GPU option is not exposed by this build",
                identity,
                observed_at,
                freshness,
            )
        results.append(gpu)
        cuda_build = parse_build_support(build_text, "CUDA")
        cuda_status = gpu.status if cuda_build == CapabilityStatus.AVAILABLE else cuda_build
        results.append(
            self._evidence(
                "gpu.colmap_cuda",
                cuda_status,
                (
                    "colmap.cuda_available"
                    if cuda_status == CapabilityStatus.AVAILABLE
                    else "colmap.cuda_unavailable"
                    if cuda_status == CapabilityStatus.UNAVAILABLE
                    else "colmap.cuda_unverified"
                ),
                (
                    "COLMAP CUDA build and GPU SIFT functional probe are verified"
                    if cuda_status == CapabilityStatus.AVAILABLE
                    else "CUDA health requires explicit build evidence and a successful GPU probe"
                ),
                observed_at,
                freshness.resource_health_seconds,
                identity,
            )
        )
        learned_tokens = {
            token
            for token in (*feature.tokens, *matcher.tokens)
            if token.startswith("ALIKED") or "LIGHTGLUE" in token or token.startswith("LOMA")
        }
        if not feature.recognized or not matcher.recognized:
            onnx_status = CapabilityStatus.UNKNOWN
            onnx_code = "colmap.help_unrecognized"
            onnx_message = "Learned-route build support cannot be determined from help"
        elif learned_tokens:
            onnx_status = parse_build_support(build_text, "ONNX")
            onnx_code = (
                "colmap.onnx_advertised"
                if onnx_status == CapabilityStatus.AVAILABLE
                else "colmap.onnx_unavailable"
                if onnx_status == CapabilityStatus.UNAVAILABLE
                else "colmap.onnx_unverified"
            )
            onnx_message = (
                "Explicit ONNX build evidence was observed; learned inference is not tested in M5"
                if onnx_status == CapabilityStatus.AVAILABLE
                else "Learned tokens do not verify ONNX; explicit build/runtime evidence is missing"
            )
        else:
            onnx_status = CapabilityStatus.UNAVAILABLE
            onnx_code = "colmap.onnx_unavailable"
            onnx_message = "COLMAP help advertises no ONNX-dependent learned routes"
        onnx = self._evidence(
            "colmap.onnx",
            onnx_status,
            onnx_code,
            onnx_message,
            observed_at,
            freshness.static_cli_seconds,
            identity,
            details=(("learned_tokens", ",".join(sorted(learned_tokens))),),
        )
        results.append(onnx)
        model_by_role = {item.role: item.evidence for item in models}
        variant_models = {
            "ALIKED_N16ROT": "aliked.n16rot",
            "ALIKED_N32": "aliked.n32",
        }
        aliked_model_status = self._any_status(
            tuple(
                model_by_role[role].status
                for token, role in variant_models.items()
                if token in feature.tokens and role in model_by_role
            )
        )
        aliked_token_status = self._any_token_status(
            feature,
            lambda value: value.startswith("ALIKED"),
        )
        results.append(
            self._composite(
                "colmap.feature.aliked",
                (aliked_token_status, onnx_status, aliked_model_status),
                "ALIKED extractor, ONNX build evidence, and a concrete model are available",
                "ALIKED is not currently usable; inspect token, ONNX, and model evidence",
                identity,
                observed_at,
                freshness,
            )
        )
        sift_bf = self._token_capability(
            "colmap.match.sift_bruteforce",
            matcher,
            "SIFT_BRUTEFORCE",
            identity,
            observed_at,
            freshness,
        )
        results.append(sift_bf)
        aliked_bf_token = self._token_status(matcher, "ALIKED_BRUTEFORCE")
        results.append(
            self._composite(
                "colmap.match.aliked_bruteforce",
                (
                    aliked_bf_token,
                    onnx_status,
                    model_by_role["bruteforce.aliked"].status,
                ),
                "ALIKED brute-force matching prerequisites are available",
                "ALIKED brute-force matching prerequisites are incomplete",
                identity,
                observed_at,
                freshness,
            )
        )
        for capability_id, token, model_role in (
            ("colmap.match.sift_lightglue", "SIFT_LIGHTGLUE", "lightglue.sift"),
            ("colmap.match.aliked_lightglue", "ALIKED_LIGHTGLUE", "lightglue.aliked"),
        ):
            dependencies = [
                self._token_status(matcher, token),
                onnx_status,
                model_by_role.get(
                    model_role,
                    self._evidence(
                        f"colmap.model.{model_role}",
                        CapabilityStatus.UNKNOWN,
                        "colmap.model_contract_unknown",
                        "No concrete model-path contract was discovered",
                        observed_at,
                        freshness.static_cli_seconds,
                        identity,
                    ),
                ).status,
            ]
            if token.startswith("ALIKED"):
                dependencies.append(aliked_model_status)
            results.append(
                self._composite(
                    capability_id,
                    tuple(dependencies),
                    f"{token} prerequisites are available",
                    f"{token} prerequisites are incomplete",
                    identity,
                    observed_at,
                    freshness,
                )
            )
        for capability_id, operation in (
            ("colmap.mapper.global", "global_mapper"),
            ("colmap.mapper.incremental", "mapper"),
            ("colmap.mapper.hierarchical", "hierarchical_mapper"),
        ):
            results.append(
                self._presence_evidence(
                    capability_id,
                    operation,
                    commands,
                    listing_ok,
                    identity,
                    observed_at,
                    freshness,
                )
            )
        return tuple(results)

    def _probe_subcommand_help(
        self,
        identity: ExecutableIdentity,
        command: str,
        commands: tuple[str, ...],
        listing_ok: bool,
        observed_at: datetime,
        freshness: FreshnessPolicy,
        environment: Mapping[str, str],
    ) -> tuple[str, SubcommandDiscovery, ParsedOptionHelp]:
        text = ""
        parsed = ParsedOptionHelp(False, (), (), ())
        if command not in commands:
            status = CapabilityStatus.UNAVAILABLE if listing_ok else CapabilityStatus.UNKNOWN
            code = "colmap.operation_missing" if listing_ok else "colmap.help_unrecognized"
            message = f"Operation {command} was not positively discovered"
        else:
            try:
                result = self._run(
                    identity.resolved_path,
                    (command, "-h"),
                    self._version_help_timeout,
                    environment=environment,
                )
            except (ProcessBoundaryError, OSError) as exc:
                status, code, message = (
                    CapabilityStatus.UNKNOWN,
                    "colmap.process_boundary_failure",
                    str(exc),
                )
            else:
                text = self._combined_text(result)
                problem = self._process_problem(result, operation=f"{command} help")
                if not self._same_identity(identity, result.executable):
                    status, code, message = (
                        CapabilityStatus.UNKNOWN,
                        "colmap.identity_changed",
                        "COLMAP executable changed during subcommand help",
                    )
                elif problem is not None:
                    status, code, message = problem
                else:
                    option = ("GlobalMapper" if command == "global_mapper" else
                              "ViewGraphCalibration" if command == "view_graph_calibrator" else
                              "TwoViewGeometry" if command == "geometric_verifier" else (
                        "FeatureExtraction.type"
                        if command == "feature_extractor"
                        else "FeatureMatching.type"
                    )
                    )
                    parsed = parse_option_help(text, option)
                    status = (
                        CapabilityStatus.AVAILABLE
                        if parsed.recognized
                        else CapabilityStatus.UNKNOWN
                    )
                    code = "colmap.help_parsed" if parsed.recognized else "colmap.help_unrecognized"
                    message = (
                        f"Parsed {command} options with {parsed.profile}"
                        if parsed.recognized
                        else f"Unrecognized {command} help; support is unknown"
                    )
        evidence = self._evidence(
            f"colmap.help.{command}",
            status,
            code,
            message,
            observed_at,
            freshness.static_cli_seconds,
            identity,
            details=(("excerpt", self._excerpt(text)),),
        )
        return (
            text,
            SubcommandDiscovery(
                command=command,
                evidence=evidence,
                parser_profile=parsed.profile,
                tokens=parsed.tokens,
                option_names=parsed.option_names,
                model_defaults=tuple(
                    EvidenceDetail(key=name, value=value)
                    for name, value in parsed.model_defaults[:32]
                ),
            ),
            parsed,
        )

    def _resolve_model_root(
        self,
        explicit: Path | None,
        bundled: Path | None,
    ) -> tuple[Path | None, str]:
        configured = self._environment.get("SPLATFORGE_COLMAP_MODEL_DIR")
        if explicit is not None:
            return explicit, "explicit"
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                return None, "environment_relative_rejected"
            return path, "environment"
        if bundled is not None:
            return bundled, "bundled"
        local = self._environment.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "SplatForge" / "models" / "colmap", "local_default"

    def _inspect_models(
        self,
        defaults: tuple[tuple[str, str], ...],
        root: Path | None,
        source: str,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> tuple[ModelEvidence, ...]:
        by_option = dict(defaults)
        records = []
        for role, option in _MODEL_OPTIONS.items():
            default = by_option.get(option)
            expected_name = None
            expected_digest = None
            if default:
                parts = default.split(";")
                parsed = urlparse(parts[0])
                expected_name = (parts[1] if len(parts) == 3 else
                                 Path(parsed.path or parts[0]).name) or None
                if len(parts) == 3 and re.fullmatch(r"[0-9a-f]{64}", parts[2]):
                    expected_digest = parts[2]
                if expected_name and (Path(expected_name).name != expected_name
                                      or "/" in expected_name or "\\" in expected_name):
                    expected_name = None
            if expected_name is None:
                evidence = self._evidence(
                    f"colmap.model.{role}",
                    CapabilityStatus.UNKNOWN,
                    "colmap.model_contract_unknown",
                    f"COLMAP help did not expose a concrete default for {option}",
                    observed_at,
                    freshness.static_cli_seconds,
                    identity,
                )
                records.append(
                    ModelEvidence(
                        role=role,
                        configured_source=source,
                        expected_name=None,
                        expected_root=str(root) if root else None,
                        evidence=evidence,
                    )
                )
                continue
            if root is None:
                evidence = self._evidence(
                    f"colmap.model.{role}",
                    CapabilityStatus.UNAVAILABLE,
                    "colmap.model_missing",
                    (
                        f"{role}: configure --colmap-model-dir or SPLATFORGE_COLMAP_MODEL_DIR "
                        f"to an absolute local directory containing {expected_name}; "
                        f"expected SHA-256: {expected_digest or 'reference digest unavailable'}; "
                        "no download was attempted"
                    ),
                    observed_at,
                    freshness.static_cli_seconds,
                    identity,
                )
                records.append(
                    ModelEvidence(
                        role=role,
                        configured_source=source,
                        expected_name=expected_name,
                        expected_sha256=expected_digest,
                        source_uri=default,
                        evidence=evidence,
                    )
                )
                continue
            candidate = root / expected_name
            # COLMAP 4.2.1 stores already provisioned cache files as SHA-name.
            # Inspect only this exact alternative, within the configured root.
            if (expected_digest and not candidate.exists()
                    and not candidate.is_symlink()):
                cached = root / f"{expected_digest}-{expected_name}"
                if cached.exists():
                    candidate = cached
            digest = None
            observed_size = None
            try:
                if not root.is_absolute() or "://" in str(root) or ";" in str(root):
                    raise OSError("model root must be an absolute local directory")
                if root.is_symlink() or root.is_junction() or candidate.is_symlink():
                    raise OSError("redirected model roots/files require explicit relinking")
                resolved = candidate.resolve(strict=True)
                if resolved.parent != root.resolve(strict=True) or not resolved.is_file():
                    raise OSError("not a regular file in the configured model root")
                stat_before = resolved.stat()
                if not 0 < stat_before.st_size <= 8 * 1024**3:
                    raise OSError("model file is empty or exceeds the supported size bound")
                digest = self._hash_file(resolved)
                stat_after = resolved.stat()
                if (
                    stat_before.st_size,
                    stat_before.st_mtime_ns,
                    stat_before.st_ino,
                    stat_before.st_ctime_ns,
                ) != (
                    stat_after.st_size,
                    stat_after.st_mtime_ns,
                    stat_after.st_ino,
                    stat_after.st_ctime_ns,
                ):
                    raise OSError("model changed while hashing")
                observed_size = stat_after.st_size
                if expected_digest is not None and digest != expected_digest:
                    raise OSError("model SHA-256 differs from the backend's pinned model contract")
            except OSError as exc:
                evidence = self._evidence(
                    f"colmap.model.{role}",
                    CapabilityStatus.UNAVAILABLE,
                    "colmap.model_unreadable",
                    f"{role}: {candidate} ({exc}); expected SHA-256: "
                    f"{expected_digest or 'reference digest unavailable'}; configure "
                    "--colmap-model-dir or SPLATFORGE_COLMAP_MODEL_DIR; no download attempted",
                    observed_at,
                    freshness.static_cli_seconds,
                    identity,
                )
                records.append(
                    ModelEvidence(
                        role=role,
                        configured_source=source,
                        expected_name=expected_name,
                        expected_root=str(root),
                        checked_path=str(candidate.absolute()),
                        resolved_path=str(candidate.absolute()),
                        expected_sha256=expected_digest,
                        source_uri=default,
                        sha256=digest if observed_size is not None else None,
                        size=observed_size,
                        evidence=evidence,
                    )
                )
                continue
            evidence = self._evidence(
                f"colmap.model.{role}",
                CapabilityStatus.AVAILABLE,
                "colmap.model_available",
                f"Concrete model evidence recorded for {role}; "
                + ("backend reference SHA-256 verified" if expected_digest else
                   "reference digest unavailable; observed local SHA-256 recorded"),
                observed_at,
                freshness.static_cli_seconds,
                identity,
            )
            records.append(
                ModelEvidence(
                    role=role,
                    configured_source=source,
                    expected_name=expected_name,
                    expected_root=str(root),
                    checked_path=str(candidate.absolute()),
                    resolved_path=str(resolved),
                    size=stat_after.st_size,
                    sha256=digest,
                    source_uri=default,
                    expected_sha256=expected_digest,
                    evidence=evidence,
                )
            )
        return tuple(records)

    def _probe_database(
        self,
        identity: ExecutableIdentity,
        commands: tuple[str, ...],
        observed_at: datetime,
        freshness: FreshnessPolicy,
        environment: Mapping[str, str],
    ) -> DatabaseCompatibility:
        if "database_creator" not in commands:
            return DatabaseCompatibility(
                evidence=self._evidence(
                    "colmap.database",
                    CapabilityStatus.UNAVAILABLE,
                    "colmap.operation_missing",
                    "COLMAP database_creator is unavailable",
                    observed_at,
                    freshness.static_cli_seconds,
                    identity,
                )
            )
        workspace = Path(tempfile.mkdtemp(prefix="splatforge-colmap-db-")).resolve()
        workspace_identity = workspace.stat()
        database_path = workspace / "probe.db"
        compatibility: DatabaseCompatibility
        cleanup_error: OSError | None = None
        try:
            try:
                result = self._run(
                    identity.resolved_path,
                    ("database_creator", "--database_path", str(database_path)),
                    self._database_timeout,
                    working_directory=workspace,
                    environment=environment,
                )
            except (ProcessBoundaryError, OSError) as exc:
                compatibility = DatabaseCompatibility(
                    evidence=self._evidence(
                        "colmap.database",
                        CapabilityStatus.UNKNOWN,
                        "colmap.database_probe_failed",
                        f"Database probe process boundary failed: {exc}",
                        observed_at,
                        freshness.static_cli_seconds,
                        identity,
                    )
                )
            else:
                problem = self._process_problem(result, operation="database_creator")
                if problem is not None:
                    status, code, message = problem
                    compatibility = DatabaseCompatibility(
                        evidence=self._evidence(
                            "colmap.database",
                            status,
                            (
                                "colmap.probe_timeout"
                                if code == "colmap.probe_timeout"
                                else "colmap.database_creation_failed"
                            ),
                            message,
                            observed_at,
                            freshness.static_cli_seconds,
                            identity,
                        )
                    )
                elif not self._same_identity(identity, result.executable):
                    compatibility = DatabaseCompatibility(
                        evidence=self._evidence(
                            "colmap.database",
                            CapabilityStatus.UNKNOWN,
                            "colmap.identity_changed",
                            "COLMAP changed during native database creation",
                            observed_at,
                            freshness.static_cli_seconds,
                            identity,
                        )
                    )
                else:
                    compatibility = self._inspect_database(
                        database_path,
                        identity,
                        observed_at,
                        freshness,
                    )
        finally:
            try:
                if not isinstance(sys.exception(), DoctorTeardownError):
                    self._cleanup_workspace(workspace, workspace_identity)
            except OSError as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            return DatabaseCompatibility(
                evidence=self._evidence(
                    "colmap.database",
                    CapabilityStatus.UNKNOWN,
                    "colmap.probe_cleanup_failed",
                    f"Owned database probe workspace cleanup failed: {cleanup_error}",
                    observed_at,
                    freshness.static_cli_seconds,
                    identity,
                ),
                sqlite_user_version=compatibility.sqlite_user_version,
                sqlite_application_id=compatibility.sqlite_application_id,
                tables=compatibility.tables,
            )
        return compatibility

    def _inspect_database(
        self,
        database_path: Path,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> DatabaseCompatibility:
        try:
            user_version, application_id, tables = inspect_colmap_database(database_path)
        except (OSError, sqlite3.DatabaseError, ValueError) as exc:
            return DatabaseCompatibility(
                evidence=self._evidence(
                    "colmap.database",
                    CapabilityStatus.UNAVAILABLE,
                    "colmap.database_incompatible",
                    f"Generated COLMAP database is incompatible: {exc}",
                    observed_at,
                    freshness.static_cli_seconds,
                    identity,
                )
            )
        return DatabaseCompatibility(
            evidence=self._evidence(
                "colmap.database",
                CapabilityStatus.AVAILABLE,
                "colmap.database_compatible",
                "Generated native COLMAP database satisfies schema probe version 1",
                observed_at,
                freshness.static_cli_seconds,
                identity,
            ),
            sqlite_user_version=user_version,
            sqlite_application_id=application_id,
            tables=tables,
        )

    def _probe_sift(
        self,
        identity: ExecutableIdentity,
        commands: tuple[str, ...],
        *,
        use_gpu: bool,
        environment: Mapping[str, str],
        options: ParsedOptionHelp,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> CapabilityEvidence:
        capability_id = "colmap.feature.sift.gpu" if use_gpu else "colmap.feature.sift.cpu"
        if "database_creator" not in commands:
            return self._static_failure(
                capability_id,
                CapabilityStatus.UNAVAILABLE,
                "database_creator is required for the disposable SIFT smoke probe",
                identity,
                observed_at,
                freshness,
            )
        workspace = Path(tempfile.mkdtemp(prefix="splatforge-colmap-sift-")).resolve()
        workspace_identity = workspace.stat()
        database_path = workspace / "probe.db"
        image_directory = workspace / "images"
        evidence: CapabilityEvidence
        cleanup_error: OSError | None = None
        try:
            image_directory.mkdir()
            self._write_test_image(image_directory / "probe.png")
            try:
                create = self._run(
                    identity.resolved_path,
                    ("database_creator", "--database_path", str(database_path)),
                    self._database_timeout,
                    working_directory=workspace,
                    environment=environment,
                )
                create_problem = self._process_problem(create, operation="database_creator")
                if not self._same_identity(identity, create.executable):
                    raise ValueError("COLMAP changed during the smoke database creation")
                if create_problem is not None:
                    raise ValueError(create_problem[2])
                inspect_colmap_database(database_path)
                gpu_option = next(
                    name
                    for name in ("FeatureExtraction.use_gpu", "SiftExtraction.use_gpu")
                    if name in options.option_names
                )
                argv = (
                    "feature_extractor",
                    "--database_path",
                    str(database_path),
                    "--image_path",
                    str(image_directory),
                    f"--{gpu_option}",
                    "1" if use_gpu else "0",
                )
                if "FeatureExtraction.type" in options.option_names:
                    argv += ("--FeatureExtraction.type", "SIFT")
                for name in (
                    "FeatureExtraction.num_threads",
                    "SiftExtraction.num_threads",
                    "ImageReader.single_camera",
                ):
                    if name in options.option_names:
                        argv += (f"--{name}", "1")
                if use_gpu and "FeatureExtraction.gpu_index" in options.option_names:
                    argv += ("--FeatureExtraction.gpu_index", "0")
                result = self._run(
                    identity.resolved_path,
                    argv,
                    self._smoke_timeout,
                    working_directory=workspace,
                    environment=environment,
                )
            except (ProcessBoundaryError, OSError, ValueError, sqlite3.DatabaseError) as exc:
                evidence = self._evidence(
                    capability_id,
                    CapabilityStatus.UNKNOWN,
                    "colmap.cuda_probe_failed" if use_gpu else "colmap.cpu_probe_failed",
                    f"Contained SIFT probe could not complete: {exc}",
                    observed_at,
                    freshness.resource_health_seconds,
                    identity,
                )
            else:
                problem = self._process_problem(
                    result,
                    operation="GPU SIFT" if use_gpu else "CPU SIFT",
                )
                if problem is not None:
                    status, code, message = problem
                    if use_gpu and code == "colmap.probe_failed":
                        lowered = self._excerpt(self._combined_text(result)).lower()
                        if any(token in lowered for token in ("display", "opengl", "egl")):
                            code = "colmap.opengl_display_unavailable"
                        elif any(
                            token in lowered
                            for token in (
                                "cuda_error_no_device",
                                "no cuda",
                                "no device",
                                "cuda driver",
                                "cuda initialization",
                            )
                        ):
                            code = "colmap.cuda_unavailable"
                        else:
                            code = "colmap.cuda_probe_failed"
                    evidence = self._evidence(
                        capability_id,
                        status,
                        code
                        if use_gpu
                        else (
                            "colmap.probe_timeout"
                            if code == "colmap.probe_timeout"
                            else "colmap.cpu_probe_failed"
                        ),
                        message,
                        observed_at,
                        freshness.resource_health_seconds,
                        identity,
                    )
                elif not self._same_identity(identity, result.executable):
                    evidence = self._evidence(
                        capability_id,
                        CapabilityStatus.UNKNOWN,
                        "colmap.identity_changed",
                        "COLMAP changed during the SIFT functional probe",
                        observed_at,
                        freshness.resource_health_seconds,
                        identity,
                    )
                else:
                    try:
                        inspect_colmap_database(database_path)
                        validate_sift_probe_output(database_path)
                        if use_gpu and not re.search(
                            r"Creating (?:SIFT GPU|SiftGPU) feature extractor\b",
                            self._combined_text(result),
                        ):
                            raise ValueError("GPU extractor execution was not positively observed")
                    except (OSError, sqlite3.DatabaseError, ValueError) as exc:
                        evidence = self._evidence(
                            capability_id,
                            CapabilityStatus.UNAVAILABLE,
                            "colmap.cuda_probe_failed" if use_gpu else "colmap.cpu_probe_failed",
                            f"SIFT exited successfully but output validation failed: {exc}",
                            observed_at,
                            freshness.resource_health_seconds,
                            identity,
                        )
                    else:
                        evidence = self._evidence(
                            capability_id,
                            CapabilityStatus.AVAILABLE,
                            "colmap.gpu_sift_available" if use_gpu else "colmap.cpu_sift_available",
                            (
                                "Disposable COLMAP GPU SIFT smoke probe succeeded"
                                if use_gpu
                                else "Disposable COLMAP CPU SIFT smoke probe succeeded"
                            ),
                            observed_at,
                            freshness.resource_health_seconds,
                            identity,
                            details=(
                                ("backend_excerpt", self._excerpt(self._combined_text(result))),
                            ),
                        )
        finally:
            try:
                if not isinstance(sys.exception(), DoctorTeardownError):
                    self._cleanup_workspace(workspace, workspace_identity)
            except OSError as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            return self._evidence(
                capability_id,
                CapabilityStatus.UNKNOWN,
                "colmap.probe_cleanup_failed",
                f"Owned SIFT probe workspace cleanup failed: {cleanup_error}",
                observed_at,
                freshness.resource_health_seconds,
                identity,
            )
        return evidence

    @staticmethod
    def _write_test_image(path: Path) -> None:
        image = Image.new("L", (192, 192), 0)
        draw = ImageDraw.Draw(image)
        for y in range(0, 192, 16):
            for x in range(0, 192, 16):
                fill = 255 if (x // 16 + y // 16) % 2 else 32
                draw.rectangle((x, y, x + 15, y + 15), fill=fill)
        draw.line((0, 0, 191, 191), fill=160, width=3)
        image.save(path, format="PNG")

    def _not_run_database(
        self,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> DatabaseCompatibility:
        return DatabaseCompatibility(
            evidence=self._not_run(
                "colmap.database",
                "Native database creation and schema validation require --deep",
                identity,
                observed_at,
                freshness,
            )
        )

    def _run(
        self,
        executable: str,
        argv: tuple[str, ...],
        timeout: float,
        *,
        working_directory: Path | None = None,
        environment: Mapping[str, str],
    ) -> ProcessResult:
        workspace = (
            Path(tempfile.mkdtemp(prefix="splatforge-colmap-help-")).resolve()
            if working_directory is None
            else None
        )
        workspace_identity = workspace.stat() if workspace is not None else None
        cwd = working_directory if working_directory is not None else workspace
        assert cwd is not None
        try:
            result = self._runner.run(
                ProcessRequest(
                    executable=executable,
                    argv=argv,
                    working_directory=cwd,
                    environment=environment,
                    timeout_seconds=timeout,
                    max_stdout_bytes=self._maximum_output,
                    max_stderr_bytes=self._maximum_output,
                )
            )
            if not result.teardown_confirmed:
                raise DoctorTeardownError(
                    f"colmap.probe_teardown_failed: contained tree is unresolved; "
                    f"stop Doctor and quarantine workspace {cwd}"
                )
        except ProcessCleanupError as exc:
            if not exc.teardown_confirmed:
                raise DoctorTeardownError(
                    f"colmap.probe_teardown_failed: {exc}; quarantine workspace {cwd}"
                ) from exc
            raise
        finally:
            if workspace is not None and not isinstance(sys.exception(), DoctorTeardownError):
                self._cleanup_workspace(workspace, workspace_identity)
        return result

    def _missing_report(
        self,
        *,
        message: str,
        deep: bool,
        observed_at: datetime,
        freshness: FreshnessPolicy,
        code: str = "colmap.executable_missing",
        status: CapabilityStatus = CapabilityStatus.UNAVAILABLE,
    ) -> ColmapProbeReport:
        binary = self._evidence(
            "colmap.binary",
            status,
            code,
            f"COLMAP is unavailable; configure --colmap or SPLATFORGE_COLMAP ({message})",
            observed_at,
            freshness.static_cli_seconds,
            None,
        )
        return self._empty_report(binary, None, deep, observed_at, freshness)

    def _failed_start_report(
        self,
        *,
        selection: ExecutableSelection,
        message: str,
        deep: bool,
        observed_at: datetime,
        freshness: FreshnessPolicy,
        code: str = "colmap.loader_failure",
        status: CapabilityStatus = CapabilityStatus.UNAVAILABLE,
    ) -> ColmapProbeReport:
        binary = self._evidence(
            "colmap.binary",
            status,
            code,
            f"COLMAP executable exists but could not be probed: {message}",
            observed_at,
            freshness.static_cli_seconds,
            selection.identity,
        )
        return self._empty_report(binary, selection, deep, observed_at, freshness)

    def _empty_report(
        self,
        binary: CapabilityEvidence,
        selection: ExecutableSelection | None,
        deep: bool,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> ColmapProbeReport:
        identity = selection.identity if selection is not None else None
        status = (
            CapabilityStatus.UNAVAILABLE
            if binary.status == CapabilityStatus.UNAVAILABLE
            else CapabilityStatus.UNKNOWN
        )
        capabilities = tuple(
            self._evidence(
                capability_id,
                status,
                "colmap.binary_prerequisite_unavailable",
                "Capability cannot be established because the COLMAP binary probe failed",
                observed_at,
                freshness.static_cli_seconds,
                identity,
            )
            for capability_id in _CAPABILITY_IDS
        )
        discovery_evidence = self._evidence(
            "colmap.commands",
            status,
            "colmap.binary_prerequisite_unavailable",
            "COLMAP commands could not be discovered",
            observed_at,
            freshness.static_cli_seconds,
            identity,
        )
        database = DatabaseCompatibility(
            evidence=self._evidence(
                "colmap.database",
                status,
                "colmap.binary_prerequisite_unavailable",
                "Native database compatibility could not be probed",
                observed_at,
                freshness.static_cli_seconds,
                identity,
            )
        )
        return ColmapProbeReport(
            selected_executable=selection,
            binary=binary,
            command_discovery=CommandDiscovery(evidence=discovery_evidence),
            capabilities=capabilities,
            database=database,
            deep=deep,
        )

    def _presence_evidence(
        self,
        capability_id: str,
        operation: str,
        commands: tuple[str, ...],
        listing_ok: bool,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> CapabilityEvidence:
        if not listing_ok:
            return self._evidence(
                capability_id,
                CapabilityStatus.UNKNOWN,
                "colmap.help_unrecognized",
                f"Cannot determine whether {operation} exists from unrecognized help",
                observed_at,
                freshness.static_cli_seconds,
                identity,
            )
        available = operation in commands
        return self._evidence(
            capability_id,
            CapabilityStatus.AVAILABLE if available else CapabilityStatus.UNAVAILABLE,
            "colmap.operation_available" if available else "colmap.operation_missing",
            (
                f"COLMAP operation {operation} is available"
                if available
                else f"COLMAP operation {operation} is not advertised"
            ),
            observed_at,
            freshness.static_cli_seconds,
            identity,
        )

    def _token_capability(
        self,
        capability_id: str,
        parsed: ParsedOptionHelp,
        token: str,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> CapabilityEvidence:
        status = self._token_status(parsed, token)
        code = (
            "colmap.option_available"
            if status == CapabilityStatus.AVAILABLE
            else (
                "colmap.option_missing"
                if status == CapabilityStatus.UNAVAILABLE
                else "colmap.help_unrecognized"
            )
        )
        return self._evidence(
            capability_id,
            status,
            code,
            (
                f"COLMAP help advertises {token}"
                if status == CapabilityStatus.AVAILABLE
                else (
                    f"COLMAP help does not advertise {token}"
                    if status == CapabilityStatus.UNAVAILABLE
                    else f"Cannot determine support for {token} from unrecognized help"
                )
            ),
            observed_at,
            freshness.static_cli_seconds,
            identity,
        )

    def _composite(
        self,
        capability_id: str,
        dependencies: tuple[CapabilityStatus, ...],
        available_message: str,
        blocked_message: str,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> CapabilityEvidence:
        status = required_status(dependencies)
        if status == CapabilityStatus.AVAILABLE:
            code = "colmap.capability_available"
            message = available_message
        elif status == CapabilityStatus.UNAVAILABLE:
            code = "colmap.capability_dependency_unavailable"
            message = blocked_message
        else:
            code = "colmap.capability_dependency_unknown"
            message = blocked_message
        return self._evidence(
            capability_id,
            status,
            code,
            message,
            observed_at,
            freshness.static_cli_seconds,
            identity,
            details=(("dependency_statuses", ",".join(item.value for item in dependencies)),),
            prerequisites={
                "colmap.feature.aliked": (
                    "colmap.help.feature_extractor",
                    "colmap.onnx",
                    "colmap.model.aliked.n16rot",
                    "colmap.model.aliked.n32",
                ),
                "colmap.match.aliked_bruteforce": (
                    "colmap.help.exhaustive_matcher",
                    "colmap.help.sequential_matcher",
                    "colmap.onnx",
                    "colmap.model.bruteforce.aliked",
                ),
                "colmap.match.sift_lightglue": (
                    "colmap.help.exhaustive_matcher",
                    "colmap.help.sequential_matcher",
                    "colmap.onnx",
                    "colmap.model.lightglue.sift",
                ),
                "colmap.match.aliked_lightglue": (
                    "colmap.help.exhaustive_matcher",
                    "colmap.help.sequential_matcher",
                    "colmap.onnx",
                    "colmap.model.lightglue.aliked",
                ),
            }.get(capability_id, ()),
        )

    def _not_run(
        self,
        capability_id: str,
        message: str,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> CapabilityEvidence:
        return self._evidence(
            capability_id,
            CapabilityStatus.UNKNOWN,
            "colmap.functional_probe_not_run",
            message,
            observed_at,
            freshness.resource_health_seconds,
            identity,
        )

    def _static_failure(
        self,
        capability_id: str,
        status: CapabilityStatus,
        message: str,
        identity: ExecutableIdentity,
        observed_at: datetime,
        freshness: FreshnessPolicy,
    ) -> CapabilityEvidence:
        return self._evidence(
            capability_id,
            status,
            (
                "colmap.help_unrecognized"
                if status == CapabilityStatus.UNKNOWN
                else "colmap.option_missing"
            ),
            message,
            observed_at,
            freshness.static_cli_seconds,
            identity,
        )

    @staticmethod
    def _token_status(parsed: ParsedOptionHelp, token: str) -> CapabilityStatus:
        if not parsed.recognized:
            return CapabilityStatus.UNKNOWN
        return (
            CapabilityStatus.AVAILABLE if token in parsed.tokens else CapabilityStatus.UNAVAILABLE
        )

    @staticmethod
    def _any_token_status(
        parsed: ParsedOptionHelp,
        predicate: Callable[[str], bool],
    ) -> CapabilityStatus:
        if not parsed.recognized:
            return CapabilityStatus.UNKNOWN
        return (
            CapabilityStatus.AVAILABLE
            if any(predicate(token) for token in parsed.tokens)
            else CapabilityStatus.UNAVAILABLE
        )

    @staticmethod
    def _any_status(statuses: tuple[CapabilityStatus, ...]) -> CapabilityStatus:
        return alternative_status(statuses)

    @staticmethod
    def _process_problem(
        result: ProcessResult,
        *,
        operation: str,
    ) -> tuple[CapabilityStatus, str, str] | None:
        if result.timed_out:
            return (
                CapabilityStatus.UNKNOWN,
                "colmap.probe_timeout",
                f"COLMAP {operation} timed out after contained process-tree cleanup",
            )
        if result.cancelled:
            return (
                CapabilityStatus.UNKNOWN,
                "colmap.probe_cancelled",
                f"COLMAP {operation} was cancelled",
            )
        if not result.teardown_confirmed or result.forced_tree_termination:
            return (
                CapabilityStatus.UNKNOWN,
                "colmap.probe_teardown_failed",
                f"COLMAP {operation} did not complete clean process-tree teardown",
            )
        if result.stdout_truncated or result.stderr_truncated:
            return (
                CapabilityStatus.UNKNOWN,
                "colmap.probe_output_truncated",
                f"COLMAP {operation} exceeded bounded diagnostic output",
            )
        if result.exit_code != 0:
            detail = ColmapCapabilityAdapter._excerpt(
                result.stderr_text().strip() or result.stdout_text().strip()
            )
            ntstatus = (result.exit_code or 0) & 0xFFFFFFFF
            loader = (
                result.exit_code == 127 and "backend launch failed" in detail.lower()
            ) or ntstatus in {0xC000007B, 0xC0000135, 0xC0000142}
            crash = ntstatus in {0xC0000005, 0xC000001D, 0xC0000409} or (
                result.exit_code in {134, 139}
            )
            return (
                CapabilityStatus.UNAVAILABLE,
                (
                    "colmap.loader_failure"
                    if loader
                    else "colmap.probe_crash"
                    if crash
                    else "colmap.probe_failed"
                ),
                (
                    f"COLMAP {operation} exited with code {result.exit_code}: "
                    f"{detail or 'no diagnostics'}"
                ),
            )
        return None

    @staticmethod
    def _evidence(
        capability_id: str,
        status: CapabilityStatus,
        code: str,
        message: str,
        observed_at: datetime,
        ttl_seconds: int,
        identity: ExecutableIdentity | None,
        *,
        details: tuple[tuple[str, str], ...] = (),
        prerequisites: tuple[str, ...] = (),
    ) -> CapabilityEvidence:
        return CapabilityEvidence(
            capability_id=capability_id,
            status=status,
            diagnostic_code=code,
            message=message[:1024],
            observed_at=observed_at,
            expires_at=observed_at + timedelta(seconds=ttl_seconds),
            freshness_seconds=ttl_seconds,
            backend_identity=identity,
            prerequisites=prerequisites,
            details=tuple(
                EvidenceDetail(key=key, value=value[:1024]) for key, value in details[:32]
            ),
        )

    @staticmethod
    def _combined_text(result: ProcessResult) -> str:
        return "\n".join(text for text in (result.stdout_text(), result.stderr_text()) if text)

    @staticmethod
    def _excerpt(text: str) -> str:
        return " ".join(text.replace("\x00", "").split())[:1024]

    @staticmethod
    def _same_identity(left: ExecutableIdentity, right: ExecutableIdentity) -> bool:
        return left.model_copy(update={"version_line": None}) == right.model_copy(
            update={"version_line": None}
        )

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _cleanup_workspace(workspace: Path, expected: os.stat_result | None = None) -> None:
        if workspace.is_symlink() or workspace.is_junction():
            raise OSError("refusing cleanup through a redirected probe root")
        resolved = workspace.resolve(strict=True)
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        if resolved.parent != temp_root or not resolved.name.startswith("splatforge-colmap-"):
            raise OSError(f"refusing cleanup outside owned probe root: {resolved}")
        current = resolved.stat()
        if expected is not None and (current.st_dev, current.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            raise OSError("refusing cleanup of a replaced probe workspace")
        pending = [resolved]
        scanned = 0
        while pending:
            directory = pending.pop()
            for entry in directory.iterdir():
                scanned += 1
                if scanned > 4096:
                    raise OSError("probe workspace exceeds bounded cleanup scope")
                if entry.is_symlink() or entry.is_junction():
                    raise OSError("refusing cleanup of a probe tree containing a redirect")
                if entry.is_dir():
                    pending.append(entry)
        shutil.rmtree(resolved)


def inspect_colmap_database(
    path: Path,
    *, maximum_bytes: int = 16 * 1024 * 1024,
) -> tuple[int, int, tuple[DatabaseTableEvidence, ...]]:
    """Read a generated COLMAP database strictly read-only and validate schema v1."""

    if path.is_symlink() or path.is_junction():
        raise ValueError("redirected database output is not allowed")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("database output is not a regular file")
    if resolved.stat().st_size > maximum_bytes:
        raise ValueError("database exceeds its inspection byte limit")
    uri = resolved.as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        deadline = time.monotonic() + (2.0 if maximum_bytes <= 16 * 1024 * 1024 else 300.0)
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        quick_check = connection.execute("PRAGMA quick_check(1)").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            raise ValueError("SQLite quick_check did not report ok")
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            ).fetchall()
        }
        missing_tables = sorted(set(_REQUIRED_SCHEMA) - names)
        if missing_tables:
            raise ValueError(f"missing required tables: {', '.join(missing_tables)}")
        evidence = []
        for table, required_columns in _REQUIRED_SCHEMA.items():
            rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = tuple(str(row[1]) for row in rows)
            if table == "descriptors" and "type" in columns:
                required_columns = required_columns | {"type"}
            missing_columns = sorted(required_columns - set(columns))
            if missing_columns:
                raise ValueError(f"table {table} is missing columns: {', '.join(missing_columns)}")
            for row in rows:
                name, declared = str(row[1]), str(row[2]).upper()
                if name not in required_columns:
                    continue
                expected_type = (
                    "BLOB"
                    if name in {"params", "data", "F", "E", "H"}
                    else "TEXT"
                    if name == "name"
                    else "INTEGER"
                )
                if declared != expected_type:
                    raise ValueError(f"table {table}.{name} requires {expected_type} storage")
            primary = tuple(
                str(row[1]) for row in sorted(rows, key=lambda row: int(row[5])) if int(row[5])
            )
            identifier = (
                "pair_id"
                if table in {"matches", "two_view_geometries"}
                else (
                    "image_id" if table in {"images", "keypoints", "descriptors"} else "camera_id"
                )
            )
            if primary != (identifier,):
                raise ValueError(f"table {table} does not key {identifier} as required")
            if table == "images":
                indexes = connection.execute(
                    'SELECT name FROM pragma_index_list(?) WHERE "unique"=1 AND partial=0',
                    ("images",),
                ).fetchall()
                unique_name = any(
                    tuple(
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM pragma_index_info(?)", (index[0],)
                        )
                    )
                    == ("name",)
                    for index in indexes
                )
                if not unique_name:
                    raise ValueError("images.name must have a non-partial unique constraint")
            evidence.append(
                DatabaseTableEvidence(
                    name=table,
                    columns=tuple(name for name in columns if name in required_columns),
                    primary_key_columns=primary,
                )
            )
    return user_version, application_id, tuple(evidence)


def validate_sift_probe_output(path: Path) -> None:
    """Validate the one generated image and positive, matching native SIFT rows."""

    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT i.name, k.rows, k.cols, length(k.data), "
            "d.rows, d.cols, length(d.data) FROM images AS i "
            "JOIN cameras AS c ON c.camera_id=i.camera_id "
            "JOIN keypoints AS k ON k.image_id=i.image_id "
            "JOIN descriptors AS d ON d.image_id=i.image_id LIMIT 2"
        ).fetchall()
    if len(rows) != 1:
        raise ValueError("expected one generated image with matching feature records")
    name, k_rows, k_cols, k_bytes, d_rows, d_cols, d_bytes = rows[0]
    if any(
        not isinstance(value, int)
        for value in (
            k_rows,
            k_cols,
            k_bytes,
            d_rows,
            d_cols,
            d_bytes,
        )
    ):
        raise ValueError("generated SIFT dimensions or payload lengths are not integers")
    if (
        name != "probe.png"
        or k_rows <= 0
        or k_rows != d_rows
        or k_cols not in {2, 4, 6}
        or d_cols != 128
        or k_bytes != k_rows * k_cols * 4
        or d_bytes != d_rows * d_cols
    ):
        raise ValueError("generated SIFT feature dimensions or payload lengths are invalid")
