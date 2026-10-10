"""Comparison policy and outcome classification.

Policy summary (see docs/methodology.md):
* Exit status, stdout and (by default) stderr must match exactly across configurations.
* Normalization happens only when explicitly enabled in ComparisonPolicy.
* Floating-point tolerance applies only to tokens that look like floating-point numbers
  (contain '.' or an exponent) and only for cases that declare a tolerance.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Sequence

from .config import ComparisonPolicy
from .models import ConfigRun, Difference, ExecResult, Outcome, ProgramCase, Safety

_FLOAT_TOKEN = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+(?=[eE]))(?:[eE][+-]?\d+)?$|^[+-]?(?:inf|nan)$", re.I)
_MAX_DIFF_LINES = 12


def normalize_text(text: str, policy: ComparisonPolicy) -> str:
    if policy.normalize_line_endings:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    if policy.strip_trailing_whitespace:
        text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text


def _floats_close(a: str, b: str, tol: float) -> bool:
    x, y = float(a), float(b)
    if math.isnan(x) and math.isnan(y):
        return True
    return math.isclose(x, y, rel_tol=tol, abs_tol=tol)


def _equal_with_tolerance(a: str, b: str, tol: float) -> bool:
    lines_a, lines_b = a.split("\n"), b.split("\n")
    if len(lines_a) != len(lines_b):
        return False
    for la, lb in zip(lines_a, lines_b):
        if la == lb:
            continue
        ta, tb = la.split(), lb.split()
        if len(ta) != len(tb):
            return False
        for x, y in zip(ta, tb):
            if x == y:
                continue
            if _FLOAT_TOKEN.match(x) and _FLOAT_TOKEN.match(y) and _floats_close(x, y, tol):
                continue
            return False
    return True


def text_difference(
    a: str, b: str, policy: ComparisonPolicy, float_tolerance: float | None = None
) -> str | None:
    """Return a short description of how two outputs differ, or None if equivalent."""
    na, nb = normalize_text(a, policy), normalize_text(b, policy)
    if na == nb:
        return None
    if float_tolerance is not None and _equal_with_tolerance(na, nb, float_tolerance):
        return None
    diff = list(difflib.unified_diff(na.splitlines(), nb.splitlines(), "A", "B", lineterm="", n=1))[2:]
    if not diff:  # differs only in line endings / trailing newline
        return f"outputs differ in whitespace only (A={na!r:.80}, B={nb!r:.80})"
    shown = diff[:_MAX_DIFF_LINES]
    if len(diff) > _MAX_DIFF_LINES:
        shown.append("... (diff truncated)")
    return "\n".join(shown)


def describe_status(run: ExecResult) -> str:
    if run.timed_out:
        return "timeout"
    if run.signal is not None:
        return f"killed by signal {run.signal}"
    if run.crashed:
        return f"abnormal termination (exit code {run.exit_code & 0xFFFFFFFF:#x})"
    return f"exit code {run.exit_code}"


def compare_runs(
    runs: Sequence[ConfigRun], case: ProgramCase, policy: ComparisonPolicy
) -> list[Difference]:
    """Compare every executed run against the first one, and against declared expectations."""
    executed = [r for r in runs if r.run is not None]
    diffs: list[Difference] = []
    if not executed:
        return diffs
    base = executed[0]
    assert base.run is not None
    for other in executed[1:]:
        assert other.run is not None
        status_a, status_b = describe_status(base.run), describe_status(other.run)
        if status_a != status_b:
            diffs.append(Difference("exit_status", base.name, other.name, f"{status_a} vs {status_b}"))
        out = text_difference(base.run.stdout, other.run.stdout, policy, case.float_tolerance)
        if out:
            diffs.append(Difference("stdout", base.name, other.name, out))
        if policy.compare_stderr:
            err = text_difference(base.run.stderr, other.run.stderr, policy, case.float_tolerance)
            if err:
                diffs.append(Difference("stderr", base.name, other.name, err))
    for run in executed:
        assert run.run is not None
        if case.expected_exit is not None and run.run.exit_code != case.expected_exit:
            diffs.append(
                Difference(
                    "expected_exit",
                    "expected",
                    run.name,
                    f"expected exit code {case.expected_exit}, got {describe_status(run.run)}",
                )
            )
        if case.expected_stdout is not None:
            out = text_difference(case.expected_stdout, run.run.stdout, policy, case.float_tolerance)
            if out:
                diffs.append(Difference("expected_stdout", "expected", run.name, out))
    return diffs


def first_error_line(stderr: str) -> str:
    """Pick the first diagnostic that mentions 'error', without the (temporary) file path."""
    lines = [ln.strip() for ln in stderr.strip().splitlines() if ln.strip()]
    chosen = next((ln for ln in lines if "error" in ln.lower()), lines[0] if lines else "no diagnostics")
    marker = chosen.lower().find("error")
    return (chosen[marker:] if marker >= 0 else chosen)[:200]


def _names(runs: Sequence[ConfigRun]) -> str:
    return ", ".join(r.name for r in runs)


def classify(
    case: ProgramCase, runs: Sequence[ConfigRun], policy: ComparisonPolicy
) -> tuple[Outcome, list[Difference], str, list[str]]:
    """Classify a set of runs. Precedence: COMPILE_ERROR > TIMEOUT > CRASH (all configs) > MISMATCH > PASS.

    A crash in only some configurations is reported as MISMATCH because the behavior differs.
    """
    compile_failed = [r for r in runs if not r.compile.ok and not r.compile.timed_out]
    if compile_failed:
        first = compile_failed[0].compile
        snippet = first_error_line(first.stderr)
        return Outcome.COMPILE_ERROR, [], f"compilation failed under {_names(compile_failed)}: {snippet}", []
    timed_out = [r for r in runs if r.compile.timed_out or (r.run is not None and r.run.timed_out)]
    if timed_out:
        return Outcome.TIMEOUT, [], f"compilation or execution timed out under {_names(timed_out)}", []
    crashed = [r for r in runs if r.run is not None and r.run.crashed]
    if runs and len(crashed) == len(runs):
        detail = "; ".join(f"{r.name}: {describe_status(r.run)}" for r in crashed if r.run)
        return Outcome.CRASH, [], f"program terminated abnormally in every configuration ({detail})", []
    diffs = compare_runs(runs, case, policy)
    if diffs:
        notes = ["A mismatch is not proof of a compiler defect: rule out undefined behavior "
                 "(use the sanitize command), implementation-defined behavior, floating-point "
                 "policy and environment effects first."]
        if case.safety is not Safety.WELL_DEFINED:
            notes.append(f"This program is declared {case.safety.value}; its differences are NOT "
                         "evidence of a compiler defect.")
        kinds = sorted({d.kind for d in diffs})
        return Outcome.MISMATCH, diffs, f"{len(diffs)} difference(s): {', '.join(kinds)}", notes
    return Outcome.PASS, [], f"behavior agrees across {len(runs)} configuration(s)", []
