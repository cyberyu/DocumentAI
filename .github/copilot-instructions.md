# Copilot Instructions

## Terminal / Command Execution

- **Never redirect command output** (`> file`, `2>&1`, `&> file`, `tee`, etc.) unless the user explicitly asks for it.
- **Never run benchmarks or long-running scripts in the background** (`&`) unless the user explicitly asks.
- Always run commands **in the foreground** so output is visible in the terminal.
- When activating a conda environment, use `conda activate <env>` on its own line first, then run the Python command on a separate line — do **not** use `conda run -n <env> python3 ...` (it suppresses debug output).
