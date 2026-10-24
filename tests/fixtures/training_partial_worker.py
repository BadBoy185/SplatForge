"""Disposable protocol fixture holding partial output in a real owned child tree."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf8"))
workspace = Path(config["result_path"]).parent
events = Path(config["events_path"])
step = config["start_step"]
for sequence, name in enumerate(("worker.started", "dataset.loaded", "training.started"), 1):
    with events.open("ab") as stream:
        stream.write(
            json.dumps(
                {
                    "protocol_version": 1,
                    "sequence": sequence,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": name,
                    "step": step,
                    "total_steps": config["settings"]["max_steps"],
                }
            ).encode()
            + b"\n"
        )
output = Path(config["output_path"])
partial = output / ("scene.ply.partial" if config["scene"] else "checkpoint/state.pt.partial")
partial.parent.mkdir(parents=True)
partial.write_bytes(b"incomplete native output")
child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import sys,time; from pathlib import Path; f=open(sys.argv[1],'rb'); "
        "Path(sys.argv[2]).write_text('ready'); time.sleep(120)",
        str(partial),
        str(workspace / "child.ready"),
    ],
    shell=False,
    cwd=workspace,
    env=dict(os.environ),
)
(workspace / "child.pid").write_text(str(child.pid))
while True:
    time.sleep(0.1)
