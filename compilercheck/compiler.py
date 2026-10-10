"""Compiler abstraction: discovery, version query and safe invocation via subprocess.

All commands are argument lists executed without a shell, so source text and file names
can never be interpreted as shell syntax.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .errors import CompilerCheckError, CompilerNotFoundError, ConfigError
from .models import CompileResult, Language

_CXX_DRIVER_RULES = (
    ("clang", "clang++"),
    ("gcc", "g++"),
    ("cc", "c++"),
)
_VERSION_SUFFIX_RE = re.compile(r"^(-\d+)?(\.exe)?$")
_SANITIZER_FLAGS = {"address": "address", "undefined": "undefined", "thread": "thread"}


def derive_cxx_driver(c_driver: str) -> str | None:
    """Map 'clang' -> 'clang++', 'clang-17' -> 'clang++-17', 'gcc' -> 'g++' (keeps the directory)."""
    path = Path(c_driver)
    for base, replacement in _CXX_DRIVER_RULES:
        if path.name.startswith(base) and _VERSION_SUFFIX_RE.match(path.name[len(base):]):
            name = replacement + path.name[len(base):]
            return str(path.with_name(name)) if path.parent != Path(".") else name
    return None


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class Compiler:
    """A C/C++ compiler driver pair (for example clang / clang++)."""

    def __init__(self, executable: str = "clang", cxx_executable: str | None = None) -> None:
        self.executable = executable
        self.cxx_executable = cxx_executable
        self._versions: dict[str, str] = {}

    def driver_for(self, language: Language) -> str:
        if language is Language.C:
            return self.executable
        if self.cxx_executable:
            return self.cxx_executable
        derived = derive_cxx_driver(self.executable)
        if derived is None:
            raise ConfigError(
                f"cannot derive a C++ driver from {self.executable!r}; pass --cxx-compiler"
            )
        return derived

    def resolve(self, language: Language = Language.C) -> str:
        driver = self.driver_for(language)
        found = shutil.which(driver)
        if found is None:
            raise CompilerNotFoundError(f"compiler executable not found on PATH: {driver}")
        return found

    def version(self, language: Language = Language.C) -> str:
        driver = self.resolve(language)
        if driver in self._versions:
            return self._versions[driver]
        try:
            proc = subprocess.run(
                [driver, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CompilerNotFoundError(f"cannot query version of {driver}: {exc}") from exc
        lines = (proc.stdout or proc.stderr).strip().splitlines()
        if proc.returncode != 0 or not lines:
            raise CompilerNotFoundError(f"{driver} --version failed (exit {proc.returncode})")
        self._versions[driver] = lines[0].strip()
        return self._versions[driver]

    def build_command(
        self,
        source: Path,
        output: Path,
        *,
        language: Language,
        optimization: str,
        std: str | None = None,
        extra_flags: Sequence[str] = (),
        sanitizers: Sequence[str] = (),
    ) -> list[str]:
        cmd = [self.driver_for(language)]
        if std:
            cmd.append(f"-std={std}")
        cmd.append(f"-{optimization}")
        if sanitizers:
            unknown = [s for s in sanitizers if s not in _SANITIZER_FLAGS]
            if unknown:
                raise ConfigError(f"unknown sanitizer(s): {', '.join(unknown)}")
            cmd += [
                "-fsanitize=" + ",".join(_SANITIZER_FLAGS[s] for s in sanitizers),
                "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer",
                "-g",
            ]
        cmd += list(extra_flags)
        cmd += [str(source), "-o", str(output)]
        if sys.platform != "win32":
            cmd.append("-lm")
        return cmd

    def compile(
        self,
        source: Path,
        output: Path,
        *,
        language: Language,
        optimization: str,
        std: str | None = None,
        extra_flags: Sequence[str] = (),
        sanitizers: Sequence[str] = (),
        timeout: float = 60.0,
    ) -> CompileResult:
        argv = self.build_command(
            source,
            output,
            language=language,
            optimization=optimization,
            std=std,
            extra_flags=extra_flags,
            sanitizers=sanitizers,
        )
        argv[0] = self.resolve(language)
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                timeout=timeout,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            return CompileResult(
                ok=False,
                exit_code=None,
                stdout=_decode(exc.stdout),
                stderr=_decode(exc.stderr),
                duration=time.perf_counter() - start,
                timed_out=True,
                command=argv,
            )
        except OSError as exc:
            raise CompilerNotFoundError(f"cannot execute compiler {argv[0]}: {exc}") from exc
        duration = time.perf_counter() - start
        produced = Path(output).is_file()
        return CompileResult(
            ok=proc.returncode == 0 and produced,
            exit_code=proc.returncode,
            stdout=_decode(proc.stdout),
            stderr=_decode(proc.stderr),
            duration=duration,
            command=argv,
            binary=str(output) if produced else None,
        )

    def describe(self) -> dict[str, Any]:
        """Best-effort description for reports; never raises for a missing compiler."""
        info: dict[str, Any] = {"executable": self.executable}
        try:
            info["resolved"] = self.resolve(Language.C)
            info["version"] = self.version(Language.C)
        except CompilerCheckError as exc:
            info["resolved"] = None
            info["version"] = f"unavailable: {exc}"
        try:
            info["cxx_executable"] = self.driver_for(Language.CPP)
            info["cxx_resolved"] = shutil.which(info["cxx_executable"])
        except ConfigError as exc:
            info["cxx_executable"] = None
            info["cxx_resolved"] = None
            info["cxx_error"] = str(exc)
        return info
