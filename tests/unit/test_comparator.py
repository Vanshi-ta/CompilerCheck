import unittest

from compilercheck.comparator import classify, compare_runs, normalize_text, text_difference
from compilercheck.config import ComparisonPolicy
from compilercheck.models import (
    CompileResult,
    ConfigRun,
    ExecResult,
    Outcome,
    Safety,
)
from tests.helpers import make_case, ok_exec

STRICT = ComparisonPolicy()


def run(name: str, result: ExecResult | None = None, compiled: bool = True, timed_out: bool = False) -> ConfigRun:
    comp = CompileResult(compiled, 0 if compiled else 1, "", "error: bad" if not compiled else "", 0.1,
                         timed_out=timed_out)
    return ConfigRun(name, [], comp, result if compiled else None)


class NormalizationTests(unittest.TestCase):
    def test_nothing_is_normalized_by_default(self) -> None:
        self.assertEqual(normalize_text("a \r\nb", STRICT), "a \r\nb")
        self.assertIsNotNone(text_difference("a\n", "a\r\n", STRICT))
        self.assertIsNotNone(text_difference("a\n", "a \n", STRICT))

    def test_line_endings_when_enabled(self) -> None:
        policy = ComparisonPolicy(normalize_line_endings=True)
        self.assertIsNone(text_difference("a\r\nb\r\n", "a\nb\n", policy))

    def test_trailing_whitespace_when_enabled(self) -> None:
        policy = ComparisonPolicy(strip_trailing_whitespace=True)
        self.assertIsNone(text_difference("a  \nb\t", "a\nb", policy))

    def test_meaningful_whitespace_difference_reported(self) -> None:
        detail = text_difference("a b\n", "a  b\n", STRICT)
        self.assertIsNotNone(detail)
        self.assertIn("+a  b", detail or "")


class FloatToleranceTests(unittest.TestCase):
    def test_close_floats_accepted_with_tolerance(self) -> None:
        self.assertIsNone(text_difference("1.0000000001e+00\n", "1.0000000002e+00\n", STRICT, 1e-6))

    def test_far_floats_rejected(self) -> None:
        self.assertIsNotNone(text_difference("1.0e+00\n", "1.1e+00\n", STRICT, 1e-6))

    def test_no_tolerance_means_exact(self) -> None:
        self.assertIsNotNone(text_difference("1.0000000001e+00\n", "1.0000000002e+00\n", STRICT))

    def test_integers_are_never_approximated(self) -> None:
        self.assertIsNotNone(text_difference("1000000000\n", "1000000001\n", STRICT, 0.5))

    def test_non_numeric_tokens_stay_exact(self) -> None:
        self.assertIsNotNone(text_difference("x 1.0\n", "y 1.0\n", STRICT, 1.0))

    def test_underscore_numbers_are_not_floats(self) -> None:
        self.assertIsNotNone(text_difference("1_0.0\n", "10.0\n", STRICT, 1e-3))


class ClassifyTests(unittest.TestCase):
    def test_pass(self) -> None:
        outcome, diffs, _, _ = classify(make_case(), [run("O0", ok_exec()), run("O2", ok_exec())], STRICT)
        self.assertEqual(outcome, Outcome.PASS)
        self.assertEqual(diffs, [])

    def test_stdout_mismatch(self) -> None:
        outcome, diffs, _, notes = classify(make_case(), [run("O0", ok_exec("1\n")), run("O2", ok_exec("2\n"))], STRICT)
        self.assertEqual(outcome, Outcome.MISMATCH)
        self.assertEqual(diffs[0].kind, "stdout")
        self.assertTrue(any("not proof" in n for n in notes))

    def test_exit_code_mismatch(self) -> None:
        outcome, diffs, _, _ = classify(make_case(), [run("O0", ok_exec(code=0)), run("O2", ok_exec(code=3))], STRICT)
        self.assertEqual(outcome, Outcome.MISMATCH)
        self.assertEqual(diffs[0].kind, "exit_status")

    def test_stderr_compared_by_default_but_can_be_ignored(self) -> None:
        runs = [run("O0", ok_exec(stderr="a")), run("O2", ok_exec(stderr="b"))]
        self.assertEqual(classify(make_case(), runs, STRICT)[0], Outcome.MISMATCH)
        self.assertEqual(classify(make_case(), runs, ComparisonPolicy(compare_stderr=False))[0], Outcome.PASS)

    def test_ub_mismatch_note(self) -> None:
        case = make_case(safety=Safety.UNDEFINED_BEHAVIOR)
        _, _, _, notes = classify(case, [run("O0", ok_exec("1")), run("O2", ok_exec("2"))], STRICT)
        self.assertTrue(any("NOT evidence" in n for n in notes))

    def test_compile_error_is_not_a_mismatch(self) -> None:
        outcome, _, reason, _ = classify(make_case(), [run("O0", ok_exec()), run("O2", compiled=False)], STRICT)
        self.assertEqual(outcome, Outcome.COMPILE_ERROR)
        self.assertIn("O2", reason)

    def test_compile_timeout(self) -> None:
        outcome, *_ = classify(make_case(), [run("O0", ok_exec()), run("O2", compiled=False, timed_out=True)], STRICT)
        self.assertEqual(outcome, Outcome.TIMEOUT)

    def test_run_timeout(self) -> None:
        hung = ExecResult(None, "", "", 5.0, timed_out=True)
        self.assertEqual(classify(make_case(), [run("O0", ok_exec()), run("O2", hung)], STRICT)[0], Outcome.TIMEOUT)

    def test_crash_everywhere_is_crash(self) -> None:
        boom = ExecResult(None, "", "", 0.1, signal=11, crashed=True)
        self.assertEqual(classify(make_case(), [run("O0", boom), run("O2", boom)], STRICT)[0], Outcome.CRASH)

    def test_partial_crash_is_mismatch(self) -> None:
        boom = ExecResult(None, "", "", 0.1, signal=11, crashed=True)
        outcome, diffs, _, _ = classify(make_case(), [run("O0", ok_exec()), run("O2", boom)], STRICT)
        self.assertEqual(outcome, Outcome.MISMATCH)
        self.assertIn("signal 11", diffs[0].detail)

    def test_expected_exit_and_stdout(self) -> None:
        case = make_case(expected_exit=0, expected_stdout="ok\n")
        runs = [run("O0", ok_exec("ok\n")), run("O2", ok_exec("ok\n"))]
        self.assertEqual(classify(case, runs, STRICT)[0], Outcome.PASS)
        bad = [run("O0", ok_exec("no\n", code=2)), run("O2", ok_exec("no\n", code=2))]
        outcome, diffs, _, _ = classify(case, bad, STRICT)
        self.assertEqual(outcome, Outcome.MISMATCH)
        self.assertEqual({d.kind for d in diffs}, {"expected_exit", "expected_stdout"})

    def test_compare_runs_with_no_executions(self) -> None:
        self.assertEqual(compare_runs([], make_case(), STRICT), [])


if __name__ == "__main__":
    unittest.main()
