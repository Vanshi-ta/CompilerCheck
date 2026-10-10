import contextlib
import io
import json
import unittest
from unittest import mock

from compilercheck import cli
from compilercheck.models import CaseResult, Outcome
from compilercheck.runner import DifferentialEngine
from tests.helpers import FakeCompiler, FakeExecutor, TempDirTestCase, make_case, ok_exec, quiet_config


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ExitCodeTests(unittest.TestCase):
    def test_exit_code_mapping(self) -> None:
        def res(*outs: Outcome) -> list[CaseResult]:
            return [CaseResult(make_case(), o) for o in outs]

        self.assertEqual(cli.exit_code_for(res(Outcome.PASS, Outcome.SKIPPED)), 0)
        self.assertEqual(cli.exit_code_for(res(Outcome.PASS, Outcome.MISMATCH)), 1)
        self.assertEqual(cli.exit_code_for(res(Outcome.CRASH)), 4)
        self.assertEqual(cli.exit_code_for(res(Outcome.COMPILE_ERROR, Outcome.TIMEOUT)), 4)
        self.assertEqual(cli.exit_code_for(res(Outcome.CRASH, Outcome.MISMATCH)), 1)


class CliTests(TempDirTestCase):
    def patched_engine(self, executor: FakeExecutor, compiler: FakeCompiler | None = None):  # type: ignore[no-untyped-def]
        def factory(config):  # type: ignore[no-untyped-def]
            return DifferentialEngine(config, compiler or FakeCompiler(), executor)
        return mock.patch.object(cli, "_make_engine", factory)

    def args(self, *extra: str) -> list[str]:
        return [*extra, "--output-dir", str(self.tmp / "out")]

    def write_source(self, name: str = "t.c") -> str:
        path = self.tmp / name
        path.write_text("// compilercheck: safety=well_defined\nint main(void){return 0;}\n")
        return str(path)

    def test_help_and_usage_errors(self) -> None:
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(io.StringIO()):
            cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        for bad in ([], ["bogus"], ["run", "--suite", "nope"], ["regressions"]):
            with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
                cli.main(bad)
            self.assertEqual(ctx.exception.code, 2)

    def test_missing_compiler_is_infrastructure_error(self) -> None:
        code, _, err = run_cli("run", "--source", self.write_source(), "--compiler", "definitely-not-a-compiler-xyz",
                               *self.args())
        self.assertEqual(code, 3)
        self.assertIn("not found", err)
        self.assertIn("Install Clang", err)

    def test_doctor_without_compiler(self) -> None:
        code, out, _ = run_cli("doctor", "--compiler", "definitely-not-a-compiler-xyz")
        self.assertEqual(code, 3)
        self.assertIn("NOT AVAILABLE", out)

    def test_run_pass_exit_zero_and_report_written(self) -> None:
        with self.patched_engine(FakeExecutor()):
            code, out, _ = run_cli("run", "--source", self.write_source(), *self.args())
        self.assertEqual(code, 0)
        self.assertIn("Successful (PASS)       : 1", out)
        report = json.loads((self.tmp / "out" / "reports" / "latest.json").read_text())
        self.assertEqual(report["summary"]["passed"], 1)

    def test_run_mismatch_exit_one(self) -> None:
        execs = FakeExecutor({"O0": ok_exec("a"), "O1": ok_exec("b"), "O2": ok_exec("a"), "O3": ok_exec("a")})
        with self.patched_engine(execs):
            code, out, _ = run_cli("run", "--source", self.write_source(), *self.args())
        self.assertEqual(code, 1)
        self.assertIn("[MISMATCH]", out)
        self.assertTrue((self.tmp / "out" / "artifacts" / "t__mismatch").is_dir())

    def test_run_compile_error_exit_four(self) -> None:
        with self.patched_engine(FakeExecutor(), FakeCompiler(fail={"O1"})):
            code, _, _ = run_cli("run", "--source", self.write_source(), *self.args())
        self.assertEqual(code, 4)

    def test_all_skipped_is_not_success(self) -> None:
        path = self.tmp / "ub.c"
        path.write_text("// compilercheck: safety=undefined_behavior\nint main(void){return 0;}\n")
        with self.patched_engine(FakeExecutor()):
            code, _, err = run_cli("run", "--source", str(path), *self.args())
        self.assertEqual(code, 3)
        self.assertIn("nothing was verified", err)

    def test_optimization_selection_and_no_artifacts(self) -> None:
        compiler = FakeCompiler()
        execs = FakeExecutor({"O0": ok_exec("a"), "O3": ok_exec("b")})
        with self.patched_engine(execs, compiler):
            code, _, _ = run_cli("run", "--source", self.write_source(), "--optimizations", "O0", "O3",
                                 "--no-artifacts", *self.args())
        self.assertEqual(code, 1)
        self.assertEqual([c["optimization"] for c in compiler.calls], ["O0", "O3"])
        self.assertFalse((self.tmp / "out" / "artifacts").exists())

    def test_generated_suite_runs_requested_count(self) -> None:
        with self.patched_engine(FakeExecutor()):
            code, out, _ = run_cli("run", "--suite", "generated", "--seed", "42", "--count", "4", *self.args())
        self.assertEqual(code, 0)
        self.assertIn("Total tests             : 4", out)
        self.assertIn("gen-s42-0000-", out)

    def test_bad_optimization_is_infrastructure_error(self) -> None:
        code, _, err = run_cli("run", "--source", self.write_source(), "--optimizations", "Ofast", *self.args())
        self.assertEqual(code, 3)
        self.assertIn("Ofast", err)

    def test_report_commands(self) -> None:
        code, _, err = run_cli("report", "--latest", *self.args())
        self.assertEqual(code, 3)
        self.assertIn("no report found", err)
        with self.patched_engine(FakeExecutor()):
            run_cli("run", "--source", self.write_source(), *self.args())
        code, out, _ = run_cli("report", "--latest", *self.args())
        self.assertEqual(code, 0)
        self.assertIn("Total tests             : 1", out)
        code, out, _ = run_cli("report", "--json", *self.args())
        self.assertEqual(json.loads(out)["summary"]["total"], 1)

    def test_regression_workflow(self) -> None:
        regs = ["--regressions-dir", str(self.tmp / "regs")]
        with self.patched_engine(FakeExecutor()):
            code, out, _ = run_cli("regressions", "add", "--source", self.write_source(), "--id", "r1", *regs, *self.args())
            self.assertEqual(code, 0)
            self.assertIn("expected PASS", out)
            code, out, _ = run_cli("regressions", "list", *regs, *self.args())
            self.assertIn("r1", out)
            code, out, _ = run_cli("regressions", "run", *regs, *self.args())
            self.assertEqual(code, 0)
            self.assertIn("[OK     ] r1", out)
        changed = FakeExecutor({"O0": ok_exec("a"), "O1": ok_exec("b"), "O2": ok_exec("a"), "O3": ok_exec("a")})
        with self.patched_engine(changed):
            code, out, _ = run_cli("regressions", "run", "--id", "r1", *regs, *self.args())
            self.assertEqual(code, 1)
            self.assertIn("[CHANGED] r1", out)
            self.assertEqual(run_cli("regressions", "update", "r1", *regs, *self.args())[0], 2)
            self.assertEqual(run_cli("regressions", "update", "r1", "--accept", *regs, *self.args())[0], 0)
            self.assertEqual(run_cli("regressions", "run", "--id", "r1", *regs, *self.args())[0], 0)

    def test_regression_add_argument_validation_and_unknown_id(self) -> None:
        regs = ["--regressions-dir", str(self.tmp / "regs")]
        self.assertEqual(run_cli("regressions", "add", *regs, *self.args())[0], 2)
        code, _, err = run_cli("regressions", "run", "--id", "ghost", *regs, *self.args())
        self.assertEqual(code, 3)
        self.assertIn("no such regression", err)

    def test_rerun_from_artifact(self) -> None:
        execs = FakeExecutor({"O0": ok_exec("a"), "O1": ok_exec("b"), "O2": ok_exec("a"), "O3": ok_exec("a")})
        with self.patched_engine(execs):
            run_cli("run", "--source", self.write_source(), *self.args())
            code, out, _ = run_cli("rerun", str(self.tmp / "out" / "artifacts" / "t__mismatch"), *self.args())
        self.assertEqual(code, 1)
        self.assertIn("suite: rerun", out)

    def test_config_file_and_cli_override(self) -> None:
        cfg = self.tmp / "c.json"
        cfg.write_text(json.dumps({"optimizations": ["O1", "O2"], "c_std": "c99"}))
        args = cli.build_parser().parse_args(["doctor", "--config", str(cfg), "--c-std", "c17"])
        config = cli.build_config(args)
        self.assertEqual((config.optimizations, config.c_std), (("O1", "O2"), "c17"))

    def test_quiet_config_helper_is_valid(self) -> None:
        self.assertEqual(quiet_config(self.tmp).optimizations, ("O0", "O2"))


if __name__ == "__main__":
    unittest.main()
