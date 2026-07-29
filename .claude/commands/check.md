Run code quality checks on the enikk project. Execute these in order and report results:

1. **Lint + Types + HTML**: `lint.bat`
2. **Tests**: `test.bat`
3. **Build**: `.\build.bat` (produces `dist\enikk\enikk.exe`)

Summarize as a table:

| Check | Result | Details |
|-------|--------|---------|
| Lint/Types/HTML | ✅/❌ | from lint.bat output |
| Tests | ✅/❌ | X passed, Y failed, Z skipped |
| Build | ✅/❌ | exit code + path to `dist\enikk\enikk.exe` |

Then require the user to verify the built artifact: ask them to run
`dist\enikk\enikk.exe` and confirm the app launches and the main window
appears (and for startup-related changes, that the loading → dashboard
flow works). Do not mark the check fully green until the user confirms.
Report the user's verification result in the summary.

If any automated step fails, list errors with file path and line number.
If all automated steps pass and the user confirms the app runs, end with
"All checks passed ✅".
