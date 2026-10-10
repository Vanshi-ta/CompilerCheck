import unittest

from compilercheck.models import ExecResult, Language, Outcome, Safety
from compilercheck.runner import DifferentialEngine
from tests.helpers import FakeCompiler, FakeExecutor, TempDirTestCase, make_case, ok_exec, quiet_config


class EngineTests(TempDirTestCase):
    def engine(self, compiler: FakeCompiler | None = None, executor: FakeExecutor | None = None, **cfg: object):
        return DifferentialEngine(quiet_config(self.tmp, **cfg), compiler or FakeCompiler(), executor or FakeExecutor())

    def test_pass_when_all_configs_agree(self) -> None:
        compiler = FakeCompiler()
        result = self.engine(compiler).evaluate(make_case())
        self.assertEqual(result.outcome, Outcome.PASS)
        self.assertEqual([c["optimization"] for c in compiler.calls], ["O0", "O2"])
        self.assertEqual([r.name for r in result.runs], ["O0", "O2"])

    def test_mismatch_from_controlled_double(self) -> None:
        execs = FakeExecutor({"O0": ok_exec("a\n"), "O2": ok_exec("b\n")})
        result = self.engine(executor=execs).evaluate(make_case())
        self.assertEqual(result.outcome, Outcome.MISMATCH)
        self.assertEqual(result.differences[0].kind, "stdout")

    def test_compile_error_is_not_mismatch(self) -> None:
        result = self.engine(FakeCompiler(fail={"O2"})).evaluate(make_case())
        self.assertEqual(result.outcome, Outcome.COMPILE_ERROR)
        self.assertIsNone(result.runs[1].run)

    def test_compile_timeout(self) -> None:
        self.assertEqual(self.engine(FakeCompiler(timeout={"O0"})).evaluate(make_case()).outcome, Outcome.TIMEOUT)

    def test_run_timeout(self) -> None:
        hung = ExecResult(None, "", "", 9.0, timed_out=True)
        result = self.engine(executor=FakeExecutor({"O2": hung})).evaluate(make_case())
        self.assertEqual(result.outcome, Outcome.TIMEOUT)

    def test_crash(self) -> None:
        boom = ExecResult(None, "", "", 0.1, signal=6, crashed=True)
        result = self.engine(executor=FakeExecutor(default=boom)).evaluate(make_case())
        self.assertEqual(result.outcome, Outcome.CRASH)

    def test_ub_programs_skipped_by_default(self) -> None:
        compiler = FakeCompiler()
        result = self.engine(compiler).evaluate(make_case(safety=Safety.UNDEFINED_BEHAVIOR))
        self.assertEqual(result.outcome, Outcome.SKIPPED)
        self.assertEqual(compiler.calls, [])
        self.assertIn("undefined_behavior", result.reason)

    def test_ub_programs_run_when_opted_in(self) -> None:
        result = self.engine(include_unsafe=True).evaluate(make_case(safety=Safety.UNDEFINED_BEHAVIOR))
        self.assertEqual(result.outcome, Outcome.PASS)

    def test_single_level_without_expectation_is_skipped(self) -> None:
        result = self.engine(optimizations=("O2",)).evaluate(make_case())
        self.assertEqual(result.outcome, Outcome.SKIPPED)

    def test_single_level_with_expectation_runs(self) -> None:
        result = self.engine(optimizations=("O2",)).evaluate(make_case(expected_stdout="ok\n"))
        self.assertEqual(result.outcome, Outcome.PASS)

    def test_missing_compiler_is_skipped_with_reason(self) -> None:
        result = self.engine(FakeCompiler(missing=True)).evaluate(make_case())
        self.assertEqual(result.outcome, Outcome.SKIPPED)
        self.assertIn("compiler unavailable", result.reason)

    def test_language_standard_and_flags_are_passed(self) -> None:
        compiler = FakeCompiler()
        case = make_case(language=Language.CPP, extra_flags=("-pthread",))
        self.engine(compiler, c_std="c99", cxx_std="c++20").evaluate(case)
        call = compiler.calls[0]
        self.assertEqual(call["std"], "c++20")
        self.assertIn("-pthread", call["extra_flags"])
        self.assertTrue(str(call["source"]).endswith(".cpp"))

    def test_run_suite_counts_and_artifacts(self) -> None:
        execs = FakeExecutor({"O0": ok_exec("a\n"), "O2": ok_exec("b\n")})
        engine = self.engine(executor=execs)
        seen = []
        report = engine.run_suite([make_case("m1"), make_case("ub", safety=Safety.INVALID)],
                                  suite_name="unit", on_result=seen.append)
        self.assertEqual(len(seen), 2)
        self.assertEqual([r.outcome for r in report.results], [Outcome.MISMATCH, Outcome.SKIPPED])
        self.assertTrue((self.tmp / "out" / "artifacts" / "m1__mismatch" / "metadata.json").is_file())
        self.assertIsNotNone(report.results[0].artifact_dir)
        self.assertIsNone(report.results[1].artifact_dir)

    def test_artifacts_can_be_disabled(self) -> None:
        engine = self.engine(executor=FakeExecutor({"O0": ok_exec("a"), "O2": ok_exec("b")}), save_artifacts=False)
        engine.run_suite([make_case()], suite_name="unit")
        self.assertFalse((self.tmp / "out" / "artifacts").exists())

    def test_reduction_attached_for_mismatch(self) -> None:
        source = "int main(void) {\n    int a = 1;\n    int b = 2;\n    return 0;\n}\n"

        def execute(binary, timeout, **kwargs):  # type: ignore[no-untyped-def]
            return ok_exec("a" if binary.parent.name == "O0" else "b")

        engine = DifferentialEngine(quiet_config(self.tmp, reduce=True, reduce_budget=20), FakeCompiler(), execute)
        report = engine.run_suite([make_case(source=source)], suite_name="unit")
        result = report.results[0]
        self.assertEqual(result.outcome, Outcome.MISMATCH)
        self.assertIsNotNone(result.reduction)
        self.assertNotIn("int a", result.minimized_source or "")
        self.assertIn("int a", result.case.source)  # original retained
        self.assertTrue((self.tmp / "out" / "artifacts" / "case1__mismatch" / "minimized.c").is_file())


if __name__ == "__main__":
    unittest.main()
