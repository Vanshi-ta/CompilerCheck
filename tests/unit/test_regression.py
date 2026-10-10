import unittest

from compilercheck.errors import RegressionError
from compilercheck.models import Outcome
from compilercheck.regression import RegressionStore, run_regression
from compilercheck.runner import DifferentialEngine
from tests.helpers import FakeCompiler, FakeExecutor, TempDirTestCase, make_case, ok_exec, quiet_config


class RegressionStoreTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = RegressionStore(self.tmp / "regs")

    def test_empty_store_lists_nothing(self) -> None:
        self.assertEqual(self.store.list(), [])

    def test_add_list_get_roundtrip(self) -> None:
        case = make_case("reg 1", "int main(void){return 0;}\n", seed=7)
        self.store.add(case, Outcome.MISMATCH, ("O0", "O3"), note="found by seed 7")
        items = self.store.list()
        self.assertEqual(len(items), 1)
        loaded = self.store.get("reg 1")
        self.assertEqual(loaded.expected_outcome, Outcome.MISMATCH)
        self.assertEqual(loaded.optimizations, ("O0", "O3"))
        self.assertEqual(loaded.case.source, case.source)
        self.assertEqual(loaded.case.seed, 7)
        self.assertEqual(loaded.note, "found by seed 7")

    def test_duplicate_requires_force(self) -> None:
        case = make_case("dup")
        self.store.add(case, Outcome.PASS, ("O0", "O2"))
        with self.assertRaises(RegressionError):
            self.store.add(case, Outcome.PASS, ("O0", "O2"))
        self.store.add(case, Outcome.MISMATCH, ("O0", "O2"), overwrite=True)
        self.assertEqual(self.store.get("dup").expected_outcome, Outcome.MISMATCH)

    def test_unknown_regression(self) -> None:
        with self.assertRaises(RegressionError):
            self.store.get("missing")

    def test_expected_outcome_can_be_updated_after_review(self) -> None:
        self.store.add(make_case("upd"), Outcome.MISMATCH, ("O0", "O2"), note="old")
        self.store.update_expected("upd", Outcome.PASS, note="fixed upstream")
        reg = self.store.get("upd")
        self.assertEqual(reg.expected_outcome, Outcome.PASS)
        self.assertEqual(reg.note, "fixed upstream")

    def test_corrupt_record_is_reported(self) -> None:
        self.store.add(make_case("bad"), Outcome.PASS, ("O0", "O2"))
        (self.tmp / "regs" / "bad" / "case.json").write_text("{not json")
        with self.assertRaises(RegressionError):
            self.store.list()

    def test_run_regression_compares_with_expectation(self) -> None:
        self.store.add(make_case("ok"), Outcome.PASS, ("O0", "O1", "O2"))
        engine = DifferentialEngine(quiet_config(self.tmp), FakeCompiler(), FakeExecutor())
        result = run_regression(engine, self.store.get("ok"))
        self.assertEqual(result.outcome, Outcome.PASS)
        self.assertEqual(result.expected_outcome, "PASS")
        self.assertEqual([r.name for r in result.runs], ["O0", "O1", "O2"])  # recorded levels, not config's

    def test_changed_outcome_is_visible(self) -> None:
        self.store.add(make_case("chg"), Outcome.PASS, ("O0", "O2"))
        engine = DifferentialEngine(quiet_config(self.tmp), FakeCompiler(),
                                    FakeExecutor({"O0": ok_exec("a"), "O2": ok_exec("b")}))
        result = run_regression(engine, self.store.get("chg"))
        self.assertEqual(result.outcome, Outcome.MISMATCH)
        self.assertNotEqual(result.expected_outcome, result.outcome.value)


if __name__ == "__main__":
    unittest.main()
