import unittest

from compilercheck.errors import ReductionError
from compilercheck.reducer import is_removable_line, reduce_source

SOURCE = """#include <stdio.h>
int main(void) {
    int a = 1;
    int b = 2;
    int keep = 3;
    int c = 4;
    printf("%d\\n", keep);
    return 0;
}
"""


class ReducerTests(unittest.TestCase):
    def test_removes_irrelevant_statements(self) -> None:
        calls: list[str] = []

        def predicate(text: str) -> bool:
            calls.append(text)
            return "int keep = 3;" in text and "printf" in text

        outcome = reduce_source(SOURCE, predicate, budget=50)
        self.assertNotIn("int a", outcome.source)
        self.assertNotIn("int b", outcome.source)
        self.assertNotIn("int c", outcome.source)
        self.assertIn("int keep = 3;", outcome.source)
        self.assertIn("#include <stdio.h>", outcome.source)
        self.assertTrue(outcome.reduced)
        self.assertEqual(outcome.attempts, len(calls))
        self.assertFalse(outcome.budget_exhausted)

    def test_every_accepted_candidate_satisfied_predicate(self) -> None:
        def predicate(text: str) -> bool:
            return "int keep = 3;" in text

        outcome = reduce_source(SOURCE, predicate, budget=50)
        self.assertTrue(predicate(outcome.source))

    def test_budget_is_respected(self) -> None:
        count = 0

        def predicate(text: str) -> bool:
            nonlocal count
            count += 1
            return False if count > 1 else True

        outcome = reduce_source(SOURCE, predicate, budget=2)
        self.assertLessEqual(count, 3)
        self.assertTrue(outcome.budget_exhausted or outcome.attempts <= 3)

    def test_original_not_reproducing_raises(self) -> None:
        with self.assertRaises(ReductionError):
            reduce_source(SOURCE, lambda text: False)

    def test_invalid_budget(self) -> None:
        with self.assertRaises(ReductionError):
            reduce_source(SOURCE, lambda text: True, budget=0)

    def test_structural_lines_never_removed(self) -> None:
        outcome = reduce_source(SOURCE, lambda text: True, budget=100)
        for line in ("int main(void) {", "return 0;", "}", "#include <stdio.h>"):
            self.assertIn(line, outcome.source)

    def test_removable_line_heuristic(self) -> None:
        self.assertTrue(is_removable_line("    x = 3;"))
        self.assertFalse(is_removable_line("    return 0;"))
        self.assertFalse(is_removable_line("#define X 1;"))
        self.assertFalse(is_removable_line("    if (x) { y = 1; }"))
        self.assertFalse(is_removable_line("    for (int i = 0; i < 3; ++i) x++;"))


if __name__ == "__main__":
    unittest.main()
