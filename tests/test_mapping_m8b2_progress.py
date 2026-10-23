"""All seven execution modes have independent nonlinear performance signatures."""

from pathlib import Path

from test_caspar_capabilities import DEVICE

from splatforge.application.work_models import mapping_progress_plan
from splatforge.core.execution import (
    GlobalAcceleratedRoute,
    HierarchicalMappingRoute,
    IncrementalMappingRoute,
    RunSnapshot,
)
from splatforge.core.progress import ExecutionHardwareProfile
from splatforge.core.reconstruction import (
    GlobalAcceleratedBackend,
    GlobalAcceleratedSettings,
    GlobalAccelerationSettings,
    HierarchicalMapperSettings,
    HierarchicalMappingBackend,
    IncrementalMapperSettings,
    IncrementalMappingBackend,
)


def test_all_classical_mode_history_is_separate_without_live_percent():
    path = Path(__file__).parent / "fixtures" / "m8a-global-snapshot.json"
    original = RunSnapshot.model_validate_json(path.read_bytes()).route
    routes = [original]
    data = original.model_dump(exclude={"route_id", "settings", "backend"})
    native = original.backend.model_dump(exclude={"adapter_id", "operation"})
    for gp, ba in ((0, "cpu"), ("cpu", 0), (0, 0)):
        routes.append(
            GlobalAcceleratedRoute(
                **data,
                settings=GlobalAcceleratedSettings(
                    acceleration=GlobalAccelerationSettings(positioning_device=gp, ba_device=ba)
                ),
                backend=GlobalAcceleratedBackend(
                    **native,
                    positioning_device=DEVICE if gp != "cpu" else None,
                    ba_device=DEVICE if ba != "cpu" else None,
                ),
            )
        )
    for caspar in (False, True):
        routes.append(
            IncrementalMappingRoute(
                **data,
                settings=IncrementalMapperSettings(
                    ba_local_backend="CASPAR" if caspar else "CERES",
                    ba_global_backend="CASPAR" if caspar else "CERES",
                    ba_gpu_index=0 if caspar else -1,
                ),
                backend=IncrementalMappingBackend(**native, device=DEVICE if caspar else None),
            )
        )
    routes.append(
        HierarchicalMappingRoute(
            **data,
            settings=HierarchicalMapperSettings(),
            backend=HierarchicalMappingBackend(**native),
        )
    )
    plans = [mapping_progress_plan(route, ExecutionHardwareProfile()) for route in routes]
    assert len({p.signature.model_dump_json() for p in plans}) == 7
    assert all(p.work.mode == "phase" and p.work.historical_job_duration for p in plans)
    assert plans[-1].work.work_model_id == "mapping.hierarchical_phases_v1"
    assert [p.signature.hardware.device for p in plans] == [
        "cpu",
        "gpu",
        "gpu",
        "gpu",
        "cpu",
        "gpu",
        "cpu",
    ]
    assert len({route.recipe_key() for route in routes}) == 7
