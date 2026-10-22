# Controlled Windows GPU runtime

SplatForge executes native COLMAP in contained child processes. Learned CUDA
inference additionally needs compatible ONNX Runtime, CUDA and cuDNN libraries.
A working GPU SIFT probe does not establish learned inference capability.
The complete method/model/runtime combination must pass its functional probe.

Runtime provisioning is an explicit operator setup action, separate from numerical
attempts. Doctor and processing never download or install these dependencies.
No Python ML runtime or PyTorch dependency is needed for native COLMAP inference.

## Isolated runtime setup

1. Identify the selected native COLMAP executable, its ONNX provider build and the
   GPU/driver. Inspect the provider's PE imports to distinguish CUDA 12 from CUDA 13;
   an ONNX Runtime version alone does not identify its CUDA build variant.
2. Select a compatible official NVIDIA Windows x64 cuDNN archive. Save the exact
   redistributable manifest, archive URL, version, size and expected SHA-256. Verify
   the complete downloaded archive before extracting any runtime library.
3. Copy the complete selected COLMAP installation into a new owned, versioned
   directory outside Git. Preserve its existing layout and inert `COLMAP.bat`
   locator. Copy files independently; refuse redirected sources, hardlinks and
   overwriting an existing bundle. Keep the original installation unchanged.
4. Add the cuDNN runtime DLL set from that archive and its license to the new
   bundle. Pin the required CUDA runtime DLLs from an explicitly selected official
   NVIDIA toolkit installation or verified redistributable. Include transitive
   and dynamically loaded dependencies required by the selected build. Record
   source identity, size and SHA-256 for every file in a local bundle manifest.
5. Select the new native executable explicitly. Existing recognized-layout
   discovery prepends the bundle's root/bin/lib directories to the COLMAP child's
   PATH and scopes its Qt plugin directories. The system PATH stays unchanged.
6. Run Doctor and the real integration matrix with explicit GPU policy. Retain
   diagnostics for any failure; do not substitute CPU inside a frozen GPU attempt.

Official references: [NVIDIA Windows installation and manifests](https://docs.nvidia.com/cudnn/latest/installation/backend/windows/),
[NVIDIA support matrix](https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/support-matrix.html),
[ONNX CUDA provider requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).
NVIDIA archives are setup inputs, not end-user installers. Retain license notices;
commercial redistribution rights require their own review before shipping a bundle.

An official archive's checksum verifies that archive's identity. A locally recorded
checksum for an existing CUDA installation pins the observed bytes; it is not an
independent vendor checksum attestation. Driver libraries remain system-owned.
Runtime manifests and machine-specific paths belong in ignored local storage.

## Validated bundle inputs

The M7b.3 operator setup uses native COLMAP 4.2.1 (`bd1fcf6`), its ONNX Runtime
1.30.0 CUDA 12 provider, existing NVIDIA CUDA 12.8 runtime DLLs and cuDNN
9.27.0.42 for CUDA 12, Windows x64. This is one tested combination rather than a
global minimum for every supported method.

The official [cuDNN 9.27.0 manifest](https://developer.download.nvidia.com/compute/cudnn/redist/redistrib_9.27.0.json)
pins `cudnn-windows-x86_64-9.27.0.42_cuda12-archive.zip`, 1,924,314,965 bytes,
with SHA-256:

```text
93949680d6499ad0f17fc1abb131825c9dd41b460844513f608e840e0c8ce72b
```

The verified archive contains its runtime libraries under `bin/x64/`. The local
bundle contains all ten `cudnn*.dll` files and the archive's `LICENSE`. CUDA
dependencies are `cudart64_12.dll`, `cublas64_12.dll`, `cublasLt64_12.dll`,
`cufft64_11.dll`, `nvrtc64_120_0.dll`, `nvrtc-builtins64_128.dll` and
`nvJitLink_120_0.dll`. Their individual observed byte identities and source paths
are recorded in the ignored local bundle manifest. Preserve the original NVIDIA
toolkit license information when preparing any redistributable package.

See [M7b real GPU integration results](M7B.md#m7b3-isolated-gpu-runtime-validation)
for all thirteen compatible combinations, execution evidence and limitations.

## Validation and use

Choose actual local paths in a fresh PowerShell session:

```powershell
$colmapExe = "C:\SplatForge Runtime\colmap-4.2.1-cuda12-cudnn9\bin\colmap.exe"
$modelRoot = "C:\SplatForge Models\COLMAP"
.\.venv\Scripts\splatforge.exe doctor --deep --colmap $colmapExe --colmap-model-dir $modelRoot --json
.\.venv\Scripts\splatforge.exe sfm resolve --profile high --device gpu:0 --colmap $colmapExe --colmap-model-dir $modelRoot
```

Doctor's aggregate report is not the route resolver. A long sequential deep probe
can outlive the existing 30-second functional/resource evidence window; expired
items honestly become `unknown`. Generic learned GPU entries can also require a
route-specific inference probe. In the local setup check, the aggregate deep report
outlived that window, while a fresh `sfm resolve --profile fast --device auto`
positively selected LOMA_B128 + LOMA_B128 on `gpu:0`. Inspect reasons and timestamps;
use exact route resolution and the real matrix to certify runnable methods rather
than interpreting an expired aggregate as a missing cuDNN library. No freshness
policy or Doctor behavior was changed in this provisioning task.

The integration environment is scoped to that PowerShell session and its children:

```powershell
$env:SPLATFORGE_TEST_COLMAP = $colmapExe
$env:SPLATFORGE_COLMAP_MODEL_DIR = $modelRoot
$env:SPLATFORGE_TEST_COLMAP_LEARNED = "1"
$env:SPLATFORGE_TEST_COLMAP_HEAVY = "1"
$env:SPLATFORGE_TEST_COLMAP_DEVICE = "gpu:0"
.\.venv\Scripts\python.exe -m pytest tests/test_matching_integration.py -k real_explicit_raw_then_verification -rs -s
```

All 13 compatible extractor/matcher combinations must execute rather than skip on
a fully provisioned validation machine. The fixture checks exact external pairs,
raw-only matches, separate verification, frozen backend/model/device identities,
independent caches, published byte integrity and separate PAIRS progress contracts.
The tiny synthetic fixture proves execution contracts, not comparative scene quality.
FP32 is the supported learned precision; BF16 is not exposed or certified.

Feature and matching recipes already pin DLL bytes in the recognized runtime
directories. Replacing or adding a runtime DLL requires a fresh resolved route and
can invalidate numerical caches, even when the COLMAP executable itself is unchanged.
Existing published artifacts remain immutable. Runtime changes never justify
rewriting an old run or silently reinterpreting its backend identity.
