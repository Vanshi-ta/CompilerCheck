import json
import unittest

from compilercheck.errors import ReportError
from compilercheck.models import CaseResult, Difference, Outcome, RunReport
from compilercheck.reporter import (
    compute_summary,
    format_summary,
    latest_report_path,
    load_report,
    report_to_dict,
    write_report,
)
from tests.helpers import TempDirTestCase, make_case


def result(test_id: str, outcome: Outcome, **kw: object) -> CaseResult:
    return CaseResult(make_case(test_id), outcome, reason=f"{outcome.value} reason", **kw)  # type: ignore[arg-type]


def sample_report() -> RunReport:
    results = [
        result("a", Outcome.PASS),
        result("b", Outcome.PASS),
        result("c", Outcome.MISMATCH, differences=[Difference("stdout", "O0", "O2", "@@ -1 +1 @@\n-1\n+2")],
               notes=["be careful"], artifact_dir="/x/c__mismatch"),
        result("d", Outcome.COMPILE_ERROR),
        result("e", Outcome.TIMEOUT),
        result("f", Outcome.CRASH),
        result("g", Outcome.SKIPPED),
        result("h", Outcome.SKIPPED),
    ]
    return RunReport("unit", "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:09+00:00", 3.5, results,
                     ["O0", "O1", "O2"], {"version": "fake 1.0"}, seed=5)


class ReporterTests(TempDirTestCase):
    def test_summary_is_computed_from_results(self) -> None:
        s = compute_summary(sample_report().results, 3, 3.5)
        self.assertEqual((s["total"], s["passed"], s["mismatches"], s["compile_errors"]), (8, 2, 1, 1))
        self.assertEqual((s["timeouts"], s["crashes"], s["skipped"], s["configurations"]), (1, 1, 2, 3))
        self.assertEqual(s["wall_seconds"], 3.5)

    def test_summary_changes_with_results(self) -> None:
        s = compute_summary([result("only", Outcome.PASS)], 2, 0.1)
        self.assertEqual((s["total"], s["passed"], s["mismatches"], s["skipped"]), (1, 1, 0, 0))

    def test_unexpected_outcomes_counted(self) -> None:
        r = result("x", Outcome.PASS, expected_outcome="MISMATCH")
        self.assertEqual(compute_summary([r], 2, 0)["unexpected_vs_expected_outcome"], 1)

    def test_json_is_serializable_and_complete(self) -> None:
        data = json.loads(json.dumps(report_to_dict(sample_report())))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["run"]["seed"], 5)
        self.assertEqual(data["summary"]["total"], len(data["results"]))
        self.assertEqual(data["results"][2]["differences"][0]["kind"], "stdout")

    def test_write_and_load_report_with_latest_copy(self) -> None:
        path = write_report(sample_report(), self.tmp / "reports")
        self.assertTrue(path.name.startswith("report-20260102T030405Z"))
        self.assertEqual(load_report(path), load_report(latest_report_path(self.tmp / "reports")))
        second = write_report(sample_report(), self.tmp / "reports")
        self.assertNotEqual(path, second)  # no overwrite on timestamp collision

    def test_terminal_summary_content(self) -> None:
        text = format_summary(report_to_dict(sample_report()))
        for needle in ("Total tests             : 8", "Behavioral mismatches   : 1", "Skipped                 : 2",
                       "Configurations tested   : 3 (O0, O1, O2)", "3.50 s", "[MISMATCH] c:", "-1",
                       "artifact: /x/c__mismatch", "note: be careful", "Skipped:", "fake 1.0"):
            self.assertIn(needle, text)
        self.assertNotIn("@@", text)

    def test_missing_and_malformed_reports(self) -> None:
        with self.assertRaises(ReportError):
            latest_report_path(self.tmp)
        bad = self.tmp / "bad.json"
        bad.write_text("{}")
        with self.assertRaises(ReportError):
            load_report(bad)
        bad.write_text("nope")
        with self.assertRaises(ReportError):
            load_report(bad)

    def test_long_output_is_clipped_in_report(self) -> None:
        from compilercheck.models import CompileResult, ConfigRun, ExecResult
        run = ConfigRun("O0", [], CompileResult(True, 0, "", "", 0.1), ExecResult(0, "x" * 10000, "", 0.1))
        data = report_to_dict(RunReport("u", "2026-01-01T00:00:00+00:00", "", 1.0,
                                        [CaseResult(make_case(), Outcome.PASS, runs=[run])], ["O0"], {}))
        self.assertLess(len(data["results"][0]["configs"][0]["run"]["stdout"]), 2100)


if __name__ == "__main__":
    unittest.main()
