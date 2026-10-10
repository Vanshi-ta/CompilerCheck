import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from compilercheck.compiler import Compiler, derive_cxx_driver
from compilercheck.errors import CompilerNotFoundError, ConfigError
from compilercheck.models import Language
from tests.helpers import TempDirTestCase


class DeriveCxxTests(unittest.TestCase):
    def test_known_drivers(self) -> None:
        self.assertEqual(derive_cxx_driver("clang"), "clang++")
        self.assertEqual(derive_cxx_driver("clang-17"), "clang++-17")
        self.assertEqual(derive_cxx_driver("gcc"), "g++")
        self.assertEqual(derive_cxx_driver("cc"), "c++")

    def test_directory_is_preserved(self) -> None:
        self.assertEqual(Path(derive_cxx_driver("/opt/llvm/bin/clang")), Path("/opt/llvm/bin/clang++"))

    def test_unknown_driver_returns_none(self) -> None:
        self.assertIsNone(derive_cxx_driver("tcc"))


class BuildCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cc = Compiler("clang")

    def test_c_command(self) -> None:
        cmd = self.cc.build_command(Path("a.c"), Path("a.out"), language=Language.C,
                                    optimization="O2", std="c11")
        self.assertEqual(cmd[:3], ["clang", "-std=c11", "-O2"])
        self.assertIn("a.c", cmd)
        self.assertEqual(cmd[cmd.index("-o") + 1], "a.out")

    def test_cpp_uses_derived_driver(self) -> None:
        cmd = self.cc.build_command(Path("a.cpp"), Path("a.out"), language=Language.CPP,
                                    optimization="O0", std="c++17")
        self.assertEqual(cmd[0], "clang++")

    def test_explicit_cxx_driver_wins(self) -> None:
        cc = Compiler("clang", "my-clang++")
        cmd = cc.build_command(Path("a.cpp"), Path("o"), language=Language.CPP, optimization="O1")
        self.assertEqual(cmd[0], "my-clang++")

    def test_extra_flags_and_sanitizers(self) -> None:
        cmd = self.cc.build_command(Path("a.c"), Path("o"), language=Language.C, optimization="O1",
                                    extra_flags=["-pthread"], sanitizers=["address", "undefined"])
        self.assertIn("-fsanitize=address,undefined", cmd)
        self.assertIn("-pthread", cmd)
        self.assertIn("-fno-sanitize-recover=all", cmd)

    def test_unknown_sanitizer_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self.cc.build_command(Path("a.c"), Path("o"), language=Language.C,
                                  optimization="O1", sanitizers=["bogus"])

    def test_underivable_cxx_driver_raises(self) -> None:
        with self.assertRaises(ConfigError):
            Compiler("tcc").driver_for(Language.CPP)

    def test_hostile_filename_stays_one_argument(self) -> None:
        weird = Path("a; rm -rf x.c")
        cmd = self.cc.build_command(weird, Path("o"), language=Language.C, optimization="O0")
        self.assertIn(str(weird), cmd)


class CompileTests(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.cc = Compiler("clang")
        self.src, self.out = self.tmp / "a.c", self.tmp / "a.out"

    def _compile(self) -> object:
        return self.cc.compile(self.src, self.out, language=Language.C, optimization="O2", std="c11", timeout=5)

    def test_missing_compiler(self) -> None:
        with mock.patch("compilercheck.compiler.shutil.which", return_value=None):
            with self.assertRaises(CompilerNotFoundError):
                self.cc.resolve()

    def test_successful_compile_never_uses_shell(self) -> None:
        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            self.out.write_text("bin")
            self.assertIsInstance(argv, list)
            self.assertFalse(kwargs.get("shell", False))
            return subprocess.CompletedProcess(argv, 0, b"", b"warn")

        with mock.patch("compilercheck.compiler.shutil.which", return_value="/usr/bin/clang"), \
                mock.patch("compilercheck.compiler.subprocess.run", side_effect=fake_run):
            result = self._compile()
        self.assertTrue(result.ok)  # type: ignore[attr-defined]
        self.assertEqual(result.stderr, "warn")  # type: ignore[attr-defined]
        self.assertEqual(result.command[0], "/usr/bin/clang")  # type: ignore[attr-defined]

    def test_compile_failure(self) -> None:
        proc = subprocess.CompletedProcess([], 1, b"", b"error: boom")
        with mock.patch("compilercheck.compiler.shutil.which", return_value="clang"), \
                mock.patch("compilercheck.compiler.subprocess.run", return_value=proc):
            result = self._compile()
        self.assertFalse(result.ok)  # type: ignore[attr-defined]
        self.assertEqual(result.exit_code, 1)  # type: ignore[attr-defined]
        self.assertIn("boom", result.stderr)  # type: ignore[attr-defined]

    def test_compile_timeout(self) -> None:
        exc = subprocess.TimeoutExpired(["clang"], 5, output=b"partial", stderr=None)
        with mock.patch("compilercheck.compiler.shutil.which", return_value="clang"), \
                mock.patch("compilercheck.compiler.subprocess.run", side_effect=exc):
            result = self._compile()
        self.assertTrue(result.timed_out)  # type: ignore[attr-defined]
        self.assertFalse(result.ok)  # type: ignore[attr-defined]
        self.assertEqual(result.stdout, "partial")  # type: ignore[attr-defined]

    def test_oserror_becomes_compiler_not_found(self) -> None:
        with mock.patch("compilercheck.compiler.shutil.which", return_value="clang"), \
                mock.patch("compilercheck.compiler.subprocess.run", side_effect=PermissionError("denied")):
            with self.assertRaises(CompilerNotFoundError):
                self._compile()

    def test_version_first_line_and_cache(self) -> None:
        proc = subprocess.CompletedProcess([], 0, "clang version 17.0.0\nTarget: x\n", "")
        with mock.patch("compilercheck.compiler.shutil.which", return_value="clang"), \
                mock.patch("compilercheck.compiler.subprocess.run", return_value=proc) as run:
            self.assertEqual(self.cc.version(), "clang version 17.0.0")
            self.cc.version()
        self.assertEqual(run.call_count, 1)

    def test_describe_reports_missing_compiler(self) -> None:
        with mock.patch("compilercheck.compiler.shutil.which", return_value=None):
            info = self.cc.describe()
        self.assertIsNone(info["resolved"])
        self.assertIn("unavailable", info["version"])

    @unittest.skipIf(sys.platform == "win32", "-lm is not added on Windows")
    def test_math_library_flag_on_posix(self) -> None:
        cmd = self.cc.build_command(self.src, self.out, language=Language.C, optimization="O0")
        self.assertEqual(cmd[-1], "-lm")


if __name__ == "__main__":
    unittest.main()
