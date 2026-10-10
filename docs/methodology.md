# Methodology

## What differential testing can and cannot show

The framework compiles one program several times (for example `-O0 -O1 -O2 -O3`) with the
same compiler and compares observable behavior. For a program with fully defined behavior,
the C and C++ standards require all conforming builds to behave the same (up to
implementation-defined and unspecified choices, which are fixed for one compiler on one
platform). A disagreement is therefore a **lead worth investigating**.

* Agreement does **not** prove the compiler correct: a bug can affect all levels equally,
  or may not be triggered by the chosen inputs.
* A mismatch does **not** prove a compiler defect. Other causes: undefined behavior the
  author did not notice, unspecified behavior, floating-point contraction/reassociation
  flags, reading uninitialized data, address-dependent output, timing-dependent output,
  environment differences, or a harness bug.

## Test-selection policy

Every `ProgramCase` has a `safety` classification:

| Safety | Meaning | Default treatment |
| --- | --- | --- |
| `well_defined` | Believed free of undefined behavior; usable as correctness evidence | Run |
| `undefined_behavior` | Deliberately contains UB, or behavior that is not guaranteed | `SKIPPED` unless `--include-unsafe` |
| `invalid` | Deliberately ill-formed | `SKIPPED` unless `--include-unsafe` |

Generated programs are `well_defined` by construction (unsigned arithmetic, bounded signed
values, in-range shifts, non-zero divisors, in-bounds indexing, no uninitialized reads).
Programs loaded from files are assumed `well_defined` unless a directive says otherwise;
this is a claim by the author and the tool prints a reminder. Use `sanitize` to gain
confidence. Results for non-well-defined programs always carry a note stating that the
difference is not evidence of a compiler defect.

## Comparison policy

* Exit status, stdout and (by default) stderr are compared exactly against the first
  configuration. `--ignore-stderr` disables the stderr comparison.
* Nothing is normalized by default. Opt-in flags: `--normalize-line-endings`,
  `--strip-trailing-whitespace`.
* Floating point: a case may declare `float_tolerance` (directive or generator template).
  Only tokens that look like floating-point literals (contain a decimal point or exponent)
  are compared with `math.isclose(rel_tol=tol, abs_tol=tol)`; every other token, including
  all integers, is compared exactly. Without a declared tolerance, floats are compared as text.
* Declared `expected_stdout` / `expected_exit` are checked for every configuration; a
  deviation is a `MISMATCH` with kind `expected_*` (it can equally mean the expectation is wrong).
* Timing is recorded but never compared.

## Outcome classification

Evaluated in this order:

1. **COMPILE_ERROR** - any configuration failed to compile (timeouts excluded). A compile
   failure is never reported as a behavioral mismatch.
2. **TIMEOUT** - any compilation or execution exceeded its limit.
3. **CRASH** - *every* configuration terminated abnormally (signal on POSIX, NTSTATUS-style
   code on Windows). A crash in only some configurations is a behavioral difference and is
   reported as `MISMATCH`.
4. **MISMATCH** - exit status, stdout, stderr or declared expectations disagree.
5. **PASS** - everything agrees.
6. **SKIPPED** - not evaluated: policy exclusion, fewer than two levels without an
   expectation, or compiler unavailable.

## Undefined behavior reference (see `testcases/educational_undefined_behavior/`)

| Topic | Why it breaks differential testing |
| --- | --- |
| Signed overflow (C and C++) | The optimizer may assume it never happens (`x + 1 > x` becomes true); `-O0` often wraps. |
| Out-of-bounds access | The value read depends on stack/heap layout, which each level lays out differently. |
| Uninitialized variables | The value is indeterminate; the compiler may pick any value per use or delete the branch. |
| Invalid pointers (dangling, past-the-end deref) | Use after lifetime end can read stale data, new data, or crash. |
| Data races | Undefined in C11/C++11; results depend on scheduling and code generation. |
| Floating-point flags | `-ffast-math` and contraction permit reassociation; results may legitimately differ. `-Ofast` is rejected by the CLI. |
| Implementation-defined behavior | Documented per platform (for example `char` signedness, right shift of negatives); stable on one platform, different across platforms. |
| Unspecified behavior | For example argument evaluation order; different conforming choices between compilers or versions. |

These examples are provided to illustrate pitfalls. Whether any given one differs across
levels depends on the compiler, version and platform; the repository makes no claim that
they do.

## Reduction

`reducer.reduce_source` is a bounded, line-oriented delta-debugging loop. It removes
single-line simple statements (never preprocessor lines, braces, `return`, or control
flow) in shrinking chunks, and accepts a candidate only if the predicate - "the engine still
reports MISMATCH" - holds. A candidate that no longer compiles fails the predicate, so
broken source cannot be accepted. It is not compiler-aware: it cannot simplify expressions,
rename, or reduce inside multi-line statements. The original source is always kept
(`source.c`); the result is saved as `minimized.c`. A budget limits the number of
predicate evaluations. Flaky mismatches (timing/ASLR dependent) can defeat reduction.

## Sanitizer runs

`sanitize` builds with `-fsanitize=...` at `-O1`, with `-fno-sanitize-recover=all`, and
looks for sanitizer reports in stderr. It is deliberately separate from differential
comparison because instrumentation changes code generation. A finding means the program is
defective or has UB, which is the first thing to rule out before suspecting a compiler.
