"""Terminal summaries and JSON reports. All numbers are computed from actual results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .errors import ReportError
from .models import CaseResult, Outcome, RunReport

SCHEMA_VERSION = 1
_OUTPUT_CLIP = 2000


def compute_summary(results: list[CaseResult], configurations: int, wall_seconds: float) -> dict[str, Any]:
    count = {o: sum(1 for r in results if r.outcome is o) for o in Outcome}
    return {
        "total": len(results),
        "passed": count[Outcome.PASS],
        "mismatches": count[Outcome.MISMATCH],
        "compile_errors": count[Outcome.COMPILE_ERROR],
        "timeouts": count[Outcome.TIMEOUT],
        "crashes": count[Outcome.CRASH],
        "skipped": count[Outcome.SKIPPED],
        "unexpected_vs_expected_outcome": sum(
            1 for r in results if r.expected_outcome is not None and r.expected_outcome != r.outcome.value
        ),
        "configurations": configurations,
        "wall_seconds": round(wall_seconds, 3),
    }


def _clip(text: str) -> str:
    return text if len(text) <= _OUTPUT_CLIP else text[:_OUTPUT_CLIP] + f"... [{len(text) - _OUTPUT_CLIP} more chars]"


def _result_dict(r: CaseResult) -> dict[str, Any]:
    configs = []
    for run in r.runs:
        entry: dict[str, Any] = {
            "name": run.name,
            "flags": run.flags,
            "compile": {
                "ok": run.compile.ok, "exit_code": run.compile.exit_code,
                "timed_out": run.compile.timed_out, "seconds": round(run.compile.duration, 6),
                "stderr": _clip(run.compile.stderr),
            },
        }
        if run.run is not None:
            entry["run"] = {
                "exit_code": run.run.exit_code, "signal": run.run.signal, "crashed": run.run.crashed,
                "timed_out": run.run.timed_out, "seconds": round(run.run.duration, 6),
                "stdout": _clip(run.run.stdout), "stderr": _clip(run.run.stderr),
                "output_truncated": run.run.truncated,
            }
        configs.append(entry)
    return {
        "test_id": r.case.test_id,
        "outcome": r.outcome.value,
        "reason": r.reason,
        "language": r.case.language.value,
        "category": r.case.category.value,
        "safety": r.case.safety.value,
        "seed": r.case.seed,
        "expected_outcome": r.expected_outcome,
        "differences": [d.__dict__ for d in r.differences],
        "notes": r.notes,
        "configs": configs,
        "duration_seconds": round(r.duration, 6),
        "minimized": r.minimized_source is not None,
        "reduction": r.reduction,
        "artifact_dir": r.artifact_dir,
    }


def report_to_dict(report: RunReport) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "compilercheck", "version": __version__},
        "run": {
            "suite": report.suite,
            "seed": report.seed,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "optimizations": report.optimizations,
            "compiler": report.compiler_info,
            "comparison_policy": report.policy,
        },
        "summary": compute_summary(report.results, len(report.optimizations), report.wall_seconds),
        "results": [_result_dict(r) for r in report.results],
    }


def _headline(detail: str) -> str:
    """First informative line of a difference (skips unified-diff hunk headers)."""
    lines = [ln for ln in detail.splitlines() if ln and not ln.startswith("@@")]
    return lines[0] if lines else ""


def format_summary(data: dict[str, Any], verbose: bool = False) -> str:
    s, run = data["summary"], data["run"]
    version = run.get("compiler", {}).get("version", "unknown")
    lines = [
        f"CompilerCheck summary (suite: {run['suite']})",
        f"Compiler                : {version}",
        f"Configurations tested   : {s['configurations']} ({', '.join(run['optimizations'])})",
        "-" * 60,
        f"Total tests             : {s['total']}",
        f"Successful (PASS)       : {s['passed']}",
        f"Behavioral mismatches   : {s['mismatches']}",
        f"Compilation failures    : {s['compile_errors']}",
        f"Timeouts                : {s['timeouts']}",
        f"Crashes                 : {s['crashes']}",
        f"Skipped                 : {s['skipped']}",
    ]
    if s.get("unexpected_vs_expected_outcome"):
        lines.append(f"Differ from expectation : {s['unexpected_vs_expected_outcome']}")
    lines.append(f"Total execution time    : {s['wall_seconds']:.2f} s")
    problems = [r for r in data["results"] if r["outcome"] not in ("PASS", "SKIPPED")]
    if problems:
        lines += ["", "Findings:"]
        for r in problems:
            lines.append(f"  [{r['outcome']}] {r['test_id']}: {r['reason']}")
            if r.get("expected_outcome") and r["expected_outcome"] != r["outcome"]:
                lines.append(f"      expected outcome was {r['expected_outcome']}")
            for d in r["differences"][: (None if verbose else 2)]:
                first = _headline(d["detail"])
                lines.append(f"      {d['kind']} ({d['config_a']} vs {d['config_b']}): {first}")
            for n in r["notes"]:
                lines.append(f"      note: {n}")
            if r.get("artifact_dir"):
                lines.append(f"      artifact: {r['artifact_dir']}")
    skipped = [r for r in data["results"] if r["outcome"] == "SKIPPED"]
    if skipped:
        lines += ["", "Skipped:"] + [f"  {r['test_id']}: {r['reason']}" for r in skipped]
    return "\n".join(lines)


def write_report(report: RunReport, reports_dir: Path) -> Path:
    """Write a timestamped report and refresh ``latest.json`` (a copy, so it works on Windows)."""
    data = report_to_dict(report)
    stamp = report.started_at.replace("-", "").replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")
    try:
        Path(reports_dir).mkdir(parents=True, exist_ok=True)
        path = Path(reports_dir) / f"report-{stamp}.json"
        counter = 1
        while path.exists():
            counter += 1
            path = Path(reports_dir) / f"report-{stamp}-{counter}.json"
        text = json.dumps(data, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        (Path(reports_dir) / "latest.json").write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"cannot write report in {reports_dir}: {exc}") from exc
    return path


def load_report(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "summary" not in data or "results" not in data:
            raise ReportError(f"{path} is not a CompilerCheck report")
        return data
    except OSError as exc:
        raise ReportError(f"cannot read report {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"report {path} is not valid JSON: {exc}") from exc


def latest_report_path(reports_dir: Path) -> Path:
    path = Path(reports_dir) / "latest.json"
    if not path.is_file():
        raise ReportError(f"no report found at {path}; run a suite first")
    return path

