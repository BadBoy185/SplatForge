# Architecture

SplatForge is a pipeline orchestrator, not a monolithic reconstruction algorithm.

```text
Sources
  -> Ingest
  -> Frame Selection
  -> Masking (optional)
  -> Feature Extraction
  -> Pair Selection
  -> Feature Matching
  -> Mapping / SfM
  -> Reconstruction Validation
  -> 3DGS Training
  -> Export / Viewer
```

Each processing box is a replaceable stage with registered methods. UI stores stable method IDs and never directly invokes FFmpeg, COLMAP or trainers.

The first high-quality flat-camera profile is:

```text
Sharpest-frame selection
-> ALIKED
-> Sequential pair selection
-> LightGlue
-> COLMAP Global Mapper
-> validation
-> trainer/export adapter
```

Pair selection and feature matching are deliberately separate concepts. Future implementations can use sequential pairing inside a video and retrieval across multiple clips without changing the matcher.

Each stage will eventually persist its implementation version, config fingerprint, input fingerprints, output manifest, status, metrics and log references. Cache invalidation flows downstream only.

Phase 1 supports ordinary video/photos. 360/fisheye is a later preprocessing/input-adapter layer and must reuse the same SfM/training core.
