import unittest

from compilercheck.errors import ConfigError
from compilercheck.models import CompileResult, ExecResult, Outcome, Safety
from compilercheck.sanitizers import check_support, find_markers, run_sanitized, validate_sanitizers
from tests.helpers import FakeCompiler, FakeExecutor, TempDirTestCase, make_case, ok_exec, quiet_config


class SanitizerTests(TempDirTestCase):
    def test_validation(self) -> None:
        self.assertEqual(validate_sanitizers(["address", "undefined", "address"]), ("address", "undefined"))
        for bad in ([], ["memory"], ["thread", "address"]):
            with self.assertRaises(ConfigError):
                validate_sanitizers(bad)

    def test_marker_detection(self) -> None:
        self.assertTrue(find_markers("==1==ERROR: AddressSanitizer: heap-buffer-overflow"))
        self.assertTrue(find_markers("a.c:3:5: runtime error: signed integer overflow"))
        self.assertEqual(find_markers("ordinary program output"), [])

    def test_clean_run_passes(self) -> None:
        result = run_sanitized(make_case(), quiet_config(self.tmp), FakeCompiler(), ["address"], FakeExecutor())
        self.assertEqual(result.outcome, Outcome.PASS)
        self.assertEqual(result.runs[0].name, "san:address")

    def test_report_in_stderr_is_a_finding(self) -> None:
        bad = FakeExecutor(default=ok_exec(stderr="a.c:1: runtime error: signed integer overflow\n", code=1))
        result = run_sanitized(make_case(), quiet_config(self.tmp), FakeCompiler(), ["undefined"], bad)
        self.assertEqual(result.outcome, Outcome.CRASH)
        self.assertIn("runtime error", result.reason)
        self.assertTrue(any("not (by themselves) a compiler defect" in n for n in result.notes))

    def test_build_failure_and_ub_skip(self) -> None:
        cfg = quiet_config(self.tmp)
        failed = run_sanitized(make_case(), cfg, FakeCompiler(fail={"O1"}), ["address"], FakeExecutor())
        self.assertEqual(failed.outcome, Outcome.COMPILE_ERROR)
        skipped = run_sanitized(make_case(safety=Safety.UNDEFINED_BEHAVIOR), cfg, FakeCompiler(), ["address"], FakeExecutor())
        self.assertEqual(skipped.outcome, Outcome.SKIPPED)

    def test_check_support_explains_how_to_enable(self) -> None:
        class NoSanitizers(FakeCompiler):
            def compile(self, source, output, **kwargs):  # type: ignore[no-untyped-def]
                return CompileResult(False, 1, "", "clang: error: unsupported option '-fsanitize=address'", 0.1)

        message = check_support(NoSanitizers(), ["address"])
        self.assertIsNotNone(message)
        self.assertIn("compiler-rt", message or "")
        self.assertIsNone(check_support(FakeCompiler(), ["address"], FakeExecutor()))
        broken = FakeExecutor(default=ExecResult(1, "", "", 0.1))
        self.assertIsNotNone(check_support(FakeCompiler(), ["address"], broken))


if __name__ == "__main__":
    unittest.main()
