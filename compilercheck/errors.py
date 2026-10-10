"""Exception hierarchy. Every error raised on purpose derives from CompilerCheckError."""

from __future__ import annotations


class CompilerCheckError(Exception):
    """Base class for all CompilerCheck errors."""


class ConfigError(CompilerCheckError):
    """Invalid or inconsistent configuration."""


class CompilerNotFoundError(CompilerCheckError):
    """The configured compiler executable is missing or cannot be started."""


class ExecutionError(CompilerCheckError):
    """A compiled binary could not be started (infrastructure failure)."""


class CaseLoadError(CompilerCheckError):
    """A test-case source file or its directives are invalid."""


class ReductionError(CompilerCheckError):
    """Test-case reduction could not be performed."""


class ArtifactError(CompilerCheckError):
    """A failure artifact could not be written or read."""


class RegressionError(CompilerCheckError):
    """A regression case could not be stored, found or evaluated."""


class ReportError(CompilerCheckError):
    """A report could not be written or read."""
