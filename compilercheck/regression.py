"""Regression store: previously interesting programs with a reviewed expected outcome.

Layout: ``<dir>/<test_id>/case.json`` plus ``source.c`` / ``source.cpp``. The expected
outcome is just data; after investigation it can be changed with ``update_expected``
(a fixed bug may turn MISMATCH into PASS, an accepted behavior may stay as recorded).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .errors import RegressionError
from .models import CaseResult, Outcome, ProgramCase, safe_name
from .runner import DifferentialEngine

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Regression:
    case: ProgramCase
    expected_outcome: Outcome
    optimizations: tuple[str, ...]
    note: str
    recorded_at: str


class RegressionStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _case_dir(self, test_id: str) -> Path:
        return self.directory / safe_name(test_id)

    def add(
        self, case: ProgramCase, expected: Outcome, optimizations: tuple[str, ...],
        note: str = "", overwrite: bool = False,
    ) -> Path:
        target = self._case_dir(case.test_id)
        if (target / "case.json").exists() and not overwrite:
            raise RegressionError(f"regression {case.test_id!r} already exists (use --force to replace)")
        try:
            target.mkdir(parents=True, exist_ok=True)
            (target / f"source{case.language.extension}").write_text(case.source, encoding="utf-8", newline="")
            record = {
                "schema_version": SCHEMA_VERSION,
                "test": case.to_dict(include_source=False),
                "expected_outcome": expected.value,
                "optimizations": list(optimizations),
                "note": note,
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            (target / "case.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise RegressionError(f"cannot write regression {case.test_id}: {exc}") from exc
        return target

    def _load(self, case_json: Path) -> Regression:
        try:
            record = json.loads(case_json.read_text(encoding="utf-8"))
            test = record["test"]
            ext = ".c" if test["language"] == "c" else ".cpp"
            source = (case_json.parent / f"source{ext}").read_bytes().decode("utf-8")
            return Regression(
                case=ProgramCase.from_dict(test, source=source),
                expected_outcome=Outcome(record["expected_outcome"]),
                optimizations=tuple(record["optimizations"]),
                note=record.get("note", ""),
                recorded_at=record.get("recorded_at", ""),
            )
        except (OSError, KeyError, ValueError) as exc:
            raise RegressionError(f"corrupt regression {case_json.parent.name}: {exc}") from exc

    def list(self) -> list[Regression]:
        if not self.directory.is_dir():
            return []
        return [self._load(p) for p in sorted(self.directory.glob("*/case.json"))]

    def get(self, test_id: str) -> Regression:
        path = self._case_dir(test_id) / "case.json"
        if not path.is_file():
            raise RegressionError(f"no such regression: {test_id}")
        return self._load(path)

    def update_expected(self, test_id: str, expected: Outcome, note: str | None = None) -> None:
        path = self._case_dir(test_id) / "case.json"
        regression = self.get(test_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["expected_outcome"] = expected.value
        record["note"] = regression.note if note is None else note
        record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def run_regression(engine: DifferentialEngine, regression: Regression) -> CaseResult:
    """Evaluate with the optimization levels recorded for the regression."""
    config: Config = replace(engine.config, optimizations=regression.optimizations, save_artifacts=False,
                             include_unsafe=True)
    result = engine.with_config(config).evaluate(regression.case)
    result.expected_outcome = regression.expected_outcome.value
    return result
