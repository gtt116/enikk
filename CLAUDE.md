# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Conventions

- **Imports at top of file.** All `import` statements must be placed at the top of the file, never inline or inside functions.
- **Import modules, not classes.** Always use `import module` rather than `from module import Class`. Access symbols via the module name as namespace (e.g. `capture.CaptureMethod`, not `from capture import CaptureMethod`).
- **No Co-Authored-By in commits.** Do not include `Co-Authored-By` trailer in git commit messages.
