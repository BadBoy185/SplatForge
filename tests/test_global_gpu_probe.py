"""Ceres GPU prerequisite probe validates numerical transport and owns quarantine."""

import shutil
import sys
from pathlib import Path

import pytest
from test_caspar_capabilities import DEVICE
from test_caspar_probe import Probe, selection
from test_colmap_capabilities import IDENTITY, process_result
from test_global_gpu import SPARSE

from splatforge.adapters import caspar_probe
from splatforge.adapters.global_gpu import probe_global_ceres_gpu
from splatforge.adapters.process_runner import ProcessRequest
from splatforge.application.doctor_contracts import DoctorTeardownError


class CeresProbe(Probe):
    def _run(self, executable, argv, timeout, *, working_directory, environment):
        if executable == sys.executable:
            return super()._run(
                executable,
                argv,
                timeout,
                working_directory=working_directory,
                environment=environment,
            )
        self.calls.append((executable, argv, working_directory))
        request = ProcessRequest(
            executable=executable,
            argv=argv,
            working_directory=working_directory,
            environment=environment,
            timeout_seconds=timeout,
        )
        if self.mode == "unresolved":
            raise DoctorTeardownError("quarantine synthetic Ceres probe")
        source = Path(argv[argv.index("--input_path") + 1])
        output = Path(argv[argv.index("--output_path") + 1])
        for path in source.iterdir():
            shutil.copyfile(path, output / path.name)
        if self.mode == "malformed":
            (output / "points3D.bin").write_bytes(b"bad")
        text = SPARSE
        if self.mode == "fallback":
            text += "Ceres compiled without CUDA support; falling back to CPU"
        elif self.mode == "zero_work":
            text = text.replace("(2)", "(0)")
        return process_result(
            request,
            identity=IDENTITY,
            stderr=text.encode(),
            stderr_truncated=self.mode == "truncated",
        )


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "malformed",
        "gpu_missing",
        "unresolved",
        "fallback",
        "truncated",
        "zero_work",
    ],
)
def test_ceres_probe_checks_solver_payload_and_quarantines_unresolved(mode, monkeypatch):
    monkeypatch.setattr(caspar_probe, "cuda_runtime_path", lambda _: Path("synthetic-cudart.dll"))
    probe = CeresProbe(mode)
    if mode == "success":
        assert probe_global_ceres_gpu(probe, selection(), 0) == DEVICE
        argv = next(args for executable, args, _ in probe.calls if executable != sys.executable)
        assert argv[argv.index("--BundleAdjustment.backend") + 1] == "CERES"
        assert argv[argv.index("--BundleAdjustmentCeres.gpu_index") + 1] == "0"
        assert argv[argv.index("--BundleAdjustmentCeres.min_num_images_gpu_solver") + 1] == "0"
    else:
        with pytest.raises((ValueError, DoctorTeardownError)):
            probe_global_ceres_gpu(probe, selection(), 0)
    workspace = probe.calls[0][2]
    if mode == "unresolved":
        assert workspace.exists()
        probe._cleanup_workspace(workspace, workspace.stat())
    else:
        assert not workspace.exists()
