"""Persist failure artifacts and reload them for replay."""

from __future__ import annotations

import json
import platform
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .errors import ArtifactError
from .models import CaseResult, ProgramCase, safe_name

SCHEMA_VERSION = 1


def artifact_dir_name(result: CaseResult) -> str:
    return f"{safe_name(result.case.test_id)}__{result.outcome.value.lower()}"


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def _reproduce_text(result: CaseResult, directory: Path, ext: str, info: dict[str, Any]) -> str:
    lines = [
        f"# Reproducing {result.case.test_id} ({result.outcome.value})",
        "",
        "## Automatic replay",
        "",
        "```",
        f"python -m compilercheck rerun {shlex.quote(str(directory))}",
        f"python -m compilercheck rerun {shlex.quote(str(directory))} --minimized   # if minimized{ext} exists",
        "```",
        "",
        "## Manual replay (POSIX shell syntax; adapt quoting on Windows)",
        "",
        "```",
    ]
    for run in result.runs:
        argv = [info.get("executable", "clang") if result.case.language.value == "c"
                else (info.get("cxx_executable") or "clang++")]
        std_flags = [f for f in run.flags if f.startswith("-std=")]
        others = [f for f in run.flags if not f.startswith("-std=")]
        argv += std_flags + others + [f"source{ext}", "-o", f"prog_{run.name}"]
        if sys.platform != "win32" and "-lm" not in argv:
            argv.append("-lm")
        lines.append(shlex.join(argv))
        lines.append(f"./prog_{run.name}")
    lines += ["```", "", "Compare stdout, stderr and exit status of the runs. A difference is a lead, not proof of a",
              "compiler bug: check for undefined behavior (`python -m compilercheck sanitize --source ...`) first.", ""]
    return "\n".join(lines)


def save_artifact(root: Path, result: CaseResult, config: Config, info: dict[str, Any]) -> Path:
    directory = Path(root) / artifact_dir_name(result)
    if directory.exists():
        if not (directory / "metadata.json").is_file():
            raise ArtifactError(f"refusing to overwrite non-artifact directory {directory}")
        shutil.rmtree(directory)
    try:
        directory.mkdir(parents=True)
        ext = result.case.language.extension
        _write(directory / f"source{ext}", result.case.source)
        if result.minimized_source is not None:
            _write(directory / f"minimized{ext}", result.minimized_source)
        configs = []
        for run in result.runs:
            _write(directory / f"{run.name}.compile.txt",
                   f"$ {shlex.join(run.compile.command)}\nexit: {run.compile.exit_code}\n"
                   f"--- stdout ---\n{run.compile.stdout}\n--- stderr ---\n{run.compile.stderr}\n")
            entry: dict[str, Any] = {
                "name": run.name,
                "flags": run.flags,
                "compile_exit_code": run.compile.exit_code,
                "compile_timed_out": run.compile.timed_out,
                "compile_seconds": round(run.compile.duration, 6),
            }
            if run.run is not None:
                _write(directory / f"{run.name}.stdout.txt", run.run.stdout)
                _write(directory / f"{run.name}.stderr.txt", run.run.stderr)
                entry.update(
                    exit_code=run.run.exit_code, signal=run.run.signal, crashed=run.run.crashed,
                    timed_out=run.run.timed_out, run_seconds=round(run.run.duration, 6),
                    output_truncated=run.run.truncated,
                )
            configs.append(entry)
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "tool_version": __version__,
            "test": result.case.to_dict(include_source=False),
            "outcome": result.outcome.value,
            "reason": result.reason,
            "notes": result.notes,
            "differences": [d.__dict__ for d in result.differences],
            "compiler": info,
            "configs": configs,
            "replay_config": config.to_replay_dict(),
            "minimized": result.minimized_source is not None,
            "reduction": result.reduction,
            "platform": platform.platform(),
            "python": sys.version,
        }
        _write(directory / "metadata.json", json.dumps(metadata, indent=2) + "\n")
        _write(directory / "REPRODUCE.md", _reproduce_text(result, directory, ext, info))
    except OSError as exc:
        raise ArtifactError(f"cannot write artifact {directory}: {exc}") from exc
    return directory


def load_artifact(directory: Path, use_minimized: bool = False) -> tuple[ProgramCase, dict[str, Any]]:
    """Return (test case, replay-config mapping) from a saved artifact directory."""
    directory = Path(directory)
    meta_path = directory / "metadata.json"
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        test = metadata["test"]
        ext = ".c" if test["language"] == "c" else ".cpp"
        name = ("minimized" if use_minimized else "source") + ext
        source = (directory / name).read_bytes().decode("utf-8")
        return ProgramCase.from_dict(test, source=source), dict(metadata["replay_config"])
    except (OSError, KeyError, ValueError) as exc:
        raise ArtifactError(f"cannot load artifact {directory}: {exc}") from exc
