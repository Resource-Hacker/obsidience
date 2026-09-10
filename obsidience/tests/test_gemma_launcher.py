"""Execute the real launcher with an isolated profile and inert argv recorder."""

import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def launcher(tmp_path):
    if shutil.which("jq") is None:
        pytest.skip("the installed launch dependency jq is unavailable")
    product = tmp_path / "product with spaces"
    script = product / "scripts" / "llm.sh"
    script.parent.mkdir(parents=True)
    runtime = tmp_path / "inert-runtime"
    server = runtime / "bin" / "llama-server"
    server.parent.mkdir(parents=True)
    capture = tmp_path / "captured.json"
    server.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"Path({str(capture)!r}).write_text(json.dumps({{"
        "'argv': sys.argv[1:], 'gpu': os.environ['CUDA_VISIBLE_DEVICES']}))\n"
    )
    server.chmod(0o700)
    source = Path(__file__).resolve().parents[1] / "scripts" / "llm.sh"
    # Replace only the fixed executable installation in this disposable copy;
    # every profile read, validation, shell expansion, and argv is production code.
    lines = source.read_text().splitlines()
    assert sum(line.startswith("LLAMA=") for line in lines) == 1
    script.write_text("\n".join(
        f"LLAMA={shlex.quote(str(runtime))}" if line.startswith("LLAMA=") else line
        for line in lines
    ) + "\n")
    profile = product / "state" / "model-launch" / "obsidience-gemma.json"
    profile.parent.mkdir(parents=True)

    def invoke(parallel):
        config = {
            "gpu_uuids": ["GPU-exact-selected"],
            "context_tokens": 65536,
            "projector_path": "/read-only model/mmproj F16.gguf",
        }
        if parallel is not None:
            config["max_num_seqs"] = parallel
        profile.write_text(json.dumps(config))
        result = subprocess.run(["/bin/sh", str(script)], capture_output=True, text=True)
        return result, json.loads(capture.read_text()) if capture.exists() else None

    return invoke


@pytest.mark.parametrize("parallel", [1, 3, 32])
def test_saved_parallelism_reaches_server_without_changing_context_or_vision(launcher, parallel):
    result, captured = launcher(parallel)
    assert result.returncode == 0, result.stderr
    args = captured["argv"]
    assert args.count("--parallel") == 1
    assert args[args.index("--parallel") + 1] == str(parallel)
    assert args[args.index("-c") + 1] == "65536"
    assert args[args.index("--checkpoint-min-step") + 1] == "0"
    assert "--swa-full" not in args
    assert args[args.index("--mmproj") + 1] == "/read-only model/mmproj F16.gguf"
    assert "--mmproj-offload" in args
    assert captured["gpu"] == "GPU-exact-selected"


@pytest.mark.parametrize("parallel", [None, 0, -1, 33, 1.5, True, "1", []])
def test_invalid_parallelism_never_launches_server(launcher, parallel):
    result, captured = launcher(parallel)
    assert result.returncode == 64
    assert captured is None
