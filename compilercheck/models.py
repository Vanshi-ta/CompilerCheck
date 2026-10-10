"""Plain data models shared by all modules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any


class Language(str, Enum):
    C = "c"
    CPP = "cpp"

    @property
    def extension(self) -> str:
        return ".c" if self is Language.C else ".cpp"


class Category(str, Enum):
    INTEGER_ARITHMETIC = "integer_arithmetic"
    SIGNED_UNSIGNED = "signed_unsigned"
    LOOPS_CONDITIONALS = "loops_conditionals"
    ARRAYS = "arrays"
    FUNCTIONS = "functions"
    STRUCTS = "structs"
    FLOATING_POINT = "floating_point"
    BOUNDARY = "boundary"
    OPTIMIZATION_SENSITIVE = "optimization_sensitive"
    UNDEFINED_BEHAVIOR = "undefined_behavior"
    GENERAL = "general"


class Safety(str, Enum):
    """How trustworthy a program is as evidence about compiler correctness."""

    WELL_DEFINED = "well_defined"
    UNDEFINED_BEHAVIOR = "undefined_behavior"
    INVALID = "invalid"


class Outcome(str, Enum):
    PASS = "PASS"
    MISMATCH = "MISMATCH"
    COMPILE_ERROR = "COMPILE_ERROR"
    TIMEOUT = "TIMEOUT"
    CRASH = "CRASH"
    SKIPPED = "SKIPPED"


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str) -> str:
    """Return a filesystem-safe, stable version of an identifier."""
    cleaned = _SAFE_NAME_RE.sub("_", value).strip("._")
    return cleaned or "case"


@dataclass(frozen=True)
class ProgramCase:
    """One program under test together with its declared properties."""

    test_id: str
    source: str
    language: Language
    category: Category = Category.GENERAL
    safety: Safety = Safety.WELL_DEFINED
    expected_stdout: str | None = None
    expected_exit: int | None = None
    seed: int | None = None
    run_timeout: float | None = None
    compile_timeout: float | None = None
    float_tolerance: float | None = None
    extra_flags: tuple[str, ...] = ()
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_source(self, source: str) -> ProgramCase:
        return replace(self, source=source)

    def to_dict(self, include_source: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "test_id": self.test_id,
            "language": self.language.value,
            "category": self.category.value,
            "safety": self.safety.value,
            "expected_stdout": self.expected_stdout,
            "expected_exit": self.expected_exit,
            "seed": self.seed,
            "run_timeout": self.run_timeout,
            "compile_timeout": self.compile_timeout,
            "float_tolerance": self.float_tolerance,
            "extra_flags": list(self.extra_flags),
            "description": self.description,
            "metadata": dict(self.metadata),
        }
        if include_source:
            data["source"] = self.source
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str | None = None) -> ProgramCase:
        text = source if source is not None else data["source"]
        return cls(
            test_id=data["test_id"],
            source=text,
            language=Language(data["language"]),
            category=Category(data.get("category", "general")),
            safety=Safety(data.get("safety", "well_defined")),
            expected_stdout=data.get("expected_stdout"),
            expected_exit=data.get("expected_exit"),
            seed=data.get("seed"),
            run_timeout=data.get("run_timeout"),
            compile_timeout=data.get("compile_timeout"),
            float_tolerance=data.get("float_tolerance"),
            extra_flags=tuple(data.get("extra_flags", ())),
            description=data.get("description", ""),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class CompileResult:
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    command: list[str] = field(default_factory=list)
    binary: str | None = None


@dataclass
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    signal: int | None = None
    crashed: bool = False
    truncated: bool = False


@dataclass
class ConfigRun:
    """Compilation and execution of one program under one configuration."""

    name: str
    flags: list[str]
    compile: CompileResult
    run: ExecResult | None = None


@dataclass
class Difference:
    kind: str  # exit_status | stdout | stderr | expected_exit | expected_stdout
    config_a: str
    config_b: str
    detail: str


@dataclass
class CaseResult:
    case: ProgramCase
    outcome: Outcome
    reason: str = ""
    runs: list[ConfigRun] = field(default_factory=list)
    differences: list[Difference] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration: float = 0.0
    minimized_source: str | None = None
    reduction: dict[str, Any] | None = None
    artifact_dir: str | None = None
    expected_outcome: str | None = None


@dataclass
class RunReport:
    suite: str
    started_at: str
    finished_at: str
    wall_seconds: float
    results: list[CaseResult]
    optimizations: list[str]
    compiler_info: dict[str, Any]
    seed: int | None = None
    policy: dict[str, Any] = field(default_factory=dict)
