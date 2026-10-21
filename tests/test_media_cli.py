import importlib
import json
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from splatforge.application.media import (
    MediaAddResult,
    MediaRelinkResult,
    MediaSourceSummary,
)
from splatforge.cli.app import app
from splatforge.core.media import MediaType

runner = CliRunner()


def test_media_cli_add_list_verify_and_relink_are_thin_json_commands(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    source_id = uuid4()
    inventory_id = uuid4()
    summary = MediaSourceSummary(
        source_id=source_id,
        source_revision=1,
        filename="photo.png",
        media_type=MediaType.PHOTO,
        byte_size=3,
        content_sha256="a" * 64,
        width=1,
        height=1,
    )

    class FakeService:
        def add(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return MediaAddResult(
                project_revision=1,
                inventory_id=inventory_id,
                inventory_reference=f"sources/{inventory_id}.jsonl",
                inventory_revision=1,
                added_sources=(summary,),
            )

        def list(self, _path):  # type: ignore[no-untyped-def]
            return None

        def verify(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return ()

        def relink(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return MediaRelinkResult(
                project_revision=2,
                inventory_id=uuid4(),
                inventory_reference="sources/relinked.jsonl",
                inventory_revision=2,
                source=summary,
            )

    cli_module = importlib.import_module("splatforge.cli.app")
    monkeypatch.setattr(cli_module, "build_media_service", lambda **_kwargs: FakeService())
    project = tmp_path / "project"
    source = tmp_path / "photo.png"

    added = runner.invoke(
        app,
        ["media", "add", str(project), str(source), "--ffprobe", str(tmp_path / "ffprobe.exe")],
    )
    listed = runner.invoke(app, ["media", "list", str(project)])
    verified = runner.invoke(app, ["media", "verify", str(project), "--policy", "strict"])
    relinked = runner.invoke(
        app,
        ["media", "relink", str(project), str(source_id), str(tmp_path / "new.png")],
    )

    assert added.exit_code == 0 and json.loads(added.output)["project_revision"] == 1
    assert listed.exit_code == 0 and json.loads(listed.output) == {"inventory": None}
    assert verified.exit_code == 0 and json.loads(verified.output) == {"results": []}
    assert relinked.exit_code == 0 and json.loads(relinked.output)["inventory_revision"] == 2
