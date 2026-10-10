import re
import unittest

from compilercheck.errors import CaseLoadError
from compilercheck.generator import TEMPLATES, generate_cases
from compilercheck.models import Language, Safety


class GeneratorTests(unittest.TestCase):
    def test_same_seed_same_programs(self) -> None:
        a, b = generate_cases(42, 30), generate_cases(42, 30)
        self.assertEqual([c.source for c in a], [c.source for c in b])
        self.assertEqual([c.test_id for c in a], [c.test_id for c in b])
        self.assertEqual([c.language for c in a], [c.language for c in b])

    def test_different_seeds_differ(self) -> None:
        a, b = generate_cases(1, 11), generate_cases(2, 11)
        self.assertNotEqual([c.source for c in a], [c.source for c in b])

    def test_prefix_stability(self) -> None:
        self.assertEqual([c.source for c in generate_cases(5, 5)], [c.source for c in generate_cases(5, 12)][:5])

    def test_ids_unique_and_encode_seed(self) -> None:
        cases = generate_cases(9, 40)
        self.assertEqual(len({c.test_id for c in cases}), 40)
        self.assertTrue(all(c.test_id.startswith("gen-s9-") and c.seed == 9 for c in cases))

    def test_every_template_is_used(self) -> None:
        used = {c.metadata["template"] for c in generate_cases(0, len(TEMPLATES))}
        self.assertEqual(used, {t.name for t in TEMPLATES})

    def test_all_generated_programs_are_declared_well_defined(self) -> None:
        self.assertTrue(all(c.safety is Safety.WELL_DEFINED for c in generate_cases(3, 22)))

    def test_c_only_mode(self) -> None:
        cases = generate_cases(0, 30, "c")
        self.assertTrue(all(c.language is Language.C for c in cases))
        self.assertFalse(any("#include <array>" in c.source for c in cases))

    def test_cpp_mode(self) -> None:
        self.assertTrue(all(c.language is Language.CPP for c in generate_cases(0, 15, "cpp")))

    def test_floating_cases_declare_tolerance_and_others_do_not(self) -> None:
        for case in generate_cases(0, 22):
            if case.metadata["template"] == "floating":
                self.assertEqual(case.float_tolerance, 1e-9)
            else:
                self.assertIsNone(case.float_tolerance)

    def test_no_obviously_undefined_constructs(self) -> None:
        for case in generate_cases(11, 66):
            self.assertNotRegex(case.source, r"\bmalloc\b|\bfree\b|\bscanf\b|\brand\(")
            for shift in re.findall(r"<<\s*(\d+)", case.source):
                self.assertLess(int(shift), 32)

    def test_invalid_arguments(self) -> None:
        with self.assertRaises(CaseLoadError):
            generate_cases(0, -1)
        with self.assertRaises(CaseLoadError):
            generate_cases(0, 1, "rust")


if __name__ == "__main__":
    unittest.main()
