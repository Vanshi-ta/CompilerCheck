"""Explicit, validated configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from .errors import ConfigError

VALID_OPTIMIZATIONS = ("O0", "O1", "O2", "O3", "Os", "Oz")
DEFAULT_OPTIMIZATIONS = ("O0", "O1", "O2", "O3")
_STD_RE = re.compile(r"^(?:c|gnu)(?:\+\+)?[0-9][0-9a-z]$")


def normalize_optimization(value: str) -> str:
    """Accept 'O2', '-O2', 'o2' or '2' and return 'O2'. -Ofast is rejected on purpose:
    it enables unsafe floating-point transformations that defeat differential testing."""
    text = value.strip().lstrip("-")
    if text in {"0", "1", "2", "3", "s", "z"}:
        text = "O" + text
    if text[:1] in {"o", "O"}:
        text = "O" + text[1:]
    if text not in VALID_OPTIMIZATIONS:
        raise ConfigError(
            f"unsupported optimization level {value!r}; choose from {', '.join(VALID_OPTIMIZATIONS)}"
        )
    return text


def validate_std(value: str, label: str) -> str:
    if not _STD_RE.match(value):
        raise ConfigError(f"invalid {label} language standard {value!r} (examples: c11, c++17)")
    return value


def find_project_root() -> Path:
    """Repository root when running from a checkout, otherwise the working directory."""
    candidate = Path(__file__).resolve().parents[1]
    if (candidate / "testcases").is_dir():
        return candidate
    return Path.cwd()


@dataclass(frozen=True)
class ComparisonPolicy:
    """What counts as 'the same observable behavior'. Nothing is normalized by default."""

    normalize_line_endings: bool = False
    strip_trailing_whitespace: bool = False
    compare_stderr: bool = True


@dataclass(frozen=True)
class Config:
    compiler: str = "clang"
    cxx_compiler: str | None = None
    optimizations: tuple[str, ...] = DEFAULT_OPTIMIZATIONS
    c_std: str = "c11"
    cxx_std: str = "c++17"
    compile_timeout: float = 60.0
    run_timeout: float = 10.0
    extra_flags: tuple[str, ...] = ()
    normalize_line_endings: bool = False
    strip_trailing_whitespace: bool = False
    compare_stderr: bool = True
    include_unsafe: bool = False
    reduce: bool = False
    reduce_budget: int = 100
    save_artifacts: bool = True
    max_output_bytes: int = 1_000_000
    output_dir: Path = Path("compilercheck-out")
    testcases_dir: Path | None = None
    regressions_dir: Path | None = None

    def validated(self) -> Config:
        opts: list[str] = []
        for item in self.optimizations:
            norm = normalize_optimization(item)
            if norm not in opts:
                opts.append(norm)
        if not opts:
            raise ConfigError("at least one optimization level is required")
        if self.compile_timeout <= 0 or self.run_timeout <= 0:
            raise ConfigError("timeouts must be positive")
        if self.reduce_budget < 1:
            raise ConfigError("reduce_budget must be at least 1")
        if self.max_output_bytes < 1:
            raise ConfigError("max_output_bytes must be at least 1")
        for flag in self.extra_flags:
            if not flag.startswith("-") or any(ch.isspace() for ch in flag):
                raise ConfigError(f"invalid extra compiler flag {flag!r}")
        return replace(
            self,
            optimizations=tuple(opts),
            c_std=validate_std(self.c_std, "C"),
            cxx_std=validate_std(self.cxx_std, "C++"),
            extra_flags=tuple(self.extra_flags),
            output_dir=Path(self.output_dir),
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> Config:
        allowed = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ConfigError(f"unknown configuration keys: {', '.join(unknown)}")
        values: dict[str, Any] = dict(data)
        for key in ("optimizations", "extra_flags"):
            if key in values:
                values[key] = tuple(values[key])
        for key in ("output_dir", "testcases_dir", "regressions_dir"):
            if values.get(key) is not None:
                values[key] = Path(values[key])
        return cls(**values).validated()

    @classmethod
    def from_file(cls, path: Path) -> Config:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"cannot read config file {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"config file {path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"config file {path} must contain a JSON object")
        return cls.from_mapping(data)

    @property
    def policy(self) -> ComparisonPolicy:
        return ComparisonPolicy(
            self.normalize_line_endings, self.strip_trailing_whitespace, self.compare_stderr
        )

    def std_for(self, language: Any) -> str:
        return self.c_std if getattr(language, "value", language) == "c" else self.cxx_std

    def resolved_testcases_dir(self) -> Path:
        return self.testcases_dir or find_project_root() / "testcases"

    def resolved_regressions_dir(self) -> Path:
        return self.regressions_dir or find_project_root() / "regressions"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def artifacts_dir(self) -> Path:
        return self.output_dir / "artifacts"

    def to_replay_dict(self) -> dict[str, Any]:
        """The subset of settings needed to rerun a test from a saved artifact."""
        return {
            "compiler": self.compiler,
            "cxx_compiler": self.cxx_compiler,
            "optimizations": list(self.optimizations),
            "c_std": self.c_std,
            "cxx_std": self.cxx_std,
            "compile_timeout": self.compile_timeout,
            "run_timeout": self.run_timeout,
            "extra_flags": list(self.extra_flags),
            "normalize_line_endings": self.normalize_line_endings,
            "strip_trailing_whitespace": self.strip_trailing_whitespace,
            "compare_stderr": self.compare_stderr,
        }
