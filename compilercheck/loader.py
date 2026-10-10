"""Load test cases from source files.

A source file may begin with a directive comment (within its first 30 lines)::

    // compilercheck: category=arrays safety=well_defined expect_exit=0 timeout=5
    // compilercheck: flags=-pthread,-fno-strict-aliasing description="two words"

An optional sibling file ``<stem>.expected`` holds the exact expected stdout.
Directives are only parsed, never executed.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from .errors import CaseLoadError
from .models import Category, Language, ProgramCase, Safety, safe_name

SUFFIX_LANGUAGE = {".c": Language.C, ".cpp": Language.CPP, ".cc": Language.CPP, ".cxx": Language.CPP}
_DIRECTIVE_RE = re.compile(r"^\s*(?://|/\*|\*|#)\s*compilercheck:\s*(.*?)\s*(?:\*/)?\s*$")
_KEYS = {"category", "safety", "expect_exit", "timeout", "compile_timeout",
         "float_tolerance", "flags", "description", "id"}


def language_for_path(path: Path) -> Language:
    try:
        return SUFFIX_LANGUAGE[path.suffix.lower()]
    except KeyError:
        raise CaseLoadError(f"{path}: unsupported extension (use .c, .cpp, .cc or .cxx)") from None


def parse_directives(source: str, origin: str = "<source>") -> dict[str, str]:
    found: dict[str, str] = {}
    for line in source.splitlines()[:30]:
        match = _DIRECTIVE_RE.match(line)
        if not match:
            continue
        try:
            tokens = shlex.split(match.group(1))
        except ValueError as exc:
            raise CaseLoadError(f"{origin}: malformed directive: {exc}") from exc
        for token in tokens:
            key, sep, value = token.partition("=")
            if not sep or key not in _KEYS:
                raise CaseLoadError(f"{origin}: unknown or malformed directive {token!r}")
            found[key] = value
    return found


def _number(value: str, kind: type, key: str, origin: str):  # type: ignore[no-untyped-def]
    try:
        return kind(value)
    except ValueError:
        raise CaseLoadError(f"{origin}: directive {key}={value!r} is not a valid {kind.__name__}") from None


def case_from_source(
    source: str, language: Language, default_id: str, origin: str
) -> ProgramCase:
    d = parse_directives(source, origin)
    try:
        category = Category(d["category"]) if "category" in d else Category.GENERAL
        safety = Safety(d["safety"]) if "safety" in d else Safety.WELL_DEFINED
    except ValueError as exc:
        raise CaseLoadError(f"{origin}: {exc}") from exc
    flags = tuple(f for f in d.get("flags", "").split(",") if f)
    for flag in flags:
        if not flag.startswith("-"):
            raise CaseLoadError(f"{origin}: invalid compiler flag {flag!r} in directive")
    return ProgramCase(
        test_id=d.get("id", default_id),
        source=source,
        language=language,
        category=category,
        safety=safety,
        expected_exit=_number(d["expect_exit"], int, "expect_exit", origin) if "expect_exit" in d else None,
        run_timeout=_number(d["timeout"], float, "timeout", origin) if "timeout" in d else None,
        compile_timeout=_number(d["compile_timeout"], float, "compile_timeout", origin)
        if "compile_timeout" in d else None,
        float_tolerance=_number(d["float_tolerance"], float, "float_tolerance", origin)
        if "float_tolerance" in d else None,
        extra_flags=flags,
        description=d.get("description", ""),
        metadata={"origin": "file", "path": origin, "safety_declared": "safety" in d},
    )


def load_source_file(path: Path) -> ProgramCase:
    path = Path(path)
    language = language_for_path(path)
    try:
        source = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise CaseLoadError(f"cannot read {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise CaseLoadError(f"{path}: not valid UTF-8: {exc}") from exc
    case = case_from_source(source, language, safe_name(path.stem), str(path))
    expected = path.with_suffix(".expected")
    if expected.is_file():
        try:
            case = replace(case, expected_stdout=expected.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise CaseLoadError(f"cannot read {expected}: {exc}") from exc
    return case


def load_directory(directory: Path) -> list[ProgramCase]:
    directory = Path(directory)
    if not directory.is_dir():
        raise CaseLoadError(f"test-case directory not found: {directory}")
    files = sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIX_LANGUAGE)
    cases = [load_source_file(p) for p in files]
    ids = [c.test_id for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise CaseLoadError(f"duplicate test ids in {directory}: {', '.join(duplicates)}")
    return cases


def load_paths(paths: Iterable[Path]) -> list[ProgramCase]:
    cases: list[ProgramCase] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            cases.extend(load_directory(path))
        elif path.is_file():
            cases.append(load_source_file(path))
        else:
            raise CaseLoadError(f"source path not found: {path}")
    return cases
