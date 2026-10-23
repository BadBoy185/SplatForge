"""Disposable BA probe requires numerical output and owns cleanup/quarantine."""

import json
import shutil
import sys
from pathlib import Path

import pytest
from test_caspar_capabilities import DEVICE
from test_colmap_capabilities import IDENTITY, process_result

from splatforge.adapters import caspar_probe
from splatforge.adapters.caspar_probe import observe_caspar_device, probe_caspar
from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.process_runner import ProcessRequest
from splatforge.application.doctor_contracts import DoctorTeardownError
from splatforge.core.capabilities import ExecutableSelection, ExecutableSource


class Probe:
    _same_identity = staticmethod(ColmapCapabilityAdapter._same_identity)
    _cleanup_workspace = staticmethod(ColmapCapabilityAdapter._cleanup_workspace)

    def __init__(self, mode):
        self.mode, self.calls = mode, []

    def _run(self, executable, argv, timeout, *, working_directory, environment):
        self.calls.append((executable, argv, working_directory))
        request = ProcessRequest(
            executable=executable,
            argv=argv,
            working_directory=working_directory,
            environment=environment,
            timeout_seconds=timeout,
        )
        if executable == sys.executable:
            if self.mode == "gpu_missing":
                return process_result(
                    request,
                    exit_code=1,
                    stdout=json.dumps({"error": "Requested GPU 0 missing"}).encode(),
                )
            return process_result(request, stdout=DEVICE.model_dump_json().encode())
        if self.mode == "unresolved":
            raise DoctorTeardownError("quarantine synthetic probe")
        source = Path(argv[argv.index("--input_path") + 1])
        output = Path(argv[argv.index("--output_path") + 1])
        for path in source.iterdir():
            shutil.copyfile(path, output / path.name)
        if self.mode == "malformed":
            (output / "points3D.bin").write_bytes(b"bad")
        return process_result(
            request,
            identity=IDENTITY,
            stderr=(b"Creating Caspar bundle adjuster\n"
                    b"Caspar: CONVERGED_SCORE_THRESHOLD after 2 iters"),
        )


def selection():
    return ExecutableSelection(
        source=ExecutableSource.EXPLICIT, requested=IDENTITY.resolved_path, identity=IDENTITY
    )


@pytest.mark.parametrize("mode", ["success", "malformed", "gpu_missing", "unresolved"])
def test_bounded_caspar_probe_validates_model_and_quarantines_unresolved(mode, monkeypatch):
    monkeypatch.setattr(caspar_probe, "cuda_runtime_path", lambda _: Path("synthetic-cudart.dll"))
    probe = Probe(mode)
    if mode == "success":
        assert probe_caspar(probe, selection(), 0) == DEVICE
        argv = next(argv for executable, argv, _ in probe.calls if executable != sys.executable)
        assert argv[argv.index("--BundleAdjustment.backend") + 1] == "CASPAR"
        assert argv[argv.index("--BundleAdjustmentCaspar.gpu_index") + 1] == "0"
    else:
        with pytest.raises((ValueError, DoctorTeardownError)):
            probe_caspar(probe, selection(), 0)
    workspace = probe.calls[0][2]
    if mode == "unresolved":
        assert workspace.exists()
        probe._cleanup_workspace(workspace, workspace.stat())
    else:
        assert not workspace.exists()


def test_cuda_ordinal_mismatch_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(caspar_probe, "cuda_runtime_path", lambda _: Path("synthetic-cudart.dll"))
    with pytest.raises(ValueError, match="ordinal differs"):
        observe_caspar_device(Probe("success"), selection(), 1, tmp_path)


def test_cuda_environment_mask_refused_before_loading_driver(monkeypatch):
    from splatforge.adapters.caspar_device_worker import device_identity

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,0")
    with pytest.raises(ValueError, match="masking/order"):
        device_identity(0, "unused-runtime.dll")
