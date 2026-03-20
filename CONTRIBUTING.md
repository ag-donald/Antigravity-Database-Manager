# Contributing to Antigravity IDE Database Management Hub

Thank you for your interest in contributing! This project exists to help the community work around a known bug in the Google Antigravity IDE. All contributions are welcome.

## How to Contribute

### Reporting Bugs

1. Check the [existing issues](https://github.com/agmercium/antigravity-recovery/issues) to see if your bug has already been reported.
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
   python -m py_compile antigravity_recover.py
   python -c "from src.recovery import main"  # validates all src/ imports
   ```
5. Test on your platform (Windows, macOS, or Linux)
6. Commit your changes: `git commit -m "Add: description of change"`
7. Push to your fork: `git push origin feature/your-feature`
8. Open a Pull Request

### Code Standards

- **Python 3.7+ compatibility**: Use `from __future__ import annotations` for modern type hints
- **Zero external dependencies**: Only standard library imports
- **Use the `Logger` class**: All console output must go through the unified `Logger` system
- **Error handling**: All I/O operations must be wrapped in `try/except` with descriptive error messages
- **Docstrings**: All public classes and methods must have docstrings
- **Module placement**: New features go in the appropriate `src/` module — see Project Structure below

### Project Structure

```
antigravity_recover.py   ← Entry point
src/
├── core/                ← Domain logic, models, and robust database operations
│   ├── constants.py
│   ├── models.py
│   ├── protobuf.py
│   ├── environment.py
│   ├── artifacts.py
│   ├── db_scanner.py
│   ├── db_operations.py
│   ├── diagnostic.py
│   ├── storage_manager.py
│   └── lifecycle.py
├── ui_tui/              ← Full-screen Terminal UI (MVU Architecture)
│   ├── app.py
│   ├── engine.py
│   ├── widgets.py
│   └── views.py
└── ui_headless/         ← Command-line Interface and Interactive Prompts
    ├── cli_parser.py
    ├── controller.py
    └── logger.py
```

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
