"""Synthetic native matcher fixture, with no external model or runtime dependency."""

import os
import sqlite3
import struct
from contextlib import closing
from pathlib import Path

from feature_helpers import NativeFixture, fill_database
from test_colmap_capabilities import process_result
from test_features_execution import build as build_features
from test_pairs_execution import build as build_pairs
from test_views_execution import harness, prepare

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_matching import ColmapMatchingAdapter
from splatforge.adapters.matching_database import pair_id
from splatforge.application.matching import MatchingService
from splatforge.core.matching import resolve_matching_settings
from splatforge.core.pairs import ExhaustiveSettings

MATCH_HELP = """-h [ --help ]
--database_path arg
--match_list_path arg
--match_type arg (=pairs) {'pairs', 'raw', 'inliers'}
--FeatureMatching.type arg (=SIFT_BRUTEFORCE)
--FeatureMatching.num_threads arg (=-1)
--FeatureMatching.use_gpu arg (=1)
--FeatureMatching.gpu_index arg (=-1)
--FeatureMatching.guided_matching arg (=0)
--FeatureMatching.skip_geometric_verification arg (=0)
--FeatureMatching.rig_verification arg (=0)
--FeatureMatching.skip_image_pairs_in_same_frame arg (=0)
--FeatureMatching.max_num_matches arg (=32768)
--SiftMatching.max_ratio arg (=0.8)
--SiftMatching.max_distance arg (=0.7)
--SiftMatching.cross_check arg (=1)
--SiftMatching.cpu_brute_force_matcher arg (=0)
--SiftMatching.lightglue_min_score arg (=0.1)
--SiftMatching.lightglue_model_path arg (=sift-lightglue.onnx)
--AlikedMatching.brute_force_min_cossim arg (=0.85)
--AlikedMatching.brute_force_max_ratio arg (=1)
--AlikedMatching.brute_force_cross_check arg (=1)
--AlikedMatching.bruteforce_model_path arg (=bruteforce-matcher.onnx)
--AlikedMatching.lightglue_min_score arg (=0.1)
--AlikedMatching.lightglue_model_path arg (=aliked-lightglue.onnx)
--LomaMatching.min_score arg (=0.1)
--LomaMatching.use_bf16 arg (=0)
--LomaMatching.b_model_path arg (=loma_matcher_B.onnx)
--LomaMatching.b128_model_path arg (=loma_matcher_B128.onnx)
--LomaMatching.r_model_path arg (=loma_matcher_R.onnx)
--LomaMatching.l_model_path arg (=loma_matcher_L.onnx)
--LomaMatching.g_model_path arg (=loma_matcher_G.onnx)
--LomaMatching.brute_force_min_cossim arg (=0.85)
--LomaMatching.brute_force_max_ratio arg (=1)
--LomaMatching.brute_force_cross_check arg (=1)
--LomaMatching.brute_force_model_path arg (=bruteforce-matcher.onnx)
--TwoViewGeometry.min_num_inliers arg (=15)
--default_random_seed arg (=0)
--log_target arg (=stderr_and_file)
"""
VERIFY_HELP = """-h [ --help ]
--database_path arg
--TwoViewGeometry.min_num_inliers arg (=15)
--TwoViewGeometry.multiple_models arg (=0)
--TwoViewGeometry.compute_relative_pose arg (=0)
--TwoViewGeometry.detect_watermark arg (=1)
--TwoViewGeometry.multiple_ignore_watermark arg (=1)
--TwoViewGeometry.watermark_detection_max_error arg (=4)
--TwoViewGeometry.filter_stationary_matches arg (=0)
--TwoViewGeometry.stationary_matches_max_error arg (=4)
--TwoViewGeometry.use_degensac arg (=0)
--TwoViewGeometry.use_sampson_refinement arg (=1)
--TwoViewGeometry.max_error arg (=4)
--TwoViewGeometry.confidence arg (=0.999)
--TwoViewGeometry.max_num_trials arg (=10000)
--TwoViewGeometry.min_inlier_ratio arg (=0)
--TwoViewGeometry.random_seed arg (=-1)
--batch_size arg (=1000)
--num_threads arg (=-1)
--rig_verification arg (=0)
--default_random_seed arg (=0)
--log_target arg (=stderr_and_file)
"""


def extend_schema(path):
    with closing(sqlite3.connect(path)) as db, db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(two_view_geometries)")}
        for name in ("qvec", "tvec"):
            if name not in columns:
                db.execute(f"ALTER TABLE two_view_geometries ADD COLUMN {name} BLOB")


class MatchingFixture(NativeFixture):
    def __init__(self, path):
        super().__init__(path)
        self.top_help += "\nmatches_importer\ngeometric_verifier\n"
        self.match_help, self.verify_help = MATCH_HELP, VERIFY_HELP
        self.match_mode, self.verify_mode = "success", "success"
        self.on_match, self.on_verify = None, None
        for name in (
            "sift-lightglue.onnx",
            "aliked-lightglue.onnx",
            "bruteforce-matcher.onnx",
            *(f"loma_matcher_{v}.onnx" for v in ("B", "B128", "R", "L", "G")),
        ):
            (self.model_root / name).write_bytes(b"synthetic matcher fixture")

    def run(self, request, *, cancellation=None, poll=None):
        argv = request.argv
        if argv in (("matches_importer", "-h"), ("geometric_verifier", "-h")):
            self.requests.append(request)
            return process_result(
                request,
                identity=self.identity,
                stdout=(
                    self.match_help if argv[0] == "matches_importer" else self.verify_help
                ).encode(),
            )
        if argv[0] == "feature_extractor" and len(argv) > 2:
            self.requests.append(request)
            path = fill_database(request, count=24)
            extend_schema(path)
            return process_result(
                request, identity=self.identity, stderr=b"Creating SIFT GPU feature extractor\n"
            )
        if argv[0] == "database_creator":
            result = super().run(request, cancellation=cancellation, poll=poll)
            extend_schema(Path(argv[argv.index("--database_path") + 1]))
            return result
        if argv[0] not in ("matches_importer", "geometric_verifier") or len(argv) == 2:
            return super().run(request, cancellation=cancellation, poll=poll)
        self.requests.append(request)
        numerical = "work" in request.working_directory.parts
        matching = argv[0] == "matches_importer"
        mode = (self.match_mode if matching else self.verify_mode) if numerical else "success"
        callback = self.on_match if matching else self.on_verify
        if numerical and callback:
            callback(getattr(cancellation, "owner", cancellation))
        if mode in ("failed", "cancelled", "timeout", "unresolved", "oom", "forced"):
            return process_result(
                request,
                identity=self.identity,
                exit_code=1,
                stderr=b"CUDA out of memory" if mode == "oom" else b"fixture backend failure",
                timed_out=mode == "timeout",
            ).model_copy(
                update={
                    "cancelled": mode == "cancelled",
                    "teardown_confirmed": mode != "unresolved",
                    "forced_tree_termination": mode == "forced",
                }
            )
        path = Path(argv[argv.index("--database_path") + 1])
        with closing(sqlite3.connect(path)) as db, db:
            if matching:
                assert db.execute("SELECT count(*) FROM matches").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM two_view_geometries").fetchone()[0] == 0
                names = dict(db.execute("SELECT name,image_id FROM images"))
                lines = Path(argv[argv.index("--match_list_path") + 1]).read_text().splitlines()
                for index, line in enumerate(lines):
                    a, b = (names[n] for n in line.split())
                    count = (24, 0, 6)[index % 3] if numerical else 24
                    data = b"".join(struct.pack("<II", i, i) for i in range(count))
                    db.execute(
                        "INSERT INTO matches VALUES (?, ?, 2, ?)", (pair_id(a, b), count, data)
                    )
                first = db.execute(
                    "SELECT pair_id FROM matches ORDER BY pair_id LIMIT 1"
                ).fetchone()[0]
                if mode == "index":
                    db.execute(
                        "UPDATE matches SET data=? WHERE pair_id=?",
                        (struct.pack("<II", 999, 0) * 24, first),
                    )
                elif mode == "duplicate":
                    db.execute("UPDATE matches SET data=? WHERE pair_id=?", (bytes(24 * 8), first))
                elif mode == "shape":
                    db.execute("UPDATE matches SET cols=3 WHERE pair_id=?", (first,))
                elif mode == "unexpected":
                    db.execute("INSERT INTO matches VALUES (?,0,2,X'')", (pair_id(1, 999),))
                elif mode == "missing":
                    db.execute("DELETE FROM matches WHERE pair_id=?", (first,))
                elif mode == "stale_geometry":
                    db.execute(
                        "INSERT INTO two_view_geometries (pair_id,rows,cols,data,config) "
                        "VALUES (?,0,2,X'',1)",
                        (first,),
                    )
            else:
                minimum = int(argv[argv.index("--TwoViewGeometry.min_num_inliers") + 1])
                rows = list(db.execute("SELECT pair_id,rows,data FROM matches WHERE rows>0"))
                for native, n, data in rows:
                    count, config = (n, 6) if n >= minimum else (0, 1)
                    h = struct.pack("<9d", 1, 0, 0, 0, 1, 0, 0, 0, 1) if count else None
                    db.execute(
                        "INSERT INTO two_view_geometries "
                        "(pair_id,rows,cols,data,config,H) VALUES (?,?,2,?,?,?)",
                        (native, count, data if count else b"", config, h),
                    )
                if mode == "matrix":
                    db.execute("UPDATE two_view_geometries SET H=X'00' WHERE config=6")
                elif mode == "config":
                    db.execute("UPDATE two_view_geometries SET config=99")
                elif mode == "mutate_raw":
                    db.execute("UPDATE matches SET rows=0,data=X''")
                elif mode == "unexpected":
                    db.execute(
                        "INSERT INTO two_view_geometries "
                        "(pair_id,rows,cols,data,config) VALUES (?,0,2,X'',1)",
                        (pair_id(1, 999),),
                    )
        if poll:
            poll()
        return process_result(request, identity=self.identity)

    def matching_adapter(self):
        caps = ColmapCapabilityAdapter(runner=self, resolver=self.resolver, environment=os.environ)
        return ColmapMatchingAdapter(runner=self, resolver=self.resolver, capability_adapter=caps)


def inputs(tmp_path, *, variant="SIFT"):
    value, fixture = harness(tmp_path), MatchingFixture(tmp_path)
    views = prepare(value)
    features = build_features(value, views, fixture, variant=variant)
    pairs = build_pairs(value, views, settings=ExhaustiveSettings())
    return value, fixture, features, pairs


def match(value, fixture, features, pairs, *, matcher="SIFT_BRUTEFORCE", progress=None, **kwargs):
    return MatchingService(value.execution, fixture.matching_adapter(), progress=progress).match(
        value.root,
        features_run_id=features.run_id,
        pairs_run_id=pairs.run_id,
        settings=resolve_matching_settings(matcher),
        colmap=fixture.exe,
        model_directory=fixture.model_root,
        **kwargs,
    )


def verify(value, fixture, matches, *, progress=None, **kwargs):
    return MatchingService(value.execution, fixture.matching_adapter(), progress=progress).verify(
        value.root,
        matches_run_id=matches.run_id,
        colmap=fixture.exe,
        **kwargs,
    )
