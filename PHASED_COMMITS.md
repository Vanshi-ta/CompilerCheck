# CompilerCheck: phased commit plan

This project is currently provided as a complete snapshot. The phases below let you introduce the files in coherent groups so the Git history is easier to review. They reconstruct a staged history from the current snapshot; they are not a record of when the work was originally written. If you are asked about the process, describe it accurately.

## Recommended phases

1. **Initialize project structure** — package metadata, configuration, shared models, and error types.
2. **Add compiler execution** — compiler discovery/invocation and safe program execution with unit tests.
3. **Load test programs** — corpus loading, examples, smoke cases, and loader tests.
4. **Compare compiler behavior** — output comparison and sanitizer support with tests.
5. **Orchestrate runs and report results** — runner, artifacts, reporting, and tests.
6. **Add test generation and regression support** — generated cases, reduction, saved regressions, and tests.
7. **Expose the CLI and integration tests** — command-line interface, helpers, and real-compiler tests.
8. **Document and automate the project** — README, design/methodology/limitations docs, and GitHub Actions CI.

## Run the script

From the extracted `CompilerCheck` directory, after creating an empty Git repository and configuring your Git identity:

```bash
git init
git config user.name "Your Name"
git config user.email "you@example.com"
bash scripts/commit_phases.sh
```

If you already created a GitHub repository, add its remote before or after running the script. The script does **not** push automatically; review the commits first, then run `git push -u origin main` (or your branch name).

The script expects a clean repository with no existing commits and no staged changes. It stops on errors. Review each commit and run the tests locally before pushing. Compiler integration tests may require Clang/LLVM to be installed.
