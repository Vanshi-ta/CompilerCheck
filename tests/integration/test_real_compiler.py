"""Integration tests against a real compiler.

The compiler is $COMPILERCHECK_TEST_COMPILER if set, otherwise ``clang``. Tests are skipped
(with an explicit reason) when no usable compiler is found. They never rely on finding a
real compiler bug: every program here is well defined or deliberately broken.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

from compilercheck import cli
from compilercheck.compiler import Compiler
from compilercheck.generator import generate_cases
from compilercheck.loader import load_directory
from compilercheck.models import Language, Outcome, Safety
from compilercheck.runner import DifferentialEngine
from compilercheck.sanitizers import check_support, run_sanitized
from tests.helpers import TempDirTestCase, make_case, quiet_config

REPO = Path(__file__).resolve().parents[2]
CC = os.environ.get("COMPILERCHECK_TEST_COMPILER", "clang")
HAVE_C = shutil.which(CC) is not None
SKIP_REASON = f"compiler {CC!r} not found on PATH (set COMPILERCHECK_TEST_COMPILER to override)"


def cli_run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, out.getvalue()


@unittest.skipUnless(HAVE_C, SKIP_REASON)
class RealCompilerTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.compiler = Compiler(CC)
        self.config = quiet_config(self.tmp, compiler=CC, optimizations=("O0", "O1", "O2", "O3"),
                                   run_timeout=5.0, compile_timeout=60.0)
        self.engine = DifferentialEngine(self.config, self.compiler)

    def test_version_is_reported(self) -> None:
        self.assertTrue(self.compiler.version())

    def test_hello_world_passes_with_expectations(self) -> None:
        case = make_case("hello", '#include <stdio.h>\nint main(void){puts("hi");return 0;}\n',
                         expected_stdout="hi\n", expected_exit=0)
        result = self.engine.evaluate(case)
        self.assertEqual(result.outcome, Outcome.PASS, result.reason)
        self.assertEqual(len(result.runs), 4)

    def test_compile_error_detected(self) -> None:
        result = self.engine.evaluate(make_case("broken", "int main(void){ return }\n"))
        self.assertEqual(result.outcome, Outcome.COMPILE_ERROR)
        self.assertTrue(all(not r.compile.ok for r in result.runs))

    def test_nonzero_exit_is_consistent_not_a_failure(self) -> None:
        result = self.engine.evaluate(make_case("exit3", "int main(void){return 3;}\n", expected_exit=3))
        self.assertEqual(result.outcome, Outcome.PASS)

    def test_run_timeout_detected(self) -> None:
        engine = DifferentialEngine(quiet_config(self.tmp, compiler=CC, run_timeout=1.0), self.compiler)
        src = "int main(void){ volatile int x = 1; while (x) { } return 0; }\n"
        result = engine.evaluate(make_case("spin", src))
        self.assertEqual(result.outcome, Outcome.TIMEOUT)

    @unittest.skipIf(sys.platform == "win32", "abort() exit status differs on Windows")
    def test_crash_detected(self) -> None:
        src = "#include <stdlib.h>\nint main(void){ abort(); }\n"
        result = self.engine.evaluate(make_case("aborts", src))
        self.assertEqual(result.outcome, Outcome.CRASH)

    def test_cpp_program(self) -> None:
        src = '#include <cstdio>\ntemplate<class T> T twice(T v){return v+v;}\nint main(){std::printf("%d\\n", twice(21));}\n'
        result = self.engine.evaluate(make_case("cpp", src, language=Language.CPP, expected_stdout="42\n"))
        self.assertEqual(result.outcome, Outcome.PASS, result.reason)

    def test_smoke_suite_passes_through_engine(self) -> None:
        report = self.engine.run_suite(load_directory(REPO / "testcases" / "smoke"), suite_name="smoke")
        failures = [(r.case.test_id, r.outcome.value, r.reason) for r in report.results if r.outcome is not Outcome.PASS]
        self.assertEqual(failures, [])
        self.assertGreaterEqual(len(report.results), 8)

    def test_generated_programs_agree_across_levels(self) -> None:
        cases = generate_cases(seed=2024, count=22)
        report = self.engine.run_suite(cases, suite_name="generated", seed=2024)
        failures = [(r.case.test_id, r.outcome.value, r.reason) for r in report.results if r.outcome is not Outcome.PASS]
        self.assertEqual(failures, [])

    def test_generated_programs_are_clean_under_sanitizers(self) -> None:
        if check_support(self.compiler, ("address", "undefined")) is not None:
            self.skipTest("sanitizers unavailable for this compiler")
        for case in generate_cases(seed=7, count=11):
            result = run_sanitized(case, self.config, self.compiler, ("address", "undefined"))
            self.assertEqual(result.outcome, Outcome.PASS, f"{case.test_id}: {result.reason}")

    def test_educational_programs_never_produce_unqualified_mismatch(self) -> None:
        config = quiet_config(self.tmp, compiler=CC, include_unsafe=True, optimizations=("O0", "O2"))
        report = DifferentialEngine(config, self.compiler).run_suite(
            load_directory(REPO / "testcases" / "educational_undefined_behavior"), suite_name="educational")
        for result in report.results:
            self.assertIsNot(result.case.safety, Safety.WELL_DEFINED)
            if result.outcome is Outcome.MISMATCH:
                self.assertTrue(any("NOT evidence" in n for n in result.notes))

    def test_ub_programs_are_skipped_by_default(self) -> None:
        cases = load_directory(REPO / "testcases" / "educational_undefined_behavior")
        report = self.engine.run_suite(cases, suite_name="default-policy")
        self.assertTrue(all(r.outcome is Outcome.SKIPPED for r in report.results))

    def test_sanitizer_detects_signed_overflow_or_bounds_error(self) -> None:
        if check_support(self.compiler, ("address", "undefined")) is not None:
            self.skipTest("sanitizers unavailable for this compiler")
        src = '#include <stdio.h>\nint main(void){ int a[2]={1,2}; volatile int i = 5; printf("%d\\n", a[i]); return 0; }\n'
        config = quiet_config(self.tmp, compiler=CC, include_unsafe=True)
        case = make_case("oob", src, safety=Safety.UNDEFINED_BEHAVIOR)
        result = run_sanitized(case, config, self.compiler, ("address", "undefined"))
        self.assertEqual(result.outcome, Outcome.CRASH)

    def test_artifact_rerun_roundtrip_via_cli(self) -> None:
        base = ["--compiler", CC, "--output-dir", str(self.tmp / "cli-out")]
        src = self.tmp / "bad.c"
        src.write_text("// compilercheck: safety=well_defined\nint main(void){ return }\n")
        code, _ = cli_run("run", "--source", str(src), *base)
        self.assertEqual(code, 4)
        artifact = self.tmp / "cli-out" / "artifacts" / "bad__compile_error"
        self.assertTrue((artifact / "metadata.json").is_file())
        code, out = cli_run("rerun", str(artifact), *base)
        self.assertEqual(code, 4)
        self.assertIn("COMPILE_ERROR", out)

    def test_cli_smoke_and_regressions(self) -> None:
        base = ["--compiler", CC, "--output-dir", str(self.tmp / "cli-out"),
                "--regressions-dir", str(self.tmp / "regs")]
        code, out = cli_run("run", "--suite", "smoke", *base)
        self.assertEqual(code, 0, out)
        report = json.loads((self.tmp / "cli-out" / "reports" / "latest.json").read_text())
        self.assertEqual(report["summary"]["passed"], report["summary"]["total"])
        smoke = REPO / "testcases" / "smoke" / "unsigned_wrap.c"
        self.assertEqual(cli_run("regressions", "add", "--source", str(smoke), "--id", "wrap", *base)[0], 0)
        self.assertEqual(cli_run("regressions", "run", *base)[0], 0)
        code, out = cli_run("regressions", "add", "--source", str(smoke), "--id", "wrong", "--expected", "MISMATCH", *base)
        self.assertEqual(code, 0)
        self.assertEqual(cli_run("regressions", "run", "--id", "wrong", *base)[0], 1)

    def test_shipped_regressions_still_hold(self) -> None:
        code, out = cli_run("regressions", "run", "--compiler", CC, "--output-dir", str(self.tmp / "o"),
                            "--regressions-dir", str(REPO / "regressions"))
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
