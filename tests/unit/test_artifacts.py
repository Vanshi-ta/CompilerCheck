import json
import unittest

from compilercheck.artifacts import artifact_dir_name, load_artifact, save_artifact
from compilercheck.errors import ArtifactError
from compilercheck.models import CaseResult, CompileResult, ConfigRun, Difference, Language, Outcome
from tests.helpers import TempDirTestCase, make_case, ok_exec, quiet_config

INFO = {"executable": "fakecc", "cxx_executable": "fakecc++", "version": "fakecc 1.0"}


def sample_result(language: Language = Language.C, minimized: str | None = None) -> CaseResult:
    case = make_case("art/case 1", "int main(void){return 1;}\n", language=language, seed=42, extra_flags=("-pthread",))
    runs = [
        ConfigRun("O0", ["-std=c11", "-O0"], CompileResult(True, 0, "", "", 0.1, command=["fakecc"]), ok_exec("a\n")),
        ConfigRun("O2", ["-std=c11", "-O2"], CompileResult(True, 0, "", "warn", 0.2, command=["fakecc"]), ok_exec("b\n")),
    ]
    return CaseResult(case, Outcome.MISMATCH, "1 difference(s)", runs,
                      [Difference("stdout", "O0", "O2", "-a\n+b")], minimized_source=minimized)


class ArtifactTests(TempDirTestCase):
    def test_saves_expected_files_with_stable_names(self) -> None:
        result = sample_result(minimized="int main(void){return 1;}\n")
        path = save_artifact(self.tmp, result, quiet_config(self.tmp), INFO)
        self.assertEqual(path.name, "art_case_1__mismatch")
        self.assertEqual(path.name, artifact_dir_name(result))
        names = {p.name for p in path.iterdir()}
        for expected in ("source.c", "minimized.c", "metadata.json", "REPRODUCE.md",
                         "O0.stdout.txt", "O2.stdout.txt", "O0.compile.txt", "O2.stderr.txt"):
            self.assertIn(expected, names)
        self.assertEqual((path / "O2.stdout.txt").read_text(), "b\n")

    def test_metadata_contents(self) -> None:
        path = save_artifact(self.tmp, sample_result(), quiet_config(self.tmp), INFO)
        meta = json.loads((path / "metadata.json").read_text())
        self.assertEqual(meta["test"]["seed"], 42)
        self.assertEqual(meta["test"]["test_id"], "art/case 1")
        self.assertEqual(meta["compiler"]["version"], "fakecc 1.0")
        self.assertEqual(meta["configs"][1]["flags"], ["-std=c11", "-O2"])
        self.assertEqual(meta["configs"][0]["exit_code"], 0)
        self.assertIn("python", meta)
        self.assertIn("platform", meta)
        self.assertEqual(meta["differences"][0]["kind"], "stdout")
        self.assertNotIn("source", meta["test"])

    def test_reproduce_instructions_mention_rerun(self) -> None:
        path = save_artifact(self.tmp, sample_result(), quiet_config(self.tmp), INFO)
        text = (path / "REPRODUCE.md").read_text()
        self.assertIn("compilercheck rerun", text)
        self.assertIn("-O2", text)
        self.assertIn("source.c", text)

    def test_roundtrip_for_rerun(self) -> None:
        path = save_artifact(self.tmp, sample_result(minimized="/* min */\nint main(void){return 1;}\n"),
                             quiet_config(self.tmp), INFO)
        case, replay = load_artifact(path)
        self.assertEqual(case.source, "int main(void){return 1;}\n")
        self.assertEqual(case.extra_flags, ("-pthread",))
        self.assertEqual(replay["optimizations"], ["O0", "O2"])
        small, _ = load_artifact(path, use_minimized=True)
        self.assertTrue(small.source.startswith("/* min */"))

    def test_cpp_extension(self) -> None:
        path = save_artifact(self.tmp, sample_result(Language.CPP), quiet_config(self.tmp), INFO)
        self.assertTrue((path / "source.cpp").is_file())
        self.assertEqual(load_artifact(path)[0].language, Language.CPP)

    def test_overwrites_previous_artifact_cleanly(self) -> None:
        save_artifact(self.tmp, sample_result(minimized="x"), quiet_config(self.tmp), INFO)
        path = save_artifact(self.tmp, sample_result(), quiet_config(self.tmp), INFO)
        self.assertFalse((path / "minimized.c").exists())

    def test_refuses_to_clobber_foreign_directory(self) -> None:
        foreign = self.tmp / "art_case_1__mismatch"
        foreign.mkdir()
        (foreign / "precious.txt").write_text("keep me")
        with self.assertRaises(ArtifactError):
            save_artifact(self.tmp, sample_result(), quiet_config(self.tmp), INFO)
        self.assertTrue((foreign / "precious.txt").exists())

    def test_load_missing_artifact(self) -> None:
        with self.assertRaises(ArtifactError):
            load_artifact(self.tmp / "nope")


if __name__ == "__main__":
    unittest.main()
