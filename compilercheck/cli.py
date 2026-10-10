"""Command-line interface.

Exit codes: 0 all tests passed (skips allowed); 1 at least one MISMATCH (or a regression
whose outcome changed); 2 usage error (argparse); 3 infrastructure problem (missing
compiler, unreadable files, nothing could be run); 4 no mismatch but compile errors,
timeouts or crashes were found.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .artifacts import load_artifact
from .compiler import Compiler
from .config import Config
from .errors import CompilerCheckError, CompilerNotFoundError
from .generator import generate_cases
from .loader import load_directory, load_paths
from .models import CaseResult, Language, Outcome, ProgramCase, RunReport
from .regression import RegressionStore, run_regression
from .reporter import (
    format_summary,
    latest_report_path,
    load_report,
    report_to_dict,
    write_report,
)
from .runner import DifferentialEngine, languages_in
from .sanitizers import SANITIZERS, check_support, run_sanitized, validate_sanitizers

EXIT_OK, EXIT_MISMATCH, EXIT_INFRA, EXIT_FAILURES = 0, 1, 3, 4
SUITES = ("smoke", "generated", "educational")
INSTALL_HINT = (
    "Install Clang: Linux `sudo apt install clang` (or your distro's package), macOS "
    "`xcode-select --install` or `brew install llvm`, Windows `winget install LLVM.LLVM`; "
    "or choose another compiler with --compiler."
)


def _add_common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("compiler and comparison options")
    g.add_argument("--config", type=Path, help="JSON file with Config options (CLI flags override it)")
    g.add_argument("--compiler", help="C compiler driver (default: $COMPILERCHECK_COMPILER or clang)")
    g.add_argument("--cxx-compiler", help="C++ compiler driver (default: derived, e.g. clang++)")
    g.add_argument("--optimizations", nargs="+", metavar="LEVEL",
                   help="levels such as O0 O1 O2 O3 Os Oz (write them without a leading dash)")
    g.add_argument("--c-std", help="C standard, e.g. c11")
    g.add_argument("--cxx-std", help="C++ standard, e.g. c++17")
    g.add_argument("--compile-timeout", type=float, help="seconds per compilation")
    g.add_argument("--run-timeout", type=float, help="seconds per execution")
    g.add_argument("--normalize-line-endings", action="store_true", default=None,
                   help="treat CRLF/CR as LF when comparing output")
    g.add_argument("--strip-trailing-whitespace", action="store_true", default=None)
    g.add_argument("--ignore-stderr", action="store_true", default=None, help="do not compare stderr")
    g.add_argument("--output-dir", type=Path, help="where reports and artifacts go (default: compilercheck-out)")
    g.add_argument("--testcases-dir", type=Path)
    g.add_argument("--regressions-dir", type=Path)


def _add_selection(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("test selection")
    g.add_argument("--suite", choices=SUITES, help="built-in suite (default: smoke)")
    g.add_argument("--source", nargs="+", type=Path, metavar="PATH", help="source files or directories")
    g.add_argument("--seed", type=int, default=0, help="seed for the generated suite")
    g.add_argument("--count", type=int, default=20, help="number of generated tests")
    g.add_argument("--language", choices=("c", "cpp", "mixed"), default="mixed", help="generated suite language")
    g.add_argument("--include-unsafe", action="store_true", default=None,
                   help="also run programs declared undefined_behavior/invalid")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compilercheck", description="Differential testing of C/C++ optimization levels.")
    parser.add_argument("--version", action="version", version=f"compilercheck {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check prerequisites")
    _add_common(doctor)

    run = sub.add_parser("run", help="run differential tests")
    _add_common(run)
    _add_selection(run)
    run.add_argument("--reduce", action="store_true", default=None, help="try to minimize mismatching sources")
    run.add_argument("--reduce-budget", type=int, help="max reduction attempts per mismatch (default 100)")
    run.add_argument("--no-artifacts", action="store_true", help="do not write failure artifacts")
    run.add_argument("--verbose", action="store_true")

    rerun = sub.add_parser("rerun", help="rerun a test from a saved artifact directory")
    _add_common(rerun)
    rerun.add_argument("artifact", type=Path)
    rerun.add_argument("--minimized", action="store_true", help="use minimized source if present")

    san = sub.add_parser("sanitize", help="run programs under Clang sanitizers (separate from differential testing)")
    _add_common(san)
    _add_selection(san)
    san.add_argument("--sanitizers", nargs="+", default=["address", "undefined"], choices=SANITIZERS)

    report = sub.add_parser("report", help="show a saved report")
    _add_common(report)
    report.add_argument("--latest", action="store_true", help="show the latest report (default)")
    report.add_argument("--file", type=Path, help="show a specific report file")
    report.add_argument("--json", action="store_true", help="print the raw JSON")
    report.add_argument("--verbose", action="store_true")

    reg = sub.add_parser("regressions", help="manage regression cases")
    rsub = reg.add_subparsers(dest="reg_command", required=True)
    lst = rsub.add_parser("list", help="list stored regressions")
    add = rsub.add_parser("add", help="store a program as a regression")
    add.add_argument("--source", type=Path, help="source file to store")
    add.add_argument("--from-artifact", type=Path, help="failure artifact directory to store")
    add.add_argument("--minimized", action="store_true", help="with --from-artifact: use minimized source")
    add.add_argument("--expected", choices=[o.value for o in Outcome], help="expected outcome (default: current)")
    add.add_argument("--id", dest="test_id", help="regression id (default: from the source)")
    add.add_argument("--note", default="")
    add.add_argument("--force", action="store_true", help="replace an existing regression")
    runp = rsub.add_parser("run", help="run all or one regression")
    runp.add_argument("--id", dest="test_id")
    upd = rsub.add_parser("update", help="re-evaluate a regression and accept the new outcome")
    upd.add_argument("test_id")
    upd.add_argument("--accept", action="store_true", help="required: confirms the change was reviewed")
    upd.add_argument("--note")
    for sp in (lst, add, runp, upd):
        _add_common(sp)
    return parser


def build_config(args: argparse.Namespace, base: Config | None = None) -> Config:
    from_env = base is None and not getattr(args, "config", None)
    if base is None:
        base = Config.from_file(args.config) if getattr(args, "config", None) else Config()
    compiler = args.compiler or (os.environ.get("COMPILERCHECK_COMPILER") if from_env else None)
    pairs = {
        "compiler": compiler, "cxx_compiler": args.cxx_compiler,
        "optimizations": tuple(args.optimizations) if args.optimizations else None,
        "c_std": args.c_std, "cxx_std": args.cxx_std,
        "compile_timeout": args.compile_timeout, "run_timeout": args.run_timeout,
        "normalize_line_endings": args.normalize_line_endings,
        "strip_trailing_whitespace": args.strip_trailing_whitespace,
        "compare_stderr": False if args.ignore_stderr else None,
        "output_dir": args.output_dir, "testcases_dir": args.testcases_dir,
        "regressions_dir": args.regressions_dir,
        "include_unsafe": getattr(args, "include_unsafe", None),
        "reduce": getattr(args, "reduce", None),
        "reduce_budget": getattr(args, "reduce_budget", None),
    }
    overrides = {k: v for k, v in pairs.items() if v is not None}
    if getattr(args, "no_artifacts", False):
        overrides["save_artifacts"] = False
    return replace(base, **overrides).validated()


def _collect(args: argparse.Namespace, config: Config) -> tuple[list[ProgramCase], str, Config]:
    if args.source:
        return load_paths(args.source), "custom-sources", config
    suite = args.suite or "smoke"
    base = config.resolved_testcases_dir()
    if suite == "generated":
        return generate_cases(args.seed, args.count, args.language), "generated", config
    if suite == "educational":
        cases = load_directory(base / "educational_undefined_behavior")
        return cases, "educational", replace(config, include_unsafe=True)
    return load_directory(base / "smoke"), "smoke", config


def _precheck(compiler: Compiler, cases: Sequence[ProgramCase]) -> str | None:
    for language in sorted(languages_in(cases), key=lambda lang: lang.value):
        try:
            compiler.resolve(language)
        except CompilerNotFoundError as exc:
            return f"{exc}\n{INSTALL_HINT}"
    return None


def exit_code_for(results: Sequence[CaseResult]) -> int:
    outcomes = {r.outcome for r in results}
    if Outcome.MISMATCH in outcomes:
        return EXIT_MISMATCH
    if outcomes & {Outcome.COMPILE_ERROR, Outcome.TIMEOUT, Outcome.CRASH}:
        return EXIT_FAILURES
    return EXIT_OK


def _print_result(result: CaseResult) -> None:
    print(f"[{result.outcome.value:13}] {result.case.test_id}  ({result.duration:.2f}s)", flush=True)


def _make_engine(config: Config) -> DifferentialEngine:
    return DifferentialEngine(config, Compiler(config.compiler, config.cxx_compiler))


def cmd_doctor(args: argparse.Namespace) -> int:
    config = build_config(args)
    compiler = Compiler(config.compiler, config.cxx_compiler)
    ok = sys.version_info >= (3, 11)
    print(f"Python        : {platform.python_version()} ({'ok' if ok else 'need 3.11 or newer'})")
    print(f"Platform      : {platform.platform()}")
    for label, language in (("C compiler", Language.C), ("C++ compiler", Language.CPP)):
        try:
            print(f"{label:14}: {compiler.resolve(language)} -> {compiler.version(language)}")
        except CompilerCheckError as exc:
            print(f"{label:14}: NOT AVAILABLE ({exc})")
            ok = ok and language is not Language.C
    print(f"Test cases    : {config.resolved_testcases_dir()}"
          f" ({'found' if config.resolved_testcases_dir().is_dir() else 'missing'})")
    try:
        problem = check_support(compiler, ("address", "undefined"))
        print(f"Sanitizers    : {'address+undefined supported' if problem is None else 'unavailable (optional): ' + problem}")
    except CompilerCheckError:
        print("Sanitizers    : not checked (compiler unavailable)")
    if not ok:
        print(INSTALL_HINT)
    return EXIT_OK if ok else EXIT_INFRA


def cmd_run(args: argparse.Namespace) -> int:
    config = build_config(args)
    cases, suite, config = _collect(args, config)
    if not cases:
        print("error: no test cases selected", file=sys.stderr)
        return EXIT_INFRA
    engine = _make_engine(config)
    problem = _precheck(engine.compiler, cases)  # type: ignore[arg-type]
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return EXIT_INFRA
    if args.source and any(not c.metadata.get("safety_declared") for c in cases):
        print("note: sources without a 'safety' directive are assumed well-defined; verify them "
              "(see `sanitize`) before treating a mismatch as a compiler issue.")
    report = engine.run_suite(cases, suite_name=suite, seed=args.seed if suite == "generated" else None,
                              on_result=_print_result)
    path = write_report(report, config.reports_dir)
    print()
    print(format_summary(report_to_dict(report), verbose=args.verbose))
    print(f"\nJSON report: {path}")
    if all(r.outcome is Outcome.SKIPPED for r in report.results):
        print("error: every test was skipped; nothing was verified", file=sys.stderr)
        return EXIT_INFRA
    return exit_code_for(report.results)


def cmd_rerun(args: argparse.Namespace) -> int:
    case, replay = load_artifact(args.artifact, use_minimized=args.minimized)
    recorded = Config.from_mapping({k: v for k, v in replay.items() if v is not None})
    config = replace(build_config(args, base=recorded), include_unsafe=True, save_artifacts=False)
    engine = _make_engine(config)
    problem = _precheck(engine.compiler, [case])  # type: ignore[arg-type]
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return EXIT_INFRA
    report = engine.run_suite([case], suite_name="rerun", on_result=_print_result)
    path = write_report(report, config.reports_dir)
    print(format_summary(report_to_dict(report), verbose=True))
    print(f"\nJSON report: {path}")
    return exit_code_for(report.results)


def cmd_sanitize(args: argparse.Namespace) -> int:
    config = build_config(args)
    cases, suite, config = _collect(args, config)
    sanitizers = validate_sanitizers(args.sanitizers)
    compiler = Compiler(config.compiler, config.cxx_compiler)
    problem = _precheck(compiler, cases)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return EXIT_INFRA
    unsupported = check_support(compiler, sanitizers)
    if unsupported:
        print(f"error: sanitizers {'+'.join(sanitizers)} unavailable: {unsupported}", file=sys.stderr)
        return EXIT_INFRA
    results = []
    for case in cases:
        result = run_sanitized(case, config, compiler, sanitizers)
        _print_result(result)
        if result.outcome not in (Outcome.PASS, Outcome.SKIPPED):
            print(f"      {result.reason}")
        results.append(result)
    clean = sum(r.outcome is Outcome.PASS for r in results)
    print(f"\nSanitizer run ({suite}, {'+'.join(sanitizers)}): {clean}/{len(results)} clean, "
          f"{sum(r.outcome is Outcome.SKIPPED for r in results)} skipped")
    if all(r.outcome is Outcome.SKIPPED for r in results):
        return EXIT_INFRA
    return EXIT_OK if all(r.outcome in (Outcome.PASS, Outcome.SKIPPED) for r in results) else EXIT_MISMATCH


def cmd_report(args: argparse.Namespace) -> int:
    config = build_config(args)
    path = args.file or latest_report_path(config.reports_dir)
    data = load_report(path)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_summary(data, verbose=args.verbose))
        print(f"\nReport file: {path}")
    return EXIT_OK


def cmd_regressions(args: argparse.Namespace) -> int:
    config = build_config(args)
    store = RegressionStore(config.resolved_regressions_dir())
    if args.reg_command == "list":
        items = store.list()
        if not items:
            print(f"no regressions in {store.directory}")
        for r in items:
            print(f"{r.case.test_id:40} expected={r.expected_outcome.value:13} "
                  f"opts={','.join(r.optimizations)}  {r.note}")
        return EXIT_OK
    if args.reg_command == "add":
        return _regressions_add(args, config, store)
    if args.reg_command == "update":
        return _regressions_update(args, config, store)
    return _regressions_run(args, config, store)


def _evaluate_now(case: ProgramCase, config: Config) -> CaseResult:
    config = replace(config, include_unsafe=True, save_artifacts=False)
    engine = _make_engine(config)
    problem = _precheck(engine.compiler, [case])  # type: ignore[arg-type]
    if problem:
        raise CompilerNotFoundError(problem)
    return engine.evaluate(case)


def _regressions_add(args: argparse.Namespace, config: Config, store: RegressionStore) -> int:
    if bool(args.source) == bool(args.from_artifact):
        print("error: give exactly one of --source or --from-artifact", file=sys.stderr)
        return 2
    if args.from_artifact:
        case, replay = load_artifact(args.from_artifact, use_minimized=args.minimized)
        config = replace(config, optimizations=tuple(replay["optimizations"]))
    else:
        case = load_paths([args.source])[0]
    if args.test_id:
        case = replace(case, test_id=args.test_id)
    if args.expected:
        expected = Outcome(args.expected)
    else:
        result = _evaluate_now(case, config)
        if result.outcome is Outcome.SKIPPED:
            print(f"error: cannot record current outcome: {result.reason}", file=sys.stderr)
            return EXIT_INFRA
        expected = result.outcome
    path = store.add(case, expected, config.optimizations, args.note, overwrite=args.force)
    print(f"stored regression {case.test_id} (expected {expected.value}) in {path}")
    return EXIT_OK


def _regressions_update(args: argparse.Namespace, config: Config, store: RegressionStore) -> int:
    if not args.accept:
        print("error: pass --accept to confirm you reviewed the new outcome", file=sys.stderr)
        return 2
    regression = store.get(args.test_id)
    result = run_regression(_make_engine(config), regression)
    if result.outcome is Outcome.SKIPPED:
        print(f"error: cannot update: {result.reason}", file=sys.stderr)
        return EXIT_INFRA
    store.update_expected(args.test_id, result.outcome, args.note)
    print(f"{args.test_id}: expected outcome {regression.expected_outcome.value} -> {result.outcome.value}")
    return EXIT_OK


def _regressions_run(args: argparse.Namespace, config: Config, store: RegressionStore) -> int:
    items = [store.get(args.test_id)] if args.test_id else store.list()
    if not items:
        print(f"error: no regressions in {store.directory}", file=sys.stderr)
        return EXIT_INFRA
    engine = _make_engine(config)
    problem = _precheck(engine.compiler, [r.case for r in items])  # type: ignore[arg-type]
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return EXIT_INFRA
    started, t0 = datetime.now(timezone.utc), time.perf_counter()
    results = []
    for reg in items:
        result = run_regression(engine, reg)
        status = "OK     " if result.outcome.value == reg.expected_outcome.value else "CHANGED"
        print(f"[{status}] {reg.case.test_id}: expected {reg.expected_outcome.value}, got {result.outcome.value}")
        results.append(result)
    report = RunReport("regressions", started.isoformat(timespec="seconds"),
                       datetime.now(timezone.utc).isoformat(timespec="seconds"), time.perf_counter() - t0,
                       results, sorted({o for r in items for o in r.optimizations}), engine.compiler.describe())
    path = write_report(report, config.reports_dir)
    print()
    print(format_summary(report_to_dict(report)))
    print(f"\nJSON report: {path}")
    changed = [r for r in results if r.expected_outcome != r.outcome.value]
    if any(r.outcome is Outcome.SKIPPED for r in results):
        return EXIT_INFRA
    return EXIT_MISMATCH if changed else EXIT_OK


COMMANDS = {"doctor": cmd_doctor, "run": cmd_run, "rerun": cmd_rerun, "sanitize": cmd_sanitize,
            "report": cmd_report, "regressions": cmd_regressions}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except CompilerCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INFRA
    except BrokenPipeError:  # e.g. output piped into `head`
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return EXIT_INFRA


__all__ = ["main", "build_parser", "exit_code_for"]
