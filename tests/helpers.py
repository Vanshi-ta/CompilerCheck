"""Test doubles: a fake compiler and fake executor that never touch a real toolchain."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from compilercheck.config import Config
from compilercheck.errors import CompilerNotFoundError
from compilercheck.models import (
    Category,
    CompileResult,
    ExecResult,
    Language,
    ProgramCase,
    Safety,
)


class TempDirTestCase(unittest.TestCase):
    """Provides ``self.tmp`` (a Path) that is removed after each test."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory(prefix="cc-test-")
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)


def ok_exec(stdout: str = "ok\n", stderr: str = "", code: int = 0) -> ExecResult:
    return ExecResult(exit_code=code, stdout=stdout, stderr=stderr, duration=0.01)


def make_case(
    test_id: str = "case1",
    source: str = "int main(void){return 0;}\n",
    *,
    language: Language = Language.C,
    safety: Safety = Safety.WELL_DEFINED,
    **kwargs: Any,
) -> ProgramCase:
    return ProgramCase(
        test_id=test_id, source=source, language=language,
        category=kwargs.pop("category", Category.GENERAL), safety=safety, **kwargs,
    )


class FakeCompiler:
    """Pretends to compile: writes a marker file so the engine sees a produced binary."""

    def __init__(self, fail: set[str] | None = None, timeout: set[str] | None = None,
                 missing: bool = False) -> None:
        self.fail = fail or set()
        self.timeout = timeout or set()
        self.missing = missing
        self.calls: list[dict[str, Any]] = []

    def resolve(self, language: Language = Language.C) -> str:
        if self.missing:
            raise CompilerNotFoundError("fakecc not installed")
        return "fakecc"

    def build_command(self, source: Path, output: Path, *, language: Language, optimization: str,
                      std: str | None = None, extra_flags: Any = (), sanitizers: Any = ()) -> list[str]:
        return ["fakecc", f"-std={std}", f"-{optimization}", *extra_flags, str(source), "-o", str(output)]

    def compile(self, source: Path, output: Path, **kwargs: Any) -> CompileResult:
        if self.missing:
            raise CompilerNotFoundError("fakecc not installed")
        opt = kwargs["optimization"]
        self.calls.append({"source": source, **kwargs})
        cmd = self.build_command(source, output, **{k: v for k, v in kwargs.items() if k != "timeout"})
        if opt in self.timeout:
            return CompileResult(False, None, "", "", 1.0, timed_out=True, command=cmd)
        if opt in self.fail:
            return CompileResult(False, 1, "", "x.c:1:1: error: fake failure\n", 0.01, command=cmd)
        Path(output).write_text(f"binary:{opt}", encoding="utf-8")
        return CompileResult(True, 0, "", "", 0.01, command=cmd, binary=str(output))

    def describe(self) -> dict[str, Any]:
        return {"executable": "fakecc", "version": "fakecc 1.0", "cxx_executable": "fakecc++"}


class FakeExecutor:
    """Returns a canned ExecResult chosen by the optimization level in the binary's directory."""

    def __init__(self, results: dict[str, ExecResult] | None = None, default: ExecResult | None = None) -> None:
        self.results = results or {}
        self.default = default or ok_exec()
        self.calls = 0

    def __call__(self, binary: Path, timeout: float, **kwargs: Any) -> ExecResult:
        self.calls += 1
        return self.results.get(Path(binary).parent.name, self.default)


def quiet_config(tmp: Path, **overrides: Any) -> Config:
    base = {"output_dir": tmp / "out", "optimizations": ("O0", "O2")}
    base.update(overrides)
    return Config.from_mapping(base)
