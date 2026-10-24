"""SplatForge-owned single-GPU worker; upstream Apache-2.0 strategies stay external.

No Graphdeco/LichtFeld implementation is used. Numerical defaults follow gsplat
v1.5.3's Apache-2.0 example; dataset loading, protocol, SSIM and persistence are owned.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024**2):
            digest.update(block)
    return digest.hexdigest()


def worker_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    files = [
        *sorted((root / "splatforge_gsplat_worker").glob("*.py")),
        root / "splatforge/core/training.py",
        root / "splatforge/core/dataset.py",
        root / "splatforge/core/reconstruction.py",
        root / "splatforge/core/views.py",
        root / "splatforge/core/features.py",
        root / "splatforge/adapters/gaussian_ply.py",
        root / "splatforge/core/training_protocol.py",
    ]
    return hashlib.sha256("".join(file_hash(p) for p in files).encode()).hexdigest()


def raster(
    params,
    view,
    intrinsics,
    width,
    height,
    degree,
    *,
    absgrad=False,
    aa=False,
    near_plane=0.01,
    far_plane=1e10,
):
    import torch
    from gsplat import rasterization

    return rasterization(
        means=params["means"],
        quats=params["quats"],
        scales=params["scales"].exp(),
        opacities=params["opacities"].sigmoid(),
        colors=torch.cat([params["sh0"], params["shN"]], dim=1),
        viewmats=view[None],
        Ks=intrinsics[None],
        width=width,
        height=height,
        sh_degree=degree,
        packed=False,
        absgrad=absgrad,
        rasterize_mode="antialiased" if aa else "classic",
        near_plane=near_plane,
        far_plane=far_plane,
    )


def make_optimizers(params, settings, scene_scale):
    import torch

    rates = {
        "means": settings.means_lr * scene_scale,
        "scales": settings.scales_lr,
        "quats": settings.quats_lr,
        "opacities": settings.opacities_lr,
        "sh0": settings.sh0_lr,
        "shN": settings.shN_lr,
    }
    optimizers = {
        k: torch.optim.Adam(
            [{"params": params[k], "lr": rates[k], "name": k}], eps=1e-15, betas=(0.9, 0.999)
        )
        for k in params
    }
    scheduler = torch.optim.lr_scheduler.ExponentialLR(
        optimizers["means"], gamma=0.01 ** (1 / settings.max_steps)
    )
    return optimizers, scheduler


def make_strategy(settings):
    from gsplat.strategy import DefaultStrategy, MCMCStrategy

    values = settings.strategy.model_dump(exclude={"strategy", "opacity_reg", "scale_reg"})
    return (DefaultStrategy if settings.strategy.strategy == "default" else MCMCStrategy)(**values)


def ssim(a, b):
    """Differentiable Gaussian-window SSIM, unit RGB range, valid 11-pixel window."""
    import torch
    from torch.nn import functional as functional

    a, b = a.permute(0, 3, 1, 2), b.permute(0, 3, 1, 2)
    width = min(11, a.shape[-1], a.shape[-2])
    width -= 1 - width % 2
    axis = torch.arange(width, device=a.device, dtype=a.dtype) - (width - 1) / 2
    axis = torch.exp(-axis.square() / (2 * 1.5**2))
    kernel = axis[:, None] * axis[None, :]
    kernel = (kernel / kernel.sum())[None, None].expand(3, 1, width, width)

    def blur(x):
        return functional.conv2d(x, kernel, groups=3)

    ma, mb = blur(a), blur(b)
    va, vb, cov = blur(a * a) - ma * ma, blur(b * b) - mb * mb, blur(a * b) - ma * mb
    return (
        ((2 * ma * mb + 0.01**2) * (2 * cov + 0.03**2))
        / ((ma * ma + mb * mb + 0.01**2) * (va + vb + 0.03**2))
    ).mean()


def rgb_to_sh(colors, device):
    """Convert in float32 so black RGB retains a gradient at the SH clamp boundary."""
    import torch

    rgb = torch.tensor(colors, dtype=torch.float32, device=device) / 255
    return ((rgb - 0.5) / 0.28209479177387814)[:, None, :]


def probe(ordinal: int) -> dict:
    import torch

    from splatforge.core.training import GSPLAT_COMMIT, TrainingSettings

    if importlib.metadata.version("gsplat") != "1.5.3":
        raise ValueError("training.unsupported_release: require exactly gsplat 1.5.3")
    torch.cuda.set_device(ordinal)
    device = torch.device(f"cuda:{ordinal}")
    test = torch.ones(4, device=device, requires_grad=True)
    test.square().sum().backward()
    features = []
    for name in ("default", "absgrad", "antialiased", "mcmc"):
        config = {
            "strategy": {"strategy": "mcmc", "cap_max": 8, "refine_start_iter": 0}
            if name == "mcmc"
            else {"strategy": "default", "absgrad": name == "absgrad"}
        }
        settings = TrainingSettings.model_validate(config)
        params = torch.nn.ParameterDict(
            {
                "means": torch.nn.Parameter(
                    torch.tensor(
                        [[-0.1, -0.1, 2], [0.1, -0.1, 2], [-0.1, 0.1, 2], [0.1, 0.1, 2]],
                        device=device,
                    )
                ),
                "scales": torch.nn.Parameter(torch.full((4, 3), -2.0, device=device)),
                "quats": torch.nn.Parameter(torch.tensor([[1.0, 0, 0, 0]] * 4, device=device)),
                "opacities": torch.nn.Parameter(
                    torch.tensor(
                        [-10.0, 0.0, 0.0, 0.0] if name == "mcmc" else [0.0, 0.0, 0.0, 0.0],
                        device=device,
                    )
                ),
                "sh0": torch.nn.Parameter(torch.ones((4, 1, 3), device=device)),
                "shN": torch.nn.Parameter(torch.zeros((4, 15, 3), device=device)),
            }
        )
        optimizers, scheduler = make_optimizers(params, settings, 1)
        strategy = make_strategy(settings)
        strategy.check_sanity(params, optimizers)
        state = (
            strategy.initialize_state(scene_scale=1)
            if name != "mcmc"
            else (strategy.initialize_state())
        )
        k = torch.tensor([[30.0, 0, 16], [0, 30, 16], [0, 0, 1]], device=device)
        colors, _, info = raster(
            params,
            torch.eye(4, device=device),
            k,
            32,
            32,
            3,
            absgrad=name == "absgrad",
            aa=name == "antialiased",
        )
        strategy.step_pre_backward(params, optimizers, state, 100, info)
        loss = colors.square().mean()
        loss.backward()
        if not torch.isfinite(params["means"].grad).all():
            raise ValueError("training.probe_nonfinite_gradient")
        for optimizer in optimizers.values():
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        scheduler.step()
        options = {"lr": scheduler.get_last_lr()[0]} if name == "mcmc" else {"packed": False}
        strategy.step_post_backward(params, optimizers, state, 100, info, **options)
        torch.cuda.synchronize()
        if not all(torch.isfinite(p).all() for p in params.values()):
            raise ValueError("training.probe_nonfinite_optimizer")
        features.append(name)
    import gsplat.cuda._backend as backend

    package_files = []
    roots = {
        "torch": "torch",
        "gsplat": "gsplat",
        "numpy": "numpy",
        "scipy": "scipy",
        "Pillow": "PIL",
        "pydantic": "pydantic",
        "pydantic_core": "pydantic_core",
    }
    for name, package in roots.items():
        dist = importlib.metadata.distribution(name)
        # direct_url/RECORD may contain a local installation locator. Only stable
        # archive/commit identity and actual numerical code bytes belong in keys.
        origin = json.loads(dist.read_text("direct_url.json") or "{}")
        package_files.append(
            (
                name,
                dist.version,
                origin.get("archive_info", {}).get("hashes", {}).get("sha256"),
                origin.get("vcs_info", {}).get("commit_id"),
            )
        )
        directory = Path(dist.locate_file(package))
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in {
                ".py",
                ".cu",
                ".cuh",
                ".cpp",
                ".h",
                ".hpp",
                ".pyd",
                ".dll",
                ".so",
            }:
                package_files.append(
                    (name, path.relative_to(directory).as_posix(), file_hash(path))
                )
        # Windows wheels also carry numerical DLLs beside the import package,
        # for example numpy.libs/scipy.libs. Hash their actual installed bytes.
        for entry in sorted(dist.files or (), key=str):
            path = Path(dist.locate_file(entry)).resolve()
            if (
                path.suffix.lower() in {".pyd", ".dll", ".so"}
                and path.is_file()
                and not path.is_relative_to(directory.resolve())
            ):
                package_files.append((name, entry.as_posix(), file_hash(path)))
    package_files.append(
        (
            "numerical_environment",
            {
                k: os.environ.get(k)
                for k in (
                    "NVIDIA_TF32_OVERRIDE",
                    "CUBLAS_WORKSPACE_CONFIG",
                    "CUBLAS_FORCE_TF32_COMPUTE",
                )
            },
        )
    )
    for path in (Path(sys._base_executable), Path(sys.base_prefix) / "python312.dll"):
        if path.is_file():
            package_files.append((path.name, file_hash(path)))
    for path in (Path(backend._C.__file__),):
        if path.is_file():
            package_files.append((path.name, file_hash(path)))
    import ctypes

    runtime_path = Path(torch.__file__).parent / "lib/cudart64_12.dll"
    if not runtime_path.is_file():
        raise ValueError("training.runtime_evidence_unavailable: Windows CUDA 12 DLL required")
    cudart = ctypes.CDLL(str(runtime_path))
    runtime_version = ctypes.c_int()
    cudart.cudaRuntimeGetVersion.argtypes = [ctypes.POINTER(ctypes.c_int)]
    cudart.cudaRuntimeGetVersion.restype = ctypes.c_int
    if cudart.cudaRuntimeGetVersion(ctypes.byref(runtime_version)) != 0:
        raise ValueError("training.cuda_runtime_query_failed")
    smi = shutil.which("nvidia-smi")
    if not smi:
        raise ValueError("training.missing_driver_evidence")
    observed = (
        subprocess.run(
            [smi, "--query-gpu=uuid,driver_version", "--format=csv,noheader"],
            cwd=Path(sys.executable).parent,
            env=dict(os.environ),
            shell=False,
            capture_output=True,
            timeout=10,
            check=True,
        )
        .stdout.decode()
        .strip()
        .splitlines()
    )
    gpu = torch.cuda.get_device_properties(ordinal)
    uuid = str(gpu.uuid)
    matched = [row.split(",") for row in observed if uuid.lower() in row.lower()]
    if len(matched) != 1:
        raise ValueError("training.gpu_uuid_mismatch")
    return {
        "worker_version": 1,
        "worker_sha256": worker_hash(),
        "python_sha256": file_hash(Path(sys.executable)),
        "python_version": sys.version,
        "torch_version": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "gsplat_version": "1.5.3",
        "gsplat_commit": GSPLAT_COMMIT,
        "packages_digest": hashlib.sha256(json.dumps(package_files).encode()).hexdigest(),
        "cuda_runtime": str(runtime_version.value),
        "driver": matched[0][1].strip(),
        "gpu_uuid": uuid,
        "gpu_name": gpu.name,
        "gpu_ordinal": ordinal,
        "compute_capability": [gpu.major, gpu.minor],
        "device_total_bytes": gpu.total_memory,
        "features": features,
        "kernel_backward_optimizer": True,
        "determinism": "seeded_gpu_not_bitwise_proven",
    }


class Events:
    def __init__(self, path, total, start):
        self.path, self.total, self.step, self.sequence = Path(path), total, start, 0

    def emit(self, event, **values):
        self.sequence += 1
        data = {
            "protocol_version": 1,
            "sequence": self.sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "step": self.step,
            "total_steps": self.total,
            **values,
        }
        with self.path.open("ab") as stream:
            stream.write(json.dumps(data, allow_nan=False).encode() + b"\n")
            stream.flush()


def train(config):
    import numpy as np
    import torch
    from PIL import Image
    from scipy.spatial import cKDTree

    from splatforge.core.dataset import PreparedDatasetComponent
    from splatforge.core.training import TrainingBackendIdentity, TrainingSettings, training_recipe

    settings = TrainingSettings.model_validate(config["settings"])
    events = Events(config["events_path"], settings.max_steps, config["start_step"])
    events.emit("worker.started")
    try:
        torch.cuda.set_device(config["backend"]["gpu_ordinal"])
        device = torch.device(f"cuda:{config['backend']['gpu_ordinal']}")
        if worker_hash() != config["backend"]["worker_sha256"]:
            raise ValueError("training.stale_worker")
        random.seed(settings.seed)
        np.random.seed(settings.seed)
        torch.manual_seed(settings.seed)
        torch.cuda.manual_seed(settings.seed)
        torch.set_num_threads(2)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.cuda.reset_peak_memory_stats()
        dataset_path = Path(config["dataset_path"])
        metadata = json.loads((dataset_path / "dataset.json").read_text(encoding="utf-8"))
        data = PreparedDatasetComponent.model_validate(
            {k: v for k, v in metadata.items() if k in PreparedDatasetComponent.model_fields}
        )
        if data.semantic_digest != config["dataset_digest"]:
            raise ValueError("training.stale_dataset")
        expected_recipe = training_recipe(
            data.semantic_digest,
            settings,
            TrainingBackendIdentity.model_validate(config["backend"]).numerical_identity,
        )
        if expected_recipe != config["training_recipe"]:
            raise ValueError("training.request_recipe_mismatch")
        cameras = {c.camera_id: c for c in data.cameras}
        held_out = set(settings.split.held_out_view_ids)
        train_ids = [i for i, v in enumerate(data.views) if v.view_id not in held_out]
        eval_ids = [i for i, v in enumerate(data.views) if v.view_id in held_out]
        if not train_ids or len(eval_ids) != len(held_out):
            raise ValueError("training.invalid_split")
        positions = []
        for view in data.views:
            r = np.asarray(view.pose.rotation_matrix())
            positions.append(-r.T @ np.asarray(view.pose.translation))
        positions = np.asarray(positions)
        scene_scale = float(np.linalg.norm(positions - positions.mean(0), axis=1).max()) * 1.1
        if scene_scale <= 0:
            raise ValueError("training.degenerate_camera_extent")
        cache, cache_size = OrderedDict(), 0

        def load(index):
            nonlocal cache_size
            if index in cache:
                cache.move_to_end(index)
                return cache[index]
            view, image = data.views[index], data.images[index]
            camera = cameras[view.camera_id]
            w, h = (
                max(1, image.width // settings.data_factor),
                max(1, image.height // settings.data_factor),
            )
            with Image.open(dataset_path / "images" / image.name) as source:
                pixels = np.asarray(
                    source.convert("RGB").resize((w, h), Image.Resampling.BOX)
                ).copy()
            p = camera.parameters
            fx, fy = p[0], p[1] if camera.model == "PINHOLE" else p[0]
            cx, cy = p[2:4] if camera.model == "PINHOLE" else p[1:3]
            k = torch.tensor(
                [
                    [fx * w / image.width, 0, cx * w / image.width],
                    [0, fy * h / image.height, cy * h / image.height],
                    [0, 0, 1],
                ],
                device=device,
            )
            matrix = torch.eye(4, device=device)
            matrix[:3, :3] = torch.tensor(view.pose.rotation_matrix(), device=device)
            matrix[:3, 3] = torch.tensor(view.pose.translation, device=device)
            while cache and cache_size + pixels.nbytes > 512 * 1024**2:
                cache_size -= cache.popitem(last=False)[1][0].nbytes
            value = (pixels, matrix, k, w, h)
            cache[index] = value
            cache_size += pixels.nbytes
            return value

        events.emit("dataset.loaded", identity=data.semantic_digest)
        if config.get("resume_path"):
            state = torch.load(config["resume_path"], map_location=device, weights_only=True)
            if state["recipe"] != config["training_recipe"] or state["step"] != events.step:
                raise ValueError("training.incompatible_checkpoint")
            params = torch.nn.ParameterDict(
                {k: torch.nn.Parameter(v) for k, v in state["params"].items()}
            )
        else:
            if events.step:
                raise ValueError("training.missing_resume_payload")
            points, colors = [], []
            with (dataset_path / "sparse/0/points3D.bin").open("rb") as stream:
                count = struct.unpack("<Q", stream.read(8))[0]
                if not 4 <= count <= config["limits"]["max_gaussians"]:
                    raise ValueError("training.invalid_initial_point_count")
                for _ in range(count):
                    row = struct.unpack("<Q3d3BdQ", stream.read(51))
                    points.append(row[1:4])
                    colors.append(row[4:7])
                    stream.seek(row[-1] * 8, 1)
            # M10 native IDs/point order are transport, not numerical identity.
            ordered = sorted(zip(points, colors, strict=True))
            xyz = np.asarray([row[0] for row in ordered], dtype=np.float32)
            colors = [row[1] for row in ordered]
            distances = cKDTree(xyz).query(xyz, k=4)[0][:, 1:]
            scales = np.log(np.maximum(np.sqrt((distances**2).mean(1)), 1e-7))
            params = torch.nn.ParameterDict(
                {
                    "means": torch.nn.Parameter(torch.tensor(xyz, device=device)),
                    "scales": torch.nn.Parameter(
                        torch.tensor(
                            np.repeat(scales[:, None], 3, 1), device=device, dtype=torch.float32
                        )
                    ),
                    "quats": torch.nn.Parameter(torch.rand((count, 4), device=device)),
                    "opacities": torch.nn.Parameter(
                        torch.full(
                            (count,),
                            math.log(settings.init_opacity / (1 - settings.init_opacity)),
                            device=device,
                        )
                    ),
                    "sh0": torch.nn.Parameter(
                        rgb_to_sh(colors, device)
                    ),
                    "shN": torch.nn.Parameter(
                        torch.zeros((count, (settings.sh_degree + 1) ** 2 - 1, 3), device=device)
                    ),
                }
            )
            state = None
        optimizers, scheduler = make_optimizers(params, settings, scene_scale)
        strategy = make_strategy(settings)
        strategy.check_sanity(params, optimizers)
        strategy_state = (
            strategy.initialize_state(scene_scale=scene_scale)
            if (settings.strategy.strategy == "default")
            else strategy.initialize_state()
        )
        if state:
            for key, optimizer in optimizers.items():
                optimizer.load_state_dict(state["optimizers"][key])
            scheduler.load_state_dict(state["scheduler"])
            strategy_state = state["strategy_state"]
            random.setstate(state["python_rng"])
            np.random.set_state(
                (
                    state["numpy_rng"][0],
                    np.asarray(state["numpy_rng"][1], dtype=np.uint32),
                    *state["numpy_rng"][2:],
                )
            )
            torch.set_rng_state(state["torch_rng"].cpu())
            torch.cuda.set_rng_state(state["cuda_rng"].cpu(), device=device)
        if (
            settings.strategy.strategy == "mcmc"
            and len(params["means"]) > settings.strategy.cap_max
        ):
            raise ValueError("training.initial_sfm_exceeds_mcmc_cap")
        start = time.monotonic()
        previous_metrics = state["metrics"] if state else {}
        loss_value = previous_metrics.get("training_loss")
        events.emit("training.started", gaussian_count=len(params["means"]))

        def render(index, degree):
            pixels, matrix, k, w, h = load(index)
            reference = torch.tensor(pixels, device=device, dtype=torch.float32)[None] / 255
            rendered, _, info = raster(
                params,
                matrix,
                k,
                w,
                h,
                degree,
                absgrad=getattr(settings.strategy, "absgrad", False),
                aa=settings.antialiased,
                near_plane=settings.near_plane,
                far_plane=settings.far_plane,
            )
            return rendered, reference, info

        for iteration in range(events.step, config["terminal_step"]):
            degree = min(settings.sh_degree, iteration // settings.sh_degree_interval)
            rendered, reference, info = render(random.choice(train_ids), degree)
            strategy.step_pre_backward(params, optimizers, strategy_state, iteration, info)
            loss = (1 - settings.ssim_weight) * (rendered - reference).abs().mean() + (
                settings.ssim_weight * (1 - ssim(rendered, reference))
            )
            if settings.strategy.strategy == "mcmc":
                loss += settings.strategy.opacity_reg * params["opacities"].sigmoid().mean()
                loss += settings.strategy.scale_reg * params["scales"].exp().mean()
            loss.backward()
            for optimizer in optimizers.values():
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            scheduler.step()
            options = (
                {"lr": scheduler.get_last_lr()[0]}
                if (settings.strategy.strategy == "mcmc")
                else {"packed": False}
            )
            strategy.step_post_backward(
                params, optimizers, strategy_state, iteration, info, **options
            )
            if not 0 < len(params["means"]) <= config["limits"]["max_gaussians"]:
                raise ValueError("training.resource_limit: Gaussian count")
            events.step = iteration + 1
            if events.step % 10 == 0 or events.step == config["terminal_step"]:
                loss_value = float(loss.detach())
                events.emit(
                    "training.progress",
                    gaussian_count=len(params["means"]),
                    loss=loss_value,
                    peak_allocated_cuda_bytes=torch.cuda.max_memory_allocated(),
                )
        metrics = {
            "training_loss": loss_value,
            "duration_seconds": previous_metrics.get("duration_seconds", 0)
            + time.monotonic()
            - start,
            "peak_allocated_cuda_bytes": max(
                torch.cuda.max_memory_allocated(),
                previous_metrics.get("peak_allocated_cuda_bytes", 0) or 0,
            ),
            "evaluation_views": 0,
            "lpips_status": "unavailable_no_local_weights",
        }
        for key in (
            "evaluation_views",
            "evaluation_step",
            "evaluation_psnr",
            "evaluation_ssim",
            "evaluation_lpips",
            "per_source_group",
        ):
            if key in previous_metrics:
                metrics[key] = previous_metrics[key]
        if eval_ids and (
            events.step % settings.evaluation_every == 0 or events.step == settings.max_steps
        ):
            scores = []
            groups = {}
            with torch.no_grad():
                for index in eval_ids:
                    rendered, reference, _ = render(
                        index,
                        min(
                            settings.sh_degree,
                            max(0, events.step - 1) // settings.sh_degree_interval,
                        ),
                    )
                    psnr = float(
                        -10 * torch.log10((rendered - reference).square().mean().clamp_min(1e-12))
                    )
                    score = (psnr, float(ssim(rendered, reference)))
                    scores.append(score)
                    group = config.get("source_groups", {}).get(
                        str(data.views[index].view_id), "unknown"
                    )
                    groups.setdefault(group, []).append(score)
            metrics.update(
                evaluation_views=len(eval_ids),
                evaluation_step=events.step,
                evaluation_psnr=sum(s[0] for s in scores) / len(scores),
                evaluation_ssim=sum(s[1] for s in scores) / len(scores),
                per_source_group={
                    k: {
                        "views": len(v),
                        "psnr": sum(s[0] for s in v) / len(v),
                        "ssim": sum(s[1] for s in v) / len(v),
                    }
                    for k, v in groups.items()
                },
            )
            events.emit("evaluation.completed", gaussian_count=len(params["means"]))
        output = Path(config["output_path"])
        output.mkdir()
        common = {
            "dataset_digest": data.semantic_digest,
            "settings": settings.model_dump(mode="json"),
            "backend": config["backend"],
            "gaussian_count": len(params["means"]),
            "metrics": metrics,
        }
        if config["scene"]:
            from splatforge.adapters.gaussian_ply import properties

            if (
                len(params["means"]) * len(properties(settings.sh_degree)) * 4 + 16384
                > (config["limits"]["max_scene_bytes"])
            ):
                raise ValueError("training.resource_limit: scene bytes before export")
            export_ply(output / "scene.ply", params, settings.sh_degree)
            if (output / "scene.ply").stat().st_size > config["limits"]["max_scene_bytes"]:
                raise ValueError("training.resource_limit: scene bytes")
            # The independent application reader computes semantics after process teardown.
            result = {
                **common,
                "method_id": settings.method_id,
                "final_step": events.step,
                "sh_degree": settings.sh_degree,
                "ply_sha256": file_hash(output / "scene.ply"),
                "ply_size": (output / "scene.ply").stat().st_size,
                "checkpoint_lineage": config["checkpoint_lineage"],
            }
            events.emit(
                "scene.exported", identity=result["ply_sha256"], gaussian_count=len(params["means"])
            )
        else:
            (output / "checkpoint").mkdir()
            temporary = output / "checkpoint/state.pt.partial"
            nrng = np.random.get_state()

            class LimitedWriter:
                def __init__(self, stream):
                    self.stream, self.written = stream, 0

                def write(self, data):
                    if self.written + len(data) > config["limits"]["max_checkpoint_bytes"]:
                        raise ValueError("training.resource_limit: checkpoint bytes during write")
                    self.written += len(data)
                    return self.stream.write(data)

                def flush(self):
                    self.stream.flush()

            with temporary.open("wb") as native_stream:
                torch.save(
                    {
                        "recipe": config["training_recipe"],
                        "step": events.step,
                        "params": params.state_dict(),
                        "optimizers": {k: o.state_dict() for k, o in optimizers.items()},
                        "scheduler": scheduler.state_dict(),
                        "strategy_state": strategy_state,
                        "python_rng": random.getstate(),
                        "numpy_rng": (nrng[0], nrng[1].tolist(), *nrng[2:]),
                        "torch_rng": torch.get_rng_state(),
                        "cuda_rng": torch.cuda.get_rng_state(device=device),
                        "metrics": metrics,
                    },
                    LimitedWriter(native_stream),
                )
                native_stream.flush()
                os.fsync(native_stream.fileno())
            if temporary.stat().st_size > config["limits"]["max_checkpoint_bytes"]:
                raise ValueError("training.resource_limit: checkpoint bytes")
            temporary.rename(output / "checkpoint/state.pt")
            native = output / "checkpoint/state.pt"
            result = {
                **common,
                "step": events.step,
                "native": {
                    "path": "checkpoint/state.pt",
                    "sha256": file_hash(native),
                    "size": native.stat().st_size,
                },
                "state_evidence": (
                    "parameters_optimizers_schedulers_strategy_python_numpy_torch_cuda_rng_v1"
                ),
                "resumed_from_checkpoint": config.get("resume_digest"),
            }
            events.emit(
                "checkpoint.saved",
                identity=result["native"]["sha256"],
                gaussian_count=len(params["means"]),
            )
        result_path = Path(config["result_path"])
        result_path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        events.emit(
            "worker.completed", identity=file_hash(result_path), gaussian_count=len(params["means"])
        )
    except Exception as exc:
        events.emit(
            "worker.failed",
            failure="gpu_oom" if isinstance(exc, torch.cuda.OutOfMemoryError) else "worker_error",
            message=str(exc)[:2048],
        )
        raise


def export_ply(path, params, degree):
    import numpy as np
    import torch

    from splatforge.adapters.gaussian_ply import properties

    count = len(params["means"])
    names = properties(degree)
    with path.open("wb") as stream:
        stream.write(
            (
                "ply\nformat binary_little_endian 1.0\nelement vertex "
                + str(count)
                + "\n"
                + "".join("property float " + name + "\n" for name in names)
                + "end_header\n"
            ).encode()
        )
        for start in range(0, count, 8192):
            batch = {k: v[start : start + 8192].detach() for k, v in params.items()}
            xyz = batch["means"]
            rows = torch.cat(
                [
                    xyz,
                    torch.zeros_like(xyz),
                    batch["sh0"].flatten(1),
                    batch["shN"].transpose(1, 2).flatten(1),
                    batch["opacities"][:, None],
                    batch["scales"],
                    torch.nn.functional.normalize(batch["quats"], dim=1),
                ],
                dim=1,
            )
            stream.write(rows.cpu().numpy().astype(np.dtype("<f4")).tobytes())
        stream.flush()
        os.fsync(stream.fileno())
