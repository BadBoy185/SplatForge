"""Tiny native database/process fixtures; no learned runtime or weights."""

import os
import sqlite3
import struct
from contextlib import closing
from pathlib import Path

from PIL import Image
from test_colmap_capabilities import TOP_HELP, create_schema, process_result

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_features import ColmapFeatureAdapter
from splatforge.adapters.process_runner import ExecutableResolver
from splatforge.core.features import descriptor_signature, resolve_extraction_settings

COMMON_OPTIONS = (
    "database_path",
    "image_path",
    "FeatureExtraction.use_gpu",
    "FeatureExtraction.gpu_index",
    "FeatureExtraction.num_threads",
    "FeatureExtraction.max_image_size",
    "SiftExtraction.max_num_features",
    "AlikedExtraction.max_num_features",
    "AlikedExtraction.min_score",
    "LomaExtraction.max_num_features",
    "LomaExtraction.min_score",
    "LomaExtraction.use_bf16",
    "LomaExtraction.use_fast_resize",
)
MODELS = {
    "AlikedExtraction.n16rot_model_path": "aliked-n16rot.onnx",
    "AlikedExtraction.n32_model_path": "aliked-n32.onnx",
    "LomaExtraction.detector_model_path": "loma-detector.onnx",
    "LomaExtraction.descriptor_model_path": "loma-b.onnx",
    "LomaExtraction.descriptor_b128_model_path": "loma-b128.onnx",
}
FEATURE_HELP = (
    "-h [ --help ]\n--FeatureExtraction.type arg (=SIFT) "
    + ("{SIFT, ALIKED_N16ROT, ALIKED_N32, LOMA_B, LOMA_B128}\n")
    + "".join(f"--{name} arg\n" for name in COMMON_OPTIONS)
    + "".join(f"--{name} arg (={default})\n" for name, default in MODELS.items())
)


def fill_database(request, *, typed=True, count=3):
    argv = request.argv
    database = Path(argv[argv.index("--database_path") + 1])
    if not database.is_absolute():
        database = request.working_directory / database
    if not database.exists():
        create_schema(database)
        if typed:
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("ALTER TABLE descriptors ADD COLUMN type INTEGER NOT NULL DEFAULT 0")
    images = Path(argv[argv.index("--image_path") + 1])
    if not images.is_absolute():
        images = request.working_directory / images
    variant = (
        argv[argv.index("--FeatureExtraction.type") + 1]
        if "--FeatureExtraction.type" in argv
        else "SIFT"
    )
    settings = resolve_extraction_settings(variant)
    signature = descriptor_signature(settings)
    kind = {"SIFT": 0, "ALIKED_N16ROT": 1, "ALIKED_N32": 2, "LOMA_B": 3, "LOMA_B128": 4}[variant]
    with closing(sqlite3.connect(database)) as db, db:
        for index, path in enumerate(sorted(images.iterdir()), 1):
            with Image.open(path) as image:
                width, height = image.size
            db.execute("INSERT INTO cameras VALUES (?,0,?,?,X'',0)", (index, width, height))
            db.execute("INSERT INTO images VALUES (?,?,?)", (index, path.name, index))
            db.execute(
                "INSERT INTO keypoints VALUES (?,?,2,?)",
                (index, count, struct.pack("<ff", 1.0, 1.0) * count),
            )
            db.execute(
                "INSERT INTO descriptors (image_id, rows, cols, data) VALUES (?,?,?,?)",
                (index, count, signature.row_bytes, bytes(count * signature.row_bytes)),
            )
            if typed:
                db.execute("UPDATE descriptors SET type=? WHERE image_id=?", (kind, index))
    return database


class NativeFixture:
    def __init__(self, tmp_path):
        self.exe = tmp_path / "COLMAP native ž.exe"
        self.exe.write_bytes(b"fake native fixture")
        self.model_root = tmp_path / "local models ž"
        self.model_root.mkdir()
        for name in MODELS.values():
            (self.model_root / name).write_bytes(b"synthetic fixture model")
        self.resolver = ExecutableResolver()
        self.identity = self.resolver.resolve(str(self.exe))
        self.requests = []
        self.mode = "success"
        self.on_extract = None
        self.top_help = TOP_HELP.replace("COLMAP 3.13.0", "COLMAP 4.2.1")
        self.top_help = self.top_help.replace("COLMAP 4.0.0", "COLMAP 4.2.1")
        self.top_help = (
            "COLMAP 4.2.1 (Commit fixture) with CUDA\nONNX_ENABLED=ON\nCUDA_ENABLED=ON\n"
            + self.top_help
        )
        self.feature_help = FEATURE_HELP

    def run(self, request, *, cancellation=None, poll=None):
        self.requests.append(request)
        argv = request.argv
        result = {}
        if argv == ("help",):
            result["stdout"] = self.top_help.encode()
        elif argv == ("feature_extractor", "-h"):
            result["stdout"] = self.feature_help.encode()
        elif len(argv) == 2 and argv[1] == "-h":
            result["stdout"] = (
                b"-h [ --help ]\n--FeatureMatching.type arg (=SIFT_BRUTEFORCE) {SIFT_BRUTEFORCE}\n"
            )
        elif argv[0] == "database_creator":
            database = Path(argv[argv.index("--database_path") + 1])
            create_schema(database)
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("ALTER TABLE descriptors ADD COLUMN type INTEGER NOT NULL DEFAULT 0")
        elif argv[0] == "feature_extractor":
            numerical = "work" in request.working_directory.parts
            if numerical and self.on_extract:
                self.on_extract(cancellation)
            mode = self.mode if numerical else "success"
            if mode in {"cancelled", "timeout", "failed", "oom", "unresolved", "forced"}:
                result.update(
                    {
                        "cancelled": mode == "cancelled",
                        "timed_out": mode == "timeout",
                        "exit_code": 1,
                        "teardown_confirmed": mode != "unresolved",
                        "forced_tree_termination": mode == "forced",
                        "stderr": b"CUDA out of memory" if mode == "oom" else b"fixture failure",
                    }
                )
            else:
                database = fill_database(request)
                with closing(sqlite3.connect(database)) as db, db:
                    if mode == "extra":
                        db.execute("INSERT INTO images VALUES (999,'unexpected.png',1)")
                    elif mode == "missing":
                        db.execute("DELETE FROM descriptors WHERE image_id=1")
                    elif mode == "dimension":
                        db.execute("UPDATE descriptors SET cols=127 WHERE image_id=1")
                    elif mode == "family":
                        db.execute("UPDATE descriptors SET type=99 WHERE image_id=1")
                    elif mode == "counts":
                        db.execute("UPDATE descriptors SET rows=2 WHERE image_id=1")
                result["stderr"] = b"Creating SIFT GPU feature extractor\n"
                if mode == "truncated":
                    result.update(stdout_truncated=True, stdout=b"x" * request.max_stdout_bytes)
        else:
            raise AssertionError(argv)
        extra = {
            key: result.pop(key)
            for key in ("cancelled", "teardown_confirmed", "forced_tree_termination")
            if key in result
        }
        return process_result(request, identity=self.identity, **result).model_copy(update=extra)

    def adapter(self):
        caps = ColmapCapabilityAdapter(runner=self, resolver=self.resolver, environment=os.environ)
        return ColmapFeatureAdapter(runner=self, resolver=self.resolver, capability_adapter=caps)
