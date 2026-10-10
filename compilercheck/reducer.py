"""Bounded, line-oriented test-case reduction.

This is deliberately NOT a C/C++-aware reducer (it does not parse code). It removes whole
lines that look like simple single-line statements, in decreasing chunk sizes (a simplified
delta-debugging loop), and accepts a candidate only if the caller-supplied predicate still
reports the interesting behavior (for example "still MISMATCH across all configurations").
Candidates that no longer compile therefore fail the predicate and are rejected, so broken
source can never be accepted as a reduction. Limitations: no reduction inside multi-line
statements, no expression simplification, no renaming; each predicate call may run several
compilations, so the budget bounds total cost, not wall-clock time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import ReductionError


@dataclass
class ReductionOutcome:
    source: str
    original_lines: int
    final_lines: int
    attempts: int
    accepted: int
    budget_exhausted: bool

    @property
    def reduced(self) -> bool:
        return self.final_lines < self.original_lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_lines": self.original_lines,
            "final_lines": self.final_lines,
            "attempts": self.attempts,
            "accepted": self.accepted,
            "budget_exhausted": self.budget_exhausted,
            "method": "line-based delta debugging (not compiler-aware)",
        }


def is_removable_line(line: str) -> bool:
    """Heuristic: a single-line simple statement. Never preprocessor, braces or return."""
    text = line.strip()
    if not text.endswith(";") or text.startswith("#") or "{" in text or "}" in text:
        return False
    return not text.startswith(("return", "for", "while", "if", "else", "do", "switch", "case"))


def reduce_source(source: str, predicate: Callable[[str], bool], budget: int = 100) -> ReductionOutcome:
    """Reduce ``source`` while ``predicate`` stays true. The input string is never modified."""
    if budget < 1:
        raise ReductionError("reduction budget must be at least 1")
    lines = source.splitlines(keepends=True)
    attempts = 1
    if not predicate(source):
        raise ReductionError("the original source does not reproduce the behavior; cannot reduce")
    current = list(range(len(lines)))  # indices of lines still present
    removable = {i for i, line in enumerate(lines) if is_removable_line(line)}
    accepted = 0
    exhausted = False
    chunk = max(1, len([i for i in current if i in removable]) // 2)
    while True:
        progress = False
        position = 0
        while True:
            candidates = [i for i in current if i in removable]
            if position >= len(candidates):
                break
            drop = set(candidates[position : position + chunk])
            if attempts >= budget + 1:
                exhausted = True
                break
            trial = [i for i in current if i not in drop]
            attempts += 1
            if predicate("".join(lines[i] for i in trial)):
                current = trial
                accepted += 1
                progress = True
            else:
                position += chunk
        if exhausted or (chunk == 1 and not progress):
            break
        if chunk > 1:
            chunk = max(1, chunk // 2)
    final = "".join(lines[i] for i in current)
    return ReductionOutcome(final, len(lines), len(current), attempts, accepted, exhausted)
