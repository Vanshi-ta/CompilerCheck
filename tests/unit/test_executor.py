import os
import signal
import sys
import unittest
from pathlib import Path

from compilercheck.errors import ExecutionError
from compilercheck.executor import interpret_returncode, run_binary
from tests.helpers import TempDirTestCase

PY = Path(sys.executable)


class ExecutorTests(TempDirTestCase):
    def test_success_captures_streams(self) -> None:
        code = "import sys; print('out'); print('err', file=sys.stderr)"
        result = run_binary(PY, 20, args=["-c", code])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "out")
        self.assertEqual(result.stderr.strip(), "err")
        self.assertFalse(result.crashed or result.timed_out)
        self.assertGreater(result.duration, 0)

    def test_nonzero_exit_is_not_a_crash(self) -> None:
        result = run_binary(PY, 20, args=["-c", "raise SystemExit(7)"])
        self.assertEqual(result.exit_code, 7)
        self.assertFalse(result.crashed)

    def test_timeout_is_enforced(self) -> None:
        result = run_binary(PY, 0.5, args=["-c", "import time; time.sleep(60)"])
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertLess(result.duration, 30)

    @unittest.skipIf(sys.platform == "win32", "signals are POSIX specific")
    def test_signal_termination_is_a_crash(self) -> None:
        result = run_binary(PY, 20, args=["-c", "import os,signal; os.kill(os.getpid(), signal.SIGSEGV)"])
        self.assertTrue(result.crashed)
        self.assertEqual(result.signal, signal.SIGSEGV)
        self.assertIsNone(result.exit_code)

    def test_output_is_truncated(self) -> None:
        result = run_binary(PY, 20, args=["-c", "print('x' * 5000)"], max_output_bytes=100)
        self.assertEqual(len(result.stdout), 100)
        self.assertTrue(result.truncated)

    def test_missing_binary_raises(self) -> None:
        with self.assertRaises(ExecutionError):
            run_binary(self.tmp / "does-not-exist", 5)

    @unittest.skipIf(sys.platform == "win32", "POSIX return codes")
    def test_interpret_returncode_posix(self) -> None:
        self.assertEqual(interpret_returncode(-11), (11, True))
        self.assertEqual(interpret_returncode(3), (None, False))
        self.assertTrue(os.name == "posix")


if __name__ == "__main__":
    unittest.main()
