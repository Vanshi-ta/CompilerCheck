"""Optional sanitizer-assisted runs (AddressSanitizer / UBSan / ThreadSanitizer).

Kept separate from differential testing on purpose: instrumentation changes code
generation and timing, so sanitized runs are a diagnostic tool, not a comparison input.
A sanitizer finding means the *program* has a defect or undefined behavior; it is not by
itself evidence of a compiler defect.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from .config import Config
from .errors import ConfigError
from .executor import run_binary
from .models import CaseResult, ConfigRun, Language, Outcome, ProgramCase, safe_name
from .runner import BINARY_NAME, CompilerLike, ExecuteFn, ineligibility_reason

SANITIZERS = ("address", "undefined", "thread")
_MARKERS = ("ERROR: AddressSanitizer", "ERROR: LeakSanitizer", "WARNING: ThreadSanitizer",
            "runtime error:", "SUMMARY: AddressSanitizer", "SUMMARY: UndefinedBehaviorSanitizer")
SANITIZER_OPT = "O1"
HOWTO = (
    "Install a Clang/LLVM build that ships the sanitizer runtimes (Linux: your distribution's "
    "clang plus libclang-rt / compiler-rt packages; macOS: Apple Clang or Homebrew LLVM). "
    "ThreadSanitizer cannot be combined with AddressSanitizer; Windows support varies by toolchain."
)


def validate_sanitizers(names: Sequence[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for name in names:
        if name not in SANITIZERS:
            raise ConfigError(f"unknown sanitizer {name!r}; choose from {', '.join(SANITIZERS)}")
        if name not in unique:
            unique.append(name)
    if not unique:
        raise ConfigError("at least one sanitizer is required")
    if "thread" in unique and len(unique) > 1:
        raise ConfigError("ThreadSanitizer cannot be combined with other sanitizers")
    return tuple(unique)


def find_markers(stderr: str) -> list[str]:
    return [m for m in _MARKERS if m in stderr]


def check_support(compiler: CompilerLike, sanitizers: Sequence[str], execute: ExecuteFn = run_binary,
                  timeout: float = 60.0) -> str | None:
    """Return None if a trivial sanitized program builds and runs, else an explanation."""
    with tempfile.TemporaryDirectory(prefix="compilercheck-san-") as tmp:
        root = Path(tmp)
        src = root / "probe.c"
        src.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        result = compiler.compile(src, root / BINARY_NAME, language=Language.C,
                                  optimization=SANITIZER_OPT, sanitizers=tuple(sanitizers), timeout=timeout)
        if not result.ok:
            first = (result.stderr.strip().splitlines() or ["no diagnostics"])[0]
            return f"sanitizer build failed ({first[:160]}). {HOWTO}"
        probe = execute(root / BINARY_NAME, 30.0)
        if probe.exit_code != 0:
            return f"sanitizer-instrumented probe did not run cleanly. {HOWTO}"
    return None


def run_sanitized(case: ProgramCase, config: Config, compiler: CompilerLike, sanitizers: Sequence[str],
                  execute: ExecuteFn = run_binary) -> CaseResult:
    reason = ineligibility_reason(case, config)
    if reason:
        return CaseResult(case=case, outcome=Outcome.SKIPPED, reason=reason)
    sanitizers = validate_sanitizers(sanitizers)
    name = "san:" + "+".join(sanitizers)
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="compilercheck-") as tmp:
        root = Path(tmp)
        src = root / f"{safe_name(case.test_id)}{case.language.extension}"
        src.write_text(case.source, encoding="utf-8", newline="")
        flags = [*config.extra_flags, *case.extra_flags]
        compiled = compiler.compile(
            src, root / BINARY_NAME, language=case.language, optimization=SANITIZER_OPT,
            std=config.std_for(case.language), extra_flags=flags, sanitizers=sanitizers,
            timeout=case.compile_timeout or config.compile_timeout,
        )
        run = ConfigRun(name=name, flags=[f"-{SANITIZER_OPT}", *flags], compile=compiled)
        if compiled.ok:
            run.run = execute(root / BINARY_NAME, case.run_timeout or config.run_timeout,
                              max_output_bytes=config.max_output_bytes)
    notes = ["Sanitizer findings indicate a defect or undefined behavior in the program, "
             "not (by themselves) a compiler defect."]
    if compiled.timed_out or (run.run and run.run.timed_out):
        outcome, why = Outcome.TIMEOUT, "timed out"
    elif not compiled.ok:
        outcome, why = Outcome.COMPILE_ERROR, "sanitized build failed"
    else:
        assert run.run is not None
        markers = find_markers(run.run.stderr)
        if markers:
            line = next((ln.strip() for ln in run.run.stderr.splitlines() if markers[0] in ln), markers[0])
            outcome, why = Outcome.CRASH, f"sanitizer report: {line[:160]}"
        elif run.run.crashed:
            outcome, why = Outcome.CRASH, "terminated abnormally"
        else:
            outcome, why = Outcome.PASS, "no sanitizer findings"
    return CaseResult(case=case, outcome=outcome, reason=why, runs=[run], notes=notes,
                      duration=time.perf_counter() - start)
