"""Synthetic mapping process and sparse binary fixtures, no installed COLMAP."""

import json
import os
import sqlite3
import struct
from contextlib import closing
from pathlib import Path

from matching_helpers import MatchingFixture, match, verify
from test_colmap_capabilities import process_result
from test_features_execution import build as build_features
from test_pairs_execution import build as build_pairs
from test_views_execution import harness, prepare

from splatforge.adapters.colmap_capabilities import ColmapCapabilityAdapter
from splatforge.adapters.colmap_mapping import ColmapMappingAdapter
from splatforge.adapters.feature_database import FeatureImageMapping, NativeFeaturePayload
from splatforge.application.mapping import MappingService
from splatforge.core.pairs import ExhaustiveSettings
from splatforge.core.reconstruction import (
    GlobalMapperSettings,
    HierarchicalClusterSettings,
    HierarchicalMapperSettings,
    IncrementalMapperSettings,
    ViewGraphCalibrationSettings,
)


def mapping_help():
    names = {"database_path", "image_path", "output_path", "default_random_seed", "log_target",
             "log_path", "log_level", "GlobalMapper.gp_gpu_index", "GlobalMapper.ba_gpu_index"}
    names |= {
        "GlobalMapper." + k
        for k in GlobalMapperSettings.model_fields
        if k not in {"method_id", "settings_version"}
    }
    return "-h [ --help ]\n" + "".join("--" + n + " arg\n" for n in sorted(names))


def calibration_help():
    names = {"database_path", "default_random_seed", "log_target"}
    names |= set(ViewGraphCalibrationSettings.model_fields) - {"settings_version", "random_seed"}
    return "-h [ --help ]\n" + "".join("--" + n + " arg\n" for n in sorted(names))


def incremental_help():
    names = {"database_path", "image_path", "output_path", "default_random_seed", "log_target",
             "log_level"}
    names |= {"Mapper." + k for k in IncrementalMapperSettings.model_fields
              if k not in {"method_id", "settings_version"}}
    return "-h [ --help ]\n" + "".join("--" + n + " arg\n" for n in sorted(names))


def hierarchical_help():
    names = {"database_path", "image_path", "output_path", "default_random_seed", "log_target",
             "log_path"}
    names |= {"HierarchicalMapper." + k for k in HierarchicalMapperSettings.model_fields
              if k not in {"method_id", "settings_version", "cluster"}}
    names |= {"Mapper." + k for k in HierarchicalClusterSettings.model_fields
              if k not in {"method_id", "settings_version", "num_threads", "init_num_trials"}}
    return "-h [ --help ]\n" + "".join("--" + n + " arg\n" for n in sorted(names))


def bundle_adjustment_help(*, compiled=False):
    names = {"input_path", "output_path", "BundleAdjustment.backend",
             "BundleAdjustmentCeres.use_gpu"}
    if compiled:
        names |= {"BundleAdjustmentCaspar.gpu_index", "BundleAdjustmentCaspar.solver_iter_max"}
    return "-h [ --help ]\n" + "".join("--" + n + " arg\n" for n in sorted(names))


def mapping_for(views, *, offset=0):
    return NativeFeaturePayload(
        user_version=0,
        application_id=0,
        tables=(),
        images=tuple(
            FeatureImageMapping(view_id=v, image_id=offset + 1 + index * 7, image_name=f"{v}.png")
            for index, v in enumerate(views)
        ),
    )


def write_model(
    directory,
    mapping,
    *,
    shift=0.0,
    focal=100.0,
    shared=True,
    native_camera_offset=0,
    selected=None,
    current_frames=True,
    with_point=False,
):
    directory.mkdir(parents=True)
    selected = selected or mapping.images
    camera_ids = {
        i.image_id: native_camera_offset + (11 if shared else 11 + index * 13)
        for index, i in enumerate(selected)
    }
    cameras = sorted(set(camera_ids.values()))
    with (directory / "cameras.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", len(cameras)))
        for native in cameras:
            stream.write(struct.pack("<IiQQ3d", native, 0, 32, 24, focal, 16.0, 12.0))
    with (directory / "images.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", len(selected)))
        for index, image in enumerate(selected):
            stream.write(
                struct.pack(
                    "<I7dI",
                    image.image_id,
                    1,
                    0,
                    0,
                    0,
                    shift + index,
                    0,
                    0,
                    camera_ids[image.image_id],
                )
            )
            stream.write(image.image_name.encode() + b"\0")
            stream.write(struct.pack("<Q", int(with_point)))
            if with_point:
                stream.write(struct.pack("<ddQ", 16.0, 12.0, 999))
    with (directory / "points3D.bin").open("wb") as stream:
        stream.write(struct.pack("<Q", int(with_point)))
        if with_point:
            stream.write(struct.pack("<Q3d3BdQ", 999, 1, 2, 3, 50, 60, 70, 0.1, len(selected)))
            for image in selected:
                stream.write(struct.pack("<II", image.image_id, 0))
    if current_frames:
        with (directory / "rigs.bin").open("wb") as stream:
            stream.write(struct.pack("<Q", len(cameras)))
            for native in cameras:
                stream.write(struct.pack("<IIiI", native + 100, 1, 0, native))
        with (directory / "frames.bin").open("wb") as stream:
            stream.write(struct.pack("<Q", len(selected)))
            for index, image in enumerate(selected):
                stream.write(
                    struct.pack(
                        "<II7dIiIQ",
                        200 + index * 5,
                        camera_ids[image.image_id] + 100,
                        1,
                        0,
                        0,
                        0,
                        shift + index,
                        0,
                        0,
                        1,
                        0,
                        camera_ids[image.image_id],
                        image.image_id,
                    )
                )


class MappingFixture(MatchingFixture):
    def __init__(self, root):
        super().__init__(root)
        self.top_help += "\nview_graph_calibrator\nbundle_adjuster\n"
        if "global_mapper" not in self.top_help:
            self.top_help += "global_mapper\n"
        self.map_help, self.cal_help = mapping_help(), calibration_help()
        self.incremental_help = incremental_help()
        self.hier_help = hierarchical_help()
        self.gpu_log = ""
        self.caspar_compiled = False
        self.caspar_evidence = True
        self.mapping_mode = "success"
        self.calibration_mode = "success"
        self.on_map = None
        self.on_calibration = None
        self.private_databases = []

    def mapping_adapter(self):
        return ColmapMappingAdapter(
            runner=self,
            resolver=self.resolver,
            capability_adapter=ColmapCapabilityAdapter(
                runner=self, resolver=self.resolver, environment=os.environ
            ),
        )

    def run(self, request, *, cancellation=None, poll=None):
        argv = request.argv
        if argv == ("mapper", "-h") or argv == ("bundle_adjuster", "-h"):
            self.requests.append(request)
            return process_result(request, identity=self.identity, stdout=(
                self.incremental_help if argv[0] == "mapper" else
                bundle_adjustment_help(compiled=self.caspar_compiled)).encode())
        if argv[0] not in {"global_mapper", "mapper", "view_graph_calibrator",
                           "hierarchical_mapper"}:
            return super().run(request, cancellation=cancellation, poll=poll)
        self.requests.append(request)
        if argv[-1] == "-h":
            return process_result(
                request,
                identity=self.identity,
                stdout=(self.map_help if argv[0] == "global_mapper" else
                        self.hier_help if argv[0] == "hierarchical_mapper" else
                        self.cal_help).encode(),
            )
        calibration = argv[0] == "view_graph_calibrator"
        mode = self.calibration_mode if calibration else self.mapping_mode
        database = Path(argv[argv.index("--database_path") + 1])
        assert "work" in database.parts and "artifacts" not in database.parts
        assert database.stat().st_nlink == 1
        self.private_databases.append(database)
        owner = cancellation
        while hasattr(owner, "owner"):
            owner = owner.owner
        callback = self.on_calibration if calibration else self.on_map
        if callback:
            callback(owner)
        if mode in {"failed", "cancelled", "timeout", "unresolved"}:
            return process_result(
                request, identity=self.identity, exit_code=1, timed_out=mode == "timeout"
            ).model_copy(
                update={
                    "cancelled": mode == "cancelled",
                    "teardown_confirmed": mode != "unresolved",
                }
            )
        with closing(sqlite3.connect(database)) as db, db:
            assert db.execute("SELECT count(*) FROM matches").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM descriptors").fetchone()[0] == 0
            rows = db.execute("SELECT image_id,name FROM images ORDER BY name").fetchall()
            if calibration:
                # A finite estimator update, deliberately not calibration truth.
                for camera, params in db.execute("SELECT camera_id,params FROM cameras").fetchall():
                    values = list(struct.unpack(f"<{len(params) // 8}d", params))
                    values[0] = float("nan") if mode == "malformed" else values[0] * 1.1
                    db.execute(
                        "UPDATE cameras SET params=? WHERE camera_id=?",
                        (struct.pack(f"<{len(values)}d", *values), camera),
                    )
                if mode == "unexpected_edge":
                    from splatforge.adapters.matching_database import pair_id

                    native = pair_id(rows[0][0], rows[2][0])
                    db.execute(
                        "INSERT INTO two_view_geometries (pair_id,rows,cols,data,config,H) "
                        "VALUES (?,1,2,?,6,?)",
                        (
                            native,
                            struct.pack("<II", 0, 0),
                            struct.pack("<9d", 1, 0, 0, 0, 1, 0, 0, 0, 1),
                        ),
                    )
            elif mode != "empty":
                mapping = NativeFeaturePayload(
                    user_version=0,
                    application_id=0,
                    tables=(),
                    images=tuple(
                        FeatureImageMapping(view_id=Path(name).stem, image_id=i, image_name=name)
                        for i, name in rows
                    ),
                )
                output = Path(argv[argv.index("--output_path") + 1])
                if mode != "multi":
                    selected = mapping.images[:3] if mode == "partial" else mapping.images
                    model_rows = rows[:3] if mode == "partial" else rows
                    write_model(output / "7", mapping, shared=False, selected=selected)
                    # Match the fixture's explicit camera dimensions/model.
                    with (output / "7" / "cameras.bin").open("wb") as stream:
                        stream.write(struct.pack("<Q", len(model_rows)))
                        for index, (image, _name) in enumerate(model_rows):
                            model, w, h, params = db.execute(
                                "SELECT c.model,c.width,c.height,c.params "
                                "FROM cameras c JOIN images i ON i.camera_id=c.camera_id "
                                "WHERE i.image_id=?",
                                (image,),
                            ).fetchone()
                            stream.write(
                                struct.pack("<IiQQ", 11 + index * 13, model, w, h) + params
                            )
                if mode == "multi":
                    # Keep the first supported component's exact camera payload, and
                    # emit a second independent component plus one unregistered view.
                    for name, selected in (("23", mapping.images[:3]), ("1", mapping.images[3:6])):
                        write_model(output / name, mapping, selected=selected, shared=False)
                        with (output / name / "cameras.bin").open("wb") as stream:
                            stream.write(struct.pack("<Q", len(selected)))
                            for index, image in enumerate(selected):
                                model, w, h, params = db.execute(
                                    "SELECT c.model,c.width,c.height,c.params "
                                    "FROM cameras c JOIN images i ON i.camera_id=c.camera_id "
                                    "WHERE i.image_id=?",
                                    (image.image_id,),
                                ).fetchone()
                                stream.write(
                                    struct.pack("<IiQQ", 11 + index * 13, model, w, h) + params
                                )
                if mode == "prior_snapshot":
                    prior_file = output.parent / "input_cameras.json"
                    prior_value = json.loads(prior_file.read_text(encoding="utf-8"))
                    prior_value["cameras"][0]["parameters"][0] += 1
                    prior_file.write_text(json.dumps(prior_value), encoding="utf-8")
                if mode == "malformed":
                    (output / "7" / "images.bin").write_bytes(b"bad")
                if mode == "overlap":
                    import shutil

                    shutil.copytree(output / "7", output / "8")
        if "--log_path" in argv:
            log = Path(argv[argv.index("--log_path") + 1]) / "colmap.log.INFO.fixture"
            log.write_text(
                "Partitioning scene\n  Cluster 0 with 3 images\n  Cluster 1 with 3 images\n"
                "Reconstructing clusters\nMerging clusters\n"
                if argv[0] == "hierarchical_mapper" else self.gpu_log, encoding="utf8")
        if poll:
            poll()
        text = (b"Creating Caspar bundle adjuster\n"
                b"Caspar: CONVERGED_SCORE_THRESHOLD after 2 iters\n"
                if "--Mapper.ba_global_backend" in argv and
                argv[argv.index("--Mapper.ba_global_backend") + 1] == "CASPAR" and
                self.caspar_evidence else b"")
        return process_result(request, identity=self.identity, stderr=text)


def mapping_inputs(tmp_path, *, multi=False, camera_model=None):
    value, fixture = harness(tmp_path), MappingFixture(tmp_path)
    if multi:
        value.materializer.mode = "too_many"
    views = prepare(value, target="5", candidate_fps="5") if multi else prepare(value)
    features = build_features(value, views, fixture)
    pairs = build_pairs(value, views, settings=ExhaustiveSettings())
    raw = match(value, fixture, features, pairs)
    kwargs = {}
    if camera_model:
        from splatforge.core.geometry import CameraPriorSet, ViewCameraPrior

        feature_set = value.execution.load_local_features(value.root, features.feature_artifact)
        kwargs["cameras"] = CameraPriorSet(cameras=tuple(
            ViewCameraPrior(view_id=v.view_id, model=camera_model, width=v.width, height=v.height,
                            parameters=(100, 100, v.width / 2, v.height / 2)
                            if camera_model == "PINHOLE" else
                            (100, v.width / 2, v.height / 2) if camera_model == "SIMPLE_PINHOLE"
                            else (100, v.width / 2, v.height / 2, 0),
                            prior_focal_length=True)
            for v in feature_set.views
        ))
    verified = verify(value, fixture, raw, **kwargs)
    return value, fixture, features, raw, verified


def map_run(value, fixture, verified, *, repository=None, progress=None, **kwargs):
    return MappingService(
        repository or value.execution, fixture.mapping_adapter(), progress=progress
    ).run(value.root, verification_run_id=verified.run_id, colmap=fixture.exe, **kwargs)
