"""Differential testing engine: compile under several configurations, run, compare, classify."""

from __future__ import annotations

import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .comparator import classify
from .config import Config
from .errors import CompilerNotFoundError
from .executor import run_binary
from .models import (
    CaseResult,
    CompileResult,
    ConfigRun,
    ExecResult,
    Language,
    Outcome,
    ProgramCase,
    RunReport,
    Safety,
    safe_name,
)
from .reducer import reduce_source

ARTIFACT_OUTCOMES = frozenset({Outcome.MISMATCH, Outcome.CRASH, Outcome.TIMEOUT, Outcome.COMPILE_ERROR})
BINARY_NAME = "prog.exe" if sys.platform == "win32" else "prog"


class CompilerLike(Protocol):
    def compile(self, source: Path, output: Path, **kwargs: Any) -> CompileResult: ...
    def build_command(self, source: Path, output: Path, **kwargs: Any) -> list[str]: ...
    def describe(self) -> dict[str, Any]: ...


ExecuteFn = Callable[..., ExecResult]


def ineligibility_reason(case: ProgramCase, config: Config) -> str | None:
    """Policy: only well-defined programs are ordinary correctness evidence."""
    if case.safety is not Safety.WELL_DEFINED and not config.include_unsafe:
        return (
            f"declared {case.safety.value}; excluded from correctness testing "
            "(pass --include-unsafe to run it for educational purposes)"
        )
    return None


class DifferentialEngine:
    def __init__(self, config: Config, compiler: CompilerLike, execute: ExecuteFn = run_binary) -> None:
        self.config = config
        self.compiler = compiler
        self.execute = execute

    def with_config(self, config: Config) -> DifferentialEngine:
        return DifferentialEngine(config, self.compiler, self.execute)

    def _skipped(self, case: ProgramCase, reason: str) -> CaseResult:
        return CaseResult(case=case, outcome=Outcome.SKIPPED, reason=reason)

    def _build_and_run(self, case: ProgramCase, source: Path, workdir: Path, opt: str) -> ConfigRun:
        workdir.mkdir(parents=True, exist_ok=True)
        binary = workdir / BINARY_NAME
        flags = [*self.config.extra_flags, *case.extra_flags]
        std = self.config.std_for(case.language)
        template = self.compiler.build_command(
            Path(f"source{case.language.extension}"), Path("prog"),
            language=case.language, optimization=opt, std=std, extra_flags=flags,
        )
        shown = [a for a in template[1:] if a not in (f"source{case.language.extension}", "-o", "prog", "-lm")]
        compiled = self.compiler.compile(
            source, binary,
            language=case.language, optimization=opt, std=std, extra_flags=flags,
            timeout=case.compile_timeout or self.config.compile_timeout,
        )
        run = ConfigRun(name=opt, flags=shown, compile=compiled)
        if compiled.ok:
            run.run = self.execute(
                binary,
                case.run_timeout or self.config.run_timeout,
                max_output_bytes=self.config.max_output_bytes,
            )
        return run

    def evaluate(self, case: ProgramCase) -> CaseResult:
        reason = ineligibility_reason(case, self.config)
        if reason:
            return self._skipped(case, reason)
        has_expectation = case.expected_stdout is not None or case.expected_exit is not None
        if len(self.config.optimizations) < 2 and not has_expectation:
            return self._skipped(case, "differential testing needs at least two optimization levels "
                                       "(or a declared expectation)")
        start = time.perf_counter()
        runs: list[ConfigRun] = []
        try:
            with tempfile.TemporaryDirectory(prefix="compilercheck-") as tmp:
                root = Path(tmp)
                source = root / f"{safe_name(case.test_id)}{case.language.extension}"
                source.write_text(case.source, encoding="utf-8", newline="")
                for opt in self.config.optimizations:
                    runs.append(self._build_and_run(case, source, root / opt, opt))
        except CompilerNotFoundError as exc:
            return self._skipped(case, f"compiler unavailable: {exc}")
        outcome, diffs, why, notes = classify(case, runs, self.config.policy)
        return CaseResult(case=case, outcome=outcome, reason=why, runs=runs, differences=diffs,
                          notes=notes, duration=time.perf_counter() - start)

    def _attach_reduction(self, result: CaseResult) -> None:
        case = result.case

        def still_mismatches(candidate: str) -> bool:
            return self.evaluate(case.with_source(candidate)).outcome is Outcome.MISMATCH

        outcome = reduce_source(case.source, still_mismatches, self.config.reduce_budget)
        result.reduction = outcome.to_dict()
        if outcome.reduced:
            result.minimized_source = outcome.source

    def run_suite(
        self,
        cases: Iterable[ProgramCase],
        *,
        suite_name: str,
        seed: int | None = None,
        on_result: Callable[[CaseResult], None] | None = None,
    ) -> RunReport:
        from .artifacts import save_artifact  # local import avoids a cycle at module load

        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        info = self.compiler.describe()
        results: list[CaseResult] = []
        for case in cases:
            result = self.evaluate(case)
            if self.config.reduce and result.outcome is Outcome.MISMATCH:
                self._attach_reduction(result)
            if self.config.save_artifacts and result.outcome in ARTIFACT_OUTCOMES:
                path = save_artifact(self.config.artifacts_dir, result, self.config, info)
                result = replace(result, artifact_dir=str(path))
            results.append(result)
            if on_result:
                on_result(result)
        return RunReport(
            suite=suite_name,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            wall_seconds=time.perf_counter() - t0,
            results=results,
            optimizations=list(self.config.optimizations),
            compiler_info=info,
            seed=seed,
            policy={
                "normalize_line_endings": self.config.normalize_line_endings,
                "strip_trailing_whitespace": self.config.strip_trailing_whitespace,
                "compare_stderr": self.config.compare_stderr,
            },
        )


def languages_in(cases: Iterable[ProgramCase]) -> set[Language]:
    return {c.language for c in cases}
