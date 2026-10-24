"""One immutable request per disposable CUDA process."""

import contextlib
import importlib.util
import json
import sys
import traceback
from pathlib import Path

# Register only our packages. Adding the application's site-packages directory to
# sys.path could replace the isolated runtime's Torch/Pydantic builds.
_root = Path(__file__).resolve().parents[1]
for _name in ("splatforge", "splatforge_gsplat_worker"):
    _directory = _root / _name
    _spec = importlib.util.spec_from_file_location(
        _name, _directory / "__init__.py", submodule_search_locations=[str(_directory)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)


def main() -> int:
    from splatforge.core.training_protocol import WorkerProbeRequest, WorkerTrainingRequest
    from splatforge_gsplat_worker.runtime import probe, train

    path = Path(sys.argv[1])
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError("training.request_resource_limit")
    config = json.loads(path.read_text(encoding="utf-8"))
    with contextlib.redirect_stdout(sys.stderr):
        if config["operation"] == "probe":
            config = WorkerProbeRequest.model_validate(config).model_dump(mode="json")
            result = probe(config["gpu_ordinal"])
            Path(config["result_path"]).write_text(json.dumps(result), encoding="utf-8")
        else:
            config = WorkerTrainingRequest.model_validate(config).model_dump(mode="json")
            train(config)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1) from None
