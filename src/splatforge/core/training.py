"""Versioned trainer-neutral recipes, checkpoints and completed Gaussian scenes."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from splatforge.core.features import Digest, digest_json
from splatforge.core.reconstruction import CONVENTION
from splatforge.core.views import FrozenModel

CHECKPOINT_TYPE = "training.checkpoint"
SCENE_TYPE = "training.gaussian_scene"
SET_TYPE = "training.gaussian_scene_set"
GSPLAT_RELEASE = "1.5.3"
GSPLAT_COMMIT = "937e29912570c372bed6747a5c9bf85fed877bae"


class DefaultStrategySettings(FrozenModel):
    strategy: Literal["default"] = "default"
    absgrad: bool = False
    grow_grad2d: float = Field(default=0.0002, gt=0)
    prune_opa: float = Field(default=0.005, gt=0, lt=1)
    grow_scale3d: float = Field(default=0.01, gt=0)
    grow_scale2d: float = Field(default=0.05, gt=0)
    prune_scale3d: float = Field(default=0.1, gt=0)
    prune_scale2d: float = Field(default=0.15, gt=0)
    refine_start_iter: int = Field(default=500, ge=0, strict=True)
    refine_stop_iter: int = Field(default=15000, ge=1, strict=True)
    refine_every: int = Field(default=100, ge=1, strict=True)
    reset_every: int = Field(default=3000, ge=1, strict=True)


class MCMCStrategySettings(FrozenModel):
    strategy: Literal["mcmc"] = "mcmc"
    cap_max: int = Field(default=1000000, ge=4, le=10000000, strict=True)
    noise_lr: float = Field(default=500000, ge=0)
    opacity_reg: float = Field(default=0.01, ge=0)
    scale_reg: float = Field(default=0.01, ge=0)
    refine_start_iter: int = Field(default=500, ge=0, strict=True)
    refine_stop_iter: int = Field(default=25000, ge=1, strict=True)
    refine_every: int = Field(default=100, ge=1, strict=True)
    min_opacity: float = Field(default=0.005, gt=0, lt=1)


class EvaluationSplit(FrozenModel):
    policy: Literal["none", "explicit_views_v1", "sha256_views_v1"] = "none"
    held_out_view_ids: tuple[UUID, ...] = Field(default=(), max_length=100000)
    # Provenance is descriptive; exact held-out membership is numerical.
    warning: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def membership(self) -> EvaluationSplit:
        if list(self.held_out_view_ids) != sorted(set(self.held_out_view_ids), key=lambda i: i.int):
            raise ValueError("training.invalid_split: canonical unique held-out IDs required")
        if (self.policy == "none") != (not self.held_out_view_ids):
            raise ValueError("training.invalid_split: policy and held-out membership differ")
        return self


class TrainingSettings(FrozenModel):
    settings_version: Literal[1] = 1
    strategy: Annotated[
        DefaultStrategySettings | MCMCStrategySettings, Field(discriminator="strategy")
    ] = DefaultStrategySettings()
    max_steps: int = Field(default=30000, ge=1, le=1000000, strict=True)
    sh_degree: int = Field(default=3, ge=0, le=3, strict=True)
    sh_degree_interval: int = Field(default=1000, ge=1, strict=True)
    data_factor: int = Field(default=1, ge=1, le=64, strict=True)
    ssim_weight: float = Field(default=0.2, ge=0, le=1)
    seed: int = Field(default=42, ge=0, le=2**32 - 1, strict=True)
    evaluation_every: int = Field(default=7000, ge=1, strict=True)
    checkpoint_every: int = Field(default=7000, ge=1, strict=True)
    final_export: bool = True
    antialiased: bool = False
    pose_opt: Literal[False] = False
    initialization: Literal["sfm"] = "sfm"
    normalize_world_space: Literal[False] = False
    split: EvaluationSplit = EvaluationSplit()
    # These worker-owned constants are explicit frozen recipe fields.
    means_lr: float = Field(default=1.6e-4, gt=0)
    scales_lr: float = Field(default=0.005, gt=0)
    opacities_lr: float = Field(default=0.05, gt=0)
    quats_lr: float = Field(default=0.001, gt=0)
    sh0_lr: float = Field(default=0.0025, gt=0)
    shN_lr: float = Field(default=0.000125, gt=0)
    init_opacity: float = Field(default=0.1, gt=0, lt=1)
    near_plane: float = Field(default=0.01, gt=0)
    far_plane: float = Field(default=1e10, gt=0)

    @model_validator(mode="after")
    def schedule(self) -> TrainingSettings:
        if self.strategy.refine_stop_iter <= self.strategy.refine_start_iter:
            raise ValueError("training.invalid_refinement: stop must exceed start")
        if self.near_plane >= self.far_plane:
            raise ValueError("training.invalid_clipping")
        return self

    @property
    def method_id(self) -> str:
        return f"gsplat.{self.strategy.strategy}"

    def numerical(self) -> dict:
        value = self.model_dump(mode="json")
        value["split"].pop("warning")
        return value


class TrainingLimits(FrozenModel):
    timeout_seconds: int = Field(default=14400, ge=1, le=172800, strict=True)
    max_checkpoint_bytes: int = Field(default=16 * 1024**3, ge=1, le=1024**4, strict=True)
    max_scene_bytes: int = Field(default=8 * 1024**3, ge=1, le=1024**4, strict=True)
    max_log_bytes: int = Field(default=8 * 1024**2, ge=1024, le=64 * 1024**2, strict=True)
    max_gaussians: int = Field(default=10000000, ge=4, le=10000000, strict=True)


class TrainingBackendIdentity(FrozenModel):
    worker_version: Literal[1] = 1
    worker_sha256: Digest
    python_sha256: Digest
    python_version: str
    torch_version: str
    torch_cuda: str
    gsplat_version: Literal[GSPLAT_RELEASE] = GSPLAT_RELEASE
    gsplat_commit: Literal[GSPLAT_COMMIT] = GSPLAT_COMMIT
    packages_digest: Digest
    cuda_runtime: str
    driver: str
    gpu_uuid: str
    gpu_name: str
    gpu_ordinal: int = Field(ge=0, strict=True)
    compute_capability: tuple[int, int]
    device_total_bytes: int = Field(gt=0, strict=True)
    features: tuple[str, ...]
    kernel_backward_optimizer: Literal[True] = True
    determinism: Literal["seeded_gpu_not_bitwise_proven"] = "seeded_gpu_not_bitwise_proven"

    @property
    def numerical_identity(self) -> str:
        return digest_json(self.model_dump(mode="json"))


def training_recipe(dataset_digest: str, settings: TrainingSettings, backend_digest: str) -> str:
    return digest_json(
        {
            "training_recipe_v1": dataset_digest,
            "method_id": settings.method_id,
            "settings": settings.numerical(),
            "backend": backend_digest,
        }
    )


def checkpoint_recipe(recipe: str, step: int, compatibility: str) -> str:
    return digest_json({"checkpoint_v1": recipe, "step": step, "compatibility": compatibility})


class TrainingMetrics(FrozenModel):
    training_loss: float | None = None
    evaluation_psnr: float | None = None
    evaluation_ssim: float | None = None
    evaluation_lpips: float | None = None
    evaluation_views: int = Field(default=0, ge=0, strict=True)
    evaluation_step: int | None = Field(default=None, ge=1, strict=True)
    per_source_group: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    lpips_status: Literal["unavailable_no_local_weights", "measured"] = (
        "unavailable_no_local_weights"
    )
    duration_seconds: float = Field(default=0, ge=0)
    peak_allocated_cuda_bytes: int | None = Field(default=None, ge=0, strict=True)


class NativeCheckpointFile(FrozenModel):
    path: Literal["checkpoint/state.pt"] = "checkpoint/state.pt"
    sha256: Digest
    size: int = Field(gt=0, strict=True)


class TrainingCheckpoint(FrozenModel):
    contract_version: Literal[1] = 1
    checkpoint_schema: Literal[1] = 1
    dataset_digest: Digest
    settings: TrainingSettings
    backend: TrainingBackendIdentity
    step: int = Field(ge=1, strict=True)
    gaussian_count: int = Field(gt=0, strict=True)
    native: NativeCheckpointFile
    state_evidence: Literal[
        "parameters_optimizers_schedulers_strategy_python_numpy_torch_cuda_rng_v1"
    ]
    metrics: TrainingMetrics = TrainingMetrics()
    resumed_from_checkpoint: Digest | None = None

    @model_validator(mode="after")
    def bounded_step(self) -> TrainingCheckpoint:
        if self.step > self.settings.max_steps:
            raise ValueError("training.invalid_checkpoint_step")
        return self

    @property
    def training_recipe(self) -> str:
        return training_recipe(self.dataset_digest, self.settings, self.backend.numerical_identity)

    @property
    def compatibility_identity(self) -> str:
        return digest_json({"schema": self.checkpoint_schema, "recipe": self.training_recipe})

    @property
    def recipe_key(self) -> str:
        return checkpoint_recipe(self.training_recipe, self.step, self.compatibility_identity)

    @property
    def semantic_digest(self) -> str:
        return digest_json({"recipe": self.recipe_key, "native": self.native.model_dump()})

    def require_compatible(
        self, dataset_digest: str, settings: TrainingSettings, backend: TrainingBackendIdentity
    ) -> None:
        if self.training_recipe != training_recipe(
            dataset_digest, settings, backend.numerical_identity
        ):
            raise ValueError("training.incompatible_checkpoint: dataset/settings/runtime differ")

    def metadata(self) -> dict:
        return {
            **self.model_dump(mode="json"),
            "training_recipe": self.training_recipe,
            "compatibility_identity": self.compatibility_identity,
            "recipe_key": self.recipe_key,
            "backend_numerical_identity": self.backend.numerical_identity,
            "numerical_semantic_digest": self.semantic_digest,
        }


class GaussianScene(FrozenModel):
    contract_version: Literal[1] = 1
    method_id: str = Field(pattern=r"^[a-z0-9_.-]+$", max_length=128)
    dataset_digest: Digest
    settings: TrainingSettings
    backend: TrainingBackendIdentity
    final_step: int = Field(gt=0, strict=True)
    gaussian_count: int = Field(gt=0, strict=True)
    sh_degree: int = Field(ge=0, le=3, strict=True)
    coordinate_convention: Literal[CONVENTION] = CONVENTION
    scale: Literal["unknown_arbitrary"] = "unknown_arbitrary"
    payload_format: Literal["gaussian_ply_float32_le_v1"] = "gaussian_ply_float32_le_v1"
    ply_sha256: Digest
    ply_size: int = Field(gt=0, strict=True)
    numerical_content_digest: Digest
    metrics: TrainingMetrics
    checkpoint_lineage: tuple[Digest, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def completed(self) -> GaussianScene:
        if self.method_id != self.settings.method_id:
            raise ValueError("training.scene_method_mismatch")
        if self.final_step != self.settings.max_steps or self.sh_degree != self.settings.sh_degree:
            raise ValueError("training.incomplete_scene: final settings/step mismatch")
        return self

    @property
    def recipe_key(self) -> str:
        return training_recipe(self.dataset_digest, self.settings, self.backend.numerical_identity)

    @property
    def semantic_digest(self) -> str:
        # Actual Gaussian numerical content; training history is provenance.
        return digest_json(
            {
                "gaussian_scene_v1": self.numerical_content_digest,
                "sh_degree": self.sh_degree,
                "convention": self.coordinate_convention,
                "scale": self.scale,
            }
        )

    def metadata(self) -> dict:
        return {
            **self.model_dump(mode="json"),
            "recipe_key": self.recipe_key,
            "backend_numerical_identity": self.backend.numerical_identity,
            "numerical_semantic_digest": self.semantic_digest,
        }


def required_training_features(settings: TrainingSettings) -> frozenset[str]:
    features = {settings.strategy.strategy}
    if getattr(settings.strategy, "absgrad", False):
        features.add("absgrad")
        if settings.antialiased:
            features.add("absgrad_antialiased")
    if settings.antialiased:
        features.add("antialiased")
        if settings.strategy.strategy == "mcmc":
            features.add("mcmc_antialiased")
    return frozenset(features)


class GaussianSceneReference(FrozenModel):
    component_id: UUID
    artifact_id: UUID
    semantic_digest: Digest
    manifest_path: str

    @model_validator(mode="after")
    def locator(self) -> GaussianSceneReference:
        if self.manifest_path != f"artifacts/gaussian_scene/{self.artifact_id}/manifest.json":
            raise ValueError("training.unsafe_scene_reference")
        return self


class GaussianSceneSet(FrozenModel):
    contract_version: Literal[1] = 1
    scenes: tuple[GaussianSceneReference, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def canonical(self) -> GaussianSceneSet:
        ids = [s.component_id.int for s in self.scenes]
        if ids != sorted(set(ids)):
            raise ValueError("training.noncanonical_components")
        return self

    @property
    def recipe_key(self) -> str:
        return digest_json(self.model_dump(mode="json"))

    @property
    def semantic_digest(self) -> str:
        return digest_json([(str(s.component_id), s.semantic_digest) for s in self.scenes])
