# Limitations and security considerations

## Executing untrusted native code

CompilerCheck compiles and **runs native programs** with the privileges of the current user.
The `subprocess` timeout bounds wall-clock time only. It is **not a sandbox**: a program can
read and write files, use the network, spawn processes (only the direct child process
group is killed on POSIX timeouts; Windows kills the direct child only), consume memory or
disk, and fill output (captured output is truncated after the run, not during it).

Only run sources you trust. For untrusted input use an OS-level sandbox (container, VM,
`nsjail`, a dedicated user with resource limits) around the whole tool.

Compiler invocation uses argument lists and never a shell, so source text and file names
cannot inject shell commands. Compiler flags supplied through a `--config` file (`extra_flags`) or a
`flags=` directive are still handed to the compiler verbatim (flags such as `-fplugin=` can
load code), so treat configuration files and test-case directives as trusted input too.

## Scope

* Educational compiler-verification framework built on an existing compiler; not a
  replacement for production validation suites (for example the LLVM test-suite, Csmith/
  YARPGen-scale random testing, or vendor conformance suites).
* It does **not** verify NVIDIA hardware, PTX, CUDA or proprietary NVIDIA compilers. No GPU
  backend is implemented.
* Output-only observation: no inspection of LLVM IR, assembly, or compiler internals.
* The generator uses a fixed set of templates; it is not a grammar-based program generator
  and cannot prove its programs are free of undefined behavior (it is designed to avoid
  it; the sanitizer integration test exercises generated programs under ASan/UBSan, but that
  checks only the sampled programs).
* The reducer is line-based and not compiler-aware.
* Differential testing on one compiler cannot detect bugs that affect all optimization
  levels identically.

## Platform notes

* Developed and run on Linux. macOS and Windows are supported by design (portable paths,
  `.exe` handling, Windows crash-status detection, no `-lm` on Windows) but were **not**
  exercised on Windows or macOS by the author of this repository snapshot; the CI workflow
  covers Linux and macOS runners.
* C++ builds need the C++ driver (`clang++`). It is derived from the C driver name
  (`clang` to `clang++`, `clang-17` to `clang++-17`, `gcc` to `g++`) or set with `--cxx-compiler`.
* The tool is compiler-agnostic in practice (flags used: `-std=`, `-O*`, `-o`, `-lm`,
  `-fsanitize=`), and was exercised in development with GCC because no Clang was available
  in that environment. Clang is the intended primary compiler.
* Sanitizers depend on the toolchain shipping the runtimes. `doctor` and `sanitize` report
  unsupported configurations and how to enable them.
* Reports contain at most 2000 characters of each captured stream; full output is in artifacts.
* Tests run sequentially; there is no parallel execution.
* Timing-sensitive programs and tests that print addresses are inherently unsuitable.
