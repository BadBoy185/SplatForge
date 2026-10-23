"""Normalize single-model Incremental provenance to the existing sparse layout."""

from pathlib import Path


def normalize_incremental_output(output: Path) -> None:
    sparse = output / "sparse"
    if not sparse.is_dir() or sparse.is_symlink() or sparse.is_junction():
        raise ValueError("mapping.zero_components: no Incremental sparse output")
    models = [p for p in sparse.iterdir() if p.name != "project.ini"]
    if len(models) > 1:
        raise ValueError(
            "mapping.unexpected_multiple_models: Incremental single-model policy violated; "
            "overlapping native hypotheses cannot be disjoint ReconstructionSet components"
        )
    if not models:
        raise ValueError("mapping.zero_components: Incremental initialization returned no model")
    model = models[0]
    if (
        not model.is_dir()
        or model.is_symlink()
        or model.is_junction()
        or not model.name.isascii()
        or not model.name.isdecimal()
    ):
        raise ValueError("mapping.malformed_output: invalid Incremental model directory")
    source = model / "project.ini"
    if source.exists() or source.is_symlink() or source.is_junction():
        if (
            not source.is_file()
            or source.is_symlink()
            or source.is_junction()
            or source.stat().st_nlink != 1
            or source.stat().st_size > 1024**2
        ):
            raise ValueError("mapping.malformed_output: unsafe Incremental native provenance")
        destination = sparse / "project.ini"
        if destination.exists() or destination.is_symlink() or destination.is_junction():
            raise ValueError("mapping.malformed_output: duplicate native provenance")
        # Only attempt-owned generated output moves. Preserve exact provenance bytes.
        source.rename(destination)
