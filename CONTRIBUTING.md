# Contributing to Antigravity IDE Database Management Hub

> **Disclaimer:** This is an **unofficial** community workaround project. It is **not** affiliated
> with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team.
> All product names, logos, and brands are property of their respective owners.

Thank you for your interest in contributing! This project exists to help the community work around a known bug in the Google Antigravity IDE. All contributions are welcome.

## How to Contribute

### Reporting Bugs

1. Check the [existing issues](https://github.com/ag-donald/Antigravity-Database-Manager/issues) to see if your bug has already been reported.
2. If not, open a new issue with:
   - Your operating system and Python version
   - Antigravity IDE version
   - Steps to reproduce the issue
   - Expected vs. actual behavior
   - Any error output from the script

### Suggesting Improvements

Open an issue with the `enhancement` label describing:
- What you'd like to see improved
- Why it would help others
- Any implementation ideas you have

### Submitting Code

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Ensure all modules pass syntax validation:
   ```bash
   python -m py_compile antigravity_database_manager.py
   python -c "from src.core.lifecycle import ApplicationContext"  # validates all src/ imports
   ```
5. Run the full test suite:
   ```bash
   python -m unittest discover -s tests -v
   ```
6. Test on your platform (Windows, macOS, or Linux)
7. Commit your changes: `git commit -m "Add: description of change"`
8. Push to your fork: `git push origin feature/your-feature`
9. Open a Pull Request

### Code Standards

- **Python 3.10+ compatibility**: Use `from __future__ import annotations` for modern type hints
- **Zero external dependencies**: Only standard library imports
- **Use the `Logger` class**: All console output must go through the unified `Logger` system
- **Error handling**: All I/O operations must be wrapped in `try/except` with descriptive error messages
- **Docstrings**: All public classes and methods must have docstrings
- **Module placement**: New features go in the appropriate `src/` module — see Project Structure below

### Project Structure

```
antigravity_database_manager.py   ← Entry point
build_release.py                  ← Builds the cross-platform .pyz zipapp
fix_workspace_uri.py              ← Thin wrapper for the fix-uris command (Bug #12)
src/
├── core/                         ← Domain logic, models, database operations
│   ├── constants.py
│   ├── models.py
│   ├── protobuf.py
│   ├── environment.py
│   ├── artifacts.py
│   ├── db_scanner.py
│   ├── db_operations.py
│   ├── diagnostic.py
│   ├── storage_manager.py
│   ├── uri_fix.py
│   └── lifecycle.py
├── ui_tui/                       ← Full-screen terminal UI
│   ├── capabilities.py           ← Terminal capability detection
│   ├── theme/                    ← Semantic colors, styles, borders, icons
│   ├── core.py                   ← ANSI-aware text utilities, Component base
│   ├── components.py             ← Reusable UI components
│   ├── animation.py              ← Screen-transition easing
│   ├── engine.py                 ← Double-buffered terminal I/O
│   ├── app.py                    ← Application event loop
│   └── views.py                  ← Eight screens (home, browse, recovery, merge, …)
└── ui_headless/                  ← CLI parser and interactive menus
    ├── cli_parser.py
    ├── controller.py
    └── logger.py
tests/
├── test_core.py                  ← Core logic tests (91 tests)
└── test_tui.py                   ← TUI framework tests (50 tests)
```

See [README.md](README.md) for usage, recovery behavior, and CLI reference.

### Commit Message Format

```
Add: new feature description
Fix: bug description
Docs: documentation change
Refactor: code improvement without behavior change
```

## Code of Conduct

Be respectful, constructive, and inclusive. This is a community project built to help developers. Harassment, discrimination, or toxic behavior of any kind will not be tolerated.

## Questions?

Open a discussion issue or reach out via the repository's issue tracker.
