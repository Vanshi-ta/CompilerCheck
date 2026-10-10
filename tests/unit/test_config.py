import json
import unittest

from compilercheck.config import Config, normalize_optimization
from compilercheck.errors import ConfigError
from tests.helpers import TempDirTestCase


class ConfigTests(TempDirTestCase):
    def test_normalize_optimization_variants(self) -> None:
        for raw, expected in (("O2", "O2"), ("-O3", "O3"), ("o1", "O1"), ("0", "O0"), ("s", "Os"), ("-Oz", "Oz")):
            self.assertEqual(normalize_optimization(raw), expected)

    def test_ofast_and_garbage_rejected(self) -> None:
        for bad in ("Ofast", "O4", "fast", ""):
            with self.assertRaises(ConfigError):
                normalize_optimization(bad)

    def test_validation(self) -> None:
        self.assertEqual(Config(optimizations=("-O2", "O2", "O0")).validated().optimizations, ("O2", "O0"))
        for bad in (Config(optimizations=()), Config(run_timeout=0), Config(c_std="--evil"),
                    Config(cxx_std="c++ 17"), Config(extra_flags=("no-dash",)), Config(extra_flags=("-a b",)),
                    Config(reduce_budget=0)):
            with self.assertRaises(ConfigError):
                bad.validated()

    def test_from_mapping_and_unknown_key(self) -> None:
        cfg = Config.from_mapping({"optimizations": ["O1", "O3"], "compiler": "gcc", "run_timeout": 3})
        self.assertEqual((cfg.optimizations, cfg.compiler, cfg.run_timeout), (("O1", "O3"), "gcc", 3))
        with self.assertRaises(ConfigError):
            Config.from_mapping({"optimisations": ["O1"]})

    def test_from_file(self) -> None:
        path = self.tmp / "cfg.json"
        path.write_text(json.dumps({"c_std": "c99", "compare_stderr": False}))
        cfg = Config.from_file(path)
        self.assertEqual(cfg.c_std, "c99")
        self.assertFalse(cfg.compare_stderr)
        path.write_text("[1]")
        with self.assertRaises(ConfigError):
            Config.from_file(path)
        path.write_text("{bad")
        with self.assertRaises(ConfigError):
            Config.from_file(path)
        with self.assertRaises(ConfigError):
            Config.from_file(self.tmp / "missing.json")

    def test_policy_defaults_conceal_nothing(self) -> None:
        policy = Config().policy
        self.assertFalse(policy.normalize_line_endings or policy.strip_trailing_whitespace)
        self.assertTrue(policy.compare_stderr)

    def test_replay_dict_roundtrips(self) -> None:
        cfg = Config(optimizations=("O0", "O2"), compiler="gcc").validated()
        self.assertEqual(Config.from_mapping(cfg.to_replay_dict()).optimizations, ("O0", "O2"))


if __name__ == "__main__":
    unittest.main()
