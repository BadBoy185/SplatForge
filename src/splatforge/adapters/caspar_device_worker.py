"""Disposable CUDA runtime/driver identity probe, never loaded by core/application."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
from pathlib import Path


def device_identity(index: int, runtime_path: str) -> dict[str, object]:
    if os.environ.get("CUDA_VISIBLE_DEVICES") or os.environ.get("CUDA_DEVICE_ORDER"):
        raise ValueError("CUDA device masking/order overrides unsupported; use an unmasked runtime")
    runtime = ctypes.CDLL(runtime_path)
    library = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1")

    def check(status: int) -> None:
        if status:
            raise ValueError(f"CUDA driver operation failed with status {status}")

    count, device, driver = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    check(runtime.cudaGetDeviceCount(ctypes.byref(count)))
    if not 0 <= index < count.value:
        raise ValueError(f"Requested GPU {index} missing; CUDA device count is {count.value}")
    # Resolve the CUDA runtime ordinal actually used by Caspar to its driver device.
    # Driver inventory ordering alone must not identify a different numerical GPU.
    pci = ctypes.create_string_buffer(64)
    check(runtime.cudaDeviceGetPCIBusId(pci, len(pci), index))
    check(library.cuInit(0))
    check(library.cuDeviceGetByPCIBusId(ctypes.byref(device), pci))
    name, uuid = ctypes.create_string_buffer(256), ctypes.create_string_buffer(16)
    check(library.cuDeviceGetName(name, len(name), device))
    check(library.cuDeviceGetUuid(ctypes.byref(uuid), device))
    check(library.cuDriverGetVersion(ctypes.byref(driver)))
    major, minor = ctypes.c_int(), ctypes.c_int()
    check(library.cuDeviceComputeCapability(ctypes.byref(major), ctypes.byref(minor), device))
    if os.name == "nt":
        path_buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.WinDLL("kernel32.dll").GetModuleFileNameW(
            ctypes.c_void_p(library._handle), path_buffer, len(path_buffer)
        )
        if not 0 < length < len(path_buffer):
            raise ValueError("Cannot identify the loaded CUDA driver binary")
        driver_path = Path(path_buffer.value)
    else:
        with Path("/proc/self/maps").open(encoding="utf-8") as stream:
            paths = {
                line.split()[-1]
                for line in stream.read(1024**2).splitlines()
                if "/libcuda.so" in line and not line.endswith("(deleted)")
            }
        if len(paths) != 1:
            raise ValueError("Cannot identify the loaded CUDA driver binary")
        driver_path = Path(paths.pop())
    with driver_path.open("rb") as stream:
        driver_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "index": index,
        "uuid": uuid.raw.hex(),
        "name": name.value.decode("utf-8"),
        "driver_version": driver.value,
        "driver_binary_sha256": driver_digest,
        "compute_major": major.value,
        "compute_minor": minor.value,
    }


def main() -> None:
    try:
        print(json.dumps(device_identity(int(sys.argv[1]), sys.argv[2])))
    except (ValueError, OSError, AttributeError) as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
