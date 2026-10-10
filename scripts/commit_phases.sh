#!/usr/bin/env bash
set -euo pipefail

# Stage the supplied snapshot in reviewable groups and create one commit per phase.
# Run from the CompilerCheck repository root in a clean, newly initialized repo.

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: run this script from inside the CompilerCheck Git repository." >&2
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: working tree or index has changes. Use a clean, newly initialized repository." >&2
  exit 1
fi
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "Error: this script is intended for a repository with no commits yet." >&2
  exit 1
fi

commit_phase() {
  local message="$1"
  shift
  git add -- "$@"
  if git diff --cached --quiet; then
    echo "Error: no files staged for phase: $message" >&2
    exit 1
  fi
  git commit -m "$message"
}

echo "Phase 1/8: project structure and core types"
commit_phase "chore: initialize CompilerCheck project structure" \
  .gitignore LICENSE pyproject.toml requirements-dev.txt PHASED_COMMITS.md scripts/commit_phases.sh \
  compilercheck/__init__.py compilercheck/errors.py compilercheck/models.py compilercheck/config.py \
  tests/__init__.py tests/unit/__init__.py tests/unit/test_config.py

echo "Phase 2/8: compiler and process execution"
commit_phase "feat: add compiler invocation and safe program execution" \
  compilercheck/compiler.py compilercheck/executor.py \
  tests/unit/test_compiler.py tests/unit/test_executor.py

echo "Phase 3/8: test corpus and loader"
commit_phase "feat: load compiler test cases and add smoke corpus" \
  compilercheck/loader.py \
  examples/c examples/cpp testcases/smoke testcases/educational_undefined_behavior \
  tests/unit/test_loader.py

echo "Phase 4/8: output comparison and sanitizers"
commit_phase "feat: compare program outputs and add sanitizer support" \
  compilercheck/comparator.py compilercheck/sanitizers.py \
  tests/unit/test_comparator.py tests/unit/test_sanitizers.py

echo "Phase 5/8: runner and result artifacts"
commit_phase "feat: orchestrate verification runs and report results" \
  compilercheck/runner.py compilercheck/artifacts.py compilercheck/reporter.py \
  tests/unit/test_runner.py tests/unit/test_artifacts.py tests/unit/test_reporter.py

echo "Phase 6/8: generation, reduction, and regressions"
commit_phase "feat: add generated tests, case reduction, and regression storage" \
  compilercheck/generator.py compilercheck/reducer.py compilercheck/regression.py \
  regressions tests/unit/test_generator.py tests/unit/test_reducer.py tests/unit/test_regression.py

echo "Phase 7/8: CLI and integration coverage"
commit_phase "feat: expose verification CLI and add integration tests" \
  compilercheck/cli.py compilercheck/__main__.py \
  tests/helpers.py tests/unit/test_cli.py tests/integration

echo "Phase 8/8: documentation and CI"
commit_phase "docs: document architecture and add CI workflow" \
  README.md docs .github/workflows/ci.yml

echo "\nDone. Review the history with: git log --oneline --decorate"
echo "Run tests, then push manually when satisfied."
