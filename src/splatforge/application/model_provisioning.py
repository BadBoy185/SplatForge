"""Read-only, route-specific manual provisioning instructions from native evidence."""

from pydantic import Field

from splatforge.core.capabilities import ColmapProbeReport, ModelEvidence
from splatforge.core.features import model_roles
from splatforge.core.matching import matcher_model_role
from splatforge.core.sfm_profiles import FeatureMatchingChoice
from splatforge.core.views import FrozenModel


class LearnedRouteProvisioning(FrozenModel):
    extractor: str
    matcher: str
    models: tuple[ModelEvidence, ...] = Field(max_length=3)
    configuration: str = "--colmap-model-dir or SPLATFORGE_COLMAP_MODEL_DIR (absolute local root)"
    rerun_command: str
    rerun_environment: tuple[tuple[str, str], ...] = Field(max_length=5)

    @property
    def ready(self) -> bool:
        return all(m.evidence.status == "available" and m.sha256 and m.size for m in self.models)


def learned_route_provisioning(
    choice: FeatureMatchingChoice, report: ColmapProbeReport,
) -> LearnedRouteProvisioning:
    roles = (*model_roles(choice.extractor), matcher_model_role(choice.matcher))
    by_role = {m.role: m for m in report.models}
    models = tuple(by_role[r] for r in roles if r is not None)
    environment = [("SPLATFORGE_TEST_COLMAP_LEARNED", "1"),
                   ("SPLATFORGE_TEST_COLMAP_DEVICE", "auto")]
    if report.selected_executable:
        environment.append(("SPLATFORGE_TEST_COLMAP",
                            report.selected_executable.identity.resolved_path))
    if models and models[0].expected_root:
        environment.append(("SPLATFORGE_COLMAP_MODEL_DIR", models[0].expected_root))
    if choice.matcher.variant in ("LOMA_L", "LOMA_G"):
        environment.append(("SPLATFORGE_TEST_COLMAP_HEAVY", "1"))
    return LearnedRouteProvisioning(
        extractor=choice.extractor.variant,
        matcher=choice.matcher.variant,
        models=models,
        rerun_environment=tuple(environment),
        rerun_command=(
            "$env:SPLATFORGE_TEST_COLMAP_LEARNED='1'; "
            + ("$env:SPLATFORGE_TEST_COLMAP_HEAVY='1'; "
               if choice.matcher.variant in ("LOMA_L", "LOMA_G") else "")
            + ".venv/Scripts/python.exe -m pytest "
            f"'tests/test_matching_integration.py::test_real_explicit_raw_then_verification"
            f"[{choice.extractor.variant}-{choice.matcher.variant}]' -s -rA"
        ),
    )
