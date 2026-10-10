import unittest
from pathlib import Path

from compilercheck.errors import CaseLoadError
from compilercheck.loader import load_directory, load_paths, load_source_file, parse_directives
from compilercheck.models import Category, Language, Safety
from tests.helpers import TempDirTestCase

REPO = Path(__file__).resolve().parents[2]


class LoaderTests(TempDirTestCase):
    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def test_directives_are_parsed(self) -> None:
        d = parse_directives('// compilercheck: category=arrays safety=undefined_behavior timeout=3 description="two words"\n')
        self.assertEqual(d["description"], "two words")
        self.assertEqual(d["timeout"], "3")

    def test_unknown_directive_rejected(self) -> None:
        with self.assertRaises(CaseLoadError):
            parse_directives("// compilercheck: bogus=1\n")

    def test_load_file_with_all_directives(self) -> None:
        path = self.write("t.cpp", "// compilercheck: category=arrays safety=undefined_behavior expect_exit=3 "
                                   "timeout=2.5 compile_timeout=9 float_tolerance=1e-6 flags=-pthread,-fwrapv\nint main(){}\n")
        case = load_source_file(path)
        self.assertEqual(case.language, Language.CPP)
        self.assertEqual(case.category, Category.ARRAYS)
        self.assertEqual(case.safety, Safety.UNDEFINED_BEHAVIOR)
        self.assertEqual((case.expected_exit, case.run_timeout, case.compile_timeout), (3, 2.5, 9.0))
        self.assertEqual(case.float_tolerance, 1e-6)
        self.assertEqual(case.extra_flags, ("-pthread", "-fwrapv"))
        self.assertEqual(case.test_id, "t")
        self.assertTrue(case.metadata["safety_declared"])

    def test_defaults_without_directives(self) -> None:
        case = load_source_file(self.write("plain.c", "int main(void){return 0;}\n"))
        self.assertEqual(case.safety, Safety.WELL_DEFINED)
        self.assertFalse(case.metadata["safety_declared"])
        self.assertIsNone(case.expected_stdout)

    def test_expected_sidecar_is_exact(self) -> None:
        self.write("e.c", "int main(void){return 0;}\n")
        self.write("e.expected", "line1\r\nline2")
        self.assertEqual(load_source_file(self.tmp / "e.c").expected_stdout, "line1\r\nline2")

    def test_bad_values_and_flags(self) -> None:
        for text in ("// compilercheck: expect_exit=abc\n", "// compilercheck: category=nope\n",
                     "// compilercheck: flags=notaflag\n"):
            with self.assertRaises(CaseLoadError):
                load_source_file(self.write("bad.c", text))

    def test_unsupported_extension_and_missing_path(self) -> None:
        with self.assertRaises(CaseLoadError):
            load_source_file(self.write("x.rs", "fn main(){}"))
        with self.assertRaises(CaseLoadError):
            load_paths([self.tmp / "missing.c"])

    def test_directory_loading_sorted_and_duplicate_detection(self) -> None:
        self.write("b.c", "int main(void){return 0;}\n")
        self.write("a.c", "int main(void){return 0;}\n")
        self.write("notes.txt", "ignored")
        self.assertEqual([c.test_id for c in load_directory(self.tmp)], ["a", "b"])
        (self.tmp / "sub").mkdir()
        (self.tmp / "sub" / "a.cpp").write_text("int main(){}\n")
        with self.assertRaises(CaseLoadError):
            load_directory(self.tmp)

    def test_non_utf8_source(self) -> None:
        (self.tmp / "bin.c").write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(CaseLoadError):
            load_source_file(self.tmp / "bin.c")

    def test_shipped_suites_load_and_are_classified(self) -> None:
        smoke = load_directory(REPO / "testcases" / "smoke")
        self.assertGreaterEqual(len(smoke), 8)
        self.assertTrue(all(c.safety is Safety.WELL_DEFINED and c.expected_stdout is not None for c in smoke))
        edu = load_directory(REPO / "testcases" / "educational_undefined_behavior")
        self.assertTrue(all(c.safety is not Safety.WELL_DEFINED for c in edu))
        self.assertTrue(any(c.safety is Safety.INVALID for c in edu))


if __name__ == "__main__":
    unittest.main()
