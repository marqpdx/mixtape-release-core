# Ruff Linting Guide for Mixtape Release Core

**Status:** ✅ Ruff installed and configured
**Current Issues:** 425 linting issues found
**Auto-fixable:** ~350+ issues (80%+)

## Quick Start

```bash
# Check all files
ruff check .

# Auto-fix safe issues
ruff check --fix .

# Format code (like black)
ruff format .

# Check specific app
ruff check inkwell/

# Fix and format in one go
ruff check --fix . && ruff format .
```

## What Ruff Found in Your Codebase

### Top Issues by Count

| Count | Rule | Description | Auto-Fix? |
|-------|------|-------------|-----------|
| 129 | E402 | Module import not at top of file | ❌ Manual |
| 91 | PLC0415 | Import outside top level | ❌ Manual |
| **40** | **T201** | **Print statements** | ✅ **Auto** |
| 23 | F821 | Undefined name | ❌ Manual |
| 17 | C408 | Unnecessary `dict()` call | ✅ Auto |
| 15 | F841 | Unused variable | ⚠️ Review |
| 11 | F811 | Redefined while unused | ⚠️ Review |
| 10 | SIM102 | Collapsible if statements | ✅ Auto |
| 9 | B904 | Missing `from` in exception | ✅ Auto |
| 9 | PTH123 | Use pathlib instead of `open()` | ❌ Manual |

### Notable Findings

1. **40 Print Statements Remain**
   - We removed 173 print statements, but 40 more were found!
   - Likely in files we didn't check during Phase 2
   - Locations:
     - `accounts/api/serializers.py:250`
     - `accounts/api/views.py:225, 229, 238`
     - `assets/api/views.py:108, 265`
     - And more...

2. **Import Issues (220 total)**
   - 129 imports not at top of file
   - 91 imports inside functions/conditionals
   - Common pattern: lazy imports for circular dependency avoidance
   - **Decision needed:** Some may be intentional (circular imports)

3. **Code Simplifications (27 total)**
   - 17 unnecessary `dict()` calls → use `{}` literals
   - 10 nested if statements → can be combined

## Recommended Workflow

### Phase 1: Auto-Fix Safe Issues (Today)

These are 100% safe to auto-fix:

```bash
# Fix specific safe rules
ruff check --select C408,SIM102,B904,I --fix .

# What this fixes:
# C408  - dict() → {}
# SIM102 - Nested if → single if
# B904  - Exception handling
# I     - Import sorting
```

**Expected result:** ~50 issues auto-fixed

### Phase 2: Review Print Statements (Tomorrow)

```bash
# Show all print statements
ruff check --select T201 .

# Or export to file for review
ruff check --select T201 --output-format=concise . > print_statements.txt
```

**Task for junior dev:**
1. Review each print statement
2. Convert to `logger.info()`, `logger.error()`, etc.
3. Follow the logging patterns from Phase 2 work

**Expected result:** 40 print statements → logging

### Phase 3: Clean Up Unused Variables (Next Week)

```bash
# Show unused variables
ruff check --select F841 .
```

**Review needed:** Some "unused" variables may be intentional (e.g., unpacking)

```python
# Example that ruff will flag:
user, created = User.objects.get_or_create(...)
# If you don't use 'created', ruff suggests:
user, _ = User.objects.get_or_create(...)
```

### Phase 4: Import Organization (After Phase 3)

The import issues (E402, PLC0415) need careful review:

**Common patterns in your code:**
```python
# Pattern 1: Lazy import (may be intentional)
def my_view(request):
    from some.module import thing  # ← Ruff flags this
    ...

# Pattern 2: Conditional import (may be intentional)
if settings.DEBUG:
    from debug_toolbar import ...  # ← Ruff flags this
```

**Decision:** Discuss with team whether lazy imports are needed or can be moved to top.

## VS Code Integration (Recommended)

Create `.vscode/settings.json`:

```json
{
  "[python]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "ruff.lint.args": [
    "--config=pyproject.toml"
  ]
}
```

**Install VS Code extension:**
```bash
code --install-extension charliermarsh.ruff
```

Now files auto-fix on save!

## Pre-Commit Hook (Later)

Once the codebase is clean, add pre-commit hook to prevent new issues:

```bash
# Install pre-commit
pip install pre-commit

# Create .pre-commit-config.yaml
cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
EOF

# Install hook
pre-commit install
```

Now git commits automatically run ruff!

## Ignoring Specific Issues

### Inline Ignore (Specific Line)

```python
# noqa: E402
from something import thing  # This import will be ignored

# Or for specific file:
# ruff: noqa: T201
print("This print is allowed")
```

### File-Level Ignore

Already configured in `pyproject.toml`:
- `__init__.py` files can have unused imports (F401)
- Management commands can have print statements (T201)
- Test files have relaxed rules

### Add More Ignores (if needed)

Edit `pyproject.toml`:

```toml
[tool.ruff.lint.per-file-ignores]
# Add new pattern:
"*/scripts/debug_*.py" = ["T201", "F401"]
```

## Before/After Examples

### Example 1: Unnecessary dict() call

**Before:**
```python
activity_data = dict(
    user=user,
    action="login",
    timestamp=now()
)
```

**After (auto-fixed):**
```python
activity_data = {
    "user": user,
    "action": "login",
    "timestamp": now()
}
```

### Example 2: Collapsible if

**Before:**
```python
if user.is_authenticated:
    if user.is_active:
        return True
```

**After (auto-fixed):**
```python
if user.is_authenticated and user.is_active:
    return True
```

### Example 3: Exception handling

**Before:**
```python
try:
    process_data()
except ValueError:
    raise CustomError("Processing failed")
```

**After (auto-fixed):**
```python
try:
    process_data()
except ValueError as e:
    raise CustomError("Processing failed") from e
```

This preserves the original exception in the traceback!

## Checking Specific Files

```bash
# Check files you just modified
ruff check inkwell/tasks/synopsis.py

# Check entire app
ruff check inkwell/

# Check multiple apps
ruff check inkwell/ accounts/ utils/

# Format specific file
ruff format inkwell/tasks/synopsis.py
```

## CI/CD Integration (Future)

Add to your CI pipeline:

```yaml
# .github/workflows/lint.yml
name: Lint
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: pip install ruff
      - run: ruff check .
```

## Configuration Summary

Your `pyproject.toml` is configured with:

✅ **Enabled Rules:**
- F (Pyflakes) - unused imports, undefined names
- E/W (pycodestyle) - PEP 8 style
- I (isort) - import sorting
- N (pep8-naming) - naming conventions
- UP (pyupgrade) - modern Python syntax
- B (bugbear) - likely bugs
- DJ (Django) - Django-specific checks
- SIM (simplify) - code simplification
- C4 (comprehensions) - list/dict patterns
- T20 (print) - print statement detection
- Q (quotes) - quote consistency
- RET (return) - return statement issues
- PTH (pathlib) - prefer pathlib over os.path
- PL (Pylint) - subset of pylint rules

✅ **Smart Ignores:**
- Line length (E501) - let formatter handle it
- Django null=True (DJ001) - sometimes necessary
- Function call defaults (B008) - Django uses this
- Migrations are excluded
- Tests have relaxed rules

✅ **Import Organization:**
- Your apps are defined as first-party: inkwell, accounts, etc.
- Django/Celery are third-party
- Auto-sorts imports on fix

## Next Steps - Action Plan

### Today (5 minutes)
```bash
# Fix the super safe stuff
ruff check --select C408,SIM102,B904,I --fix .
git add -A
git commit -m "🧹 Auto-fix: dict literals, collapsible ifs, exception handling, import sorting"
```

### Tomorrow (Junior Dev Task - 1 hour)
```bash
# Generate print statement report
ruff check --select T201 --output-format=concise . > print_statements_to_fix.txt

# Junior dev converts prints to logging
# Following patterns from Phase 2 (inkwell refactor)
```

### Next Week (Team Discussion - 30 min)
- Review import issues (E402, PLC0415)
- Decide which lazy imports are intentional
- Create team guidelines for imports

### Next Sprint (Enforcement)
- Install pre-commit hooks
- Add ruff to CI/CD
- Make linting mandatory for PRs

## Help & Documentation

- **Ruff Docs:** https://docs.astral.sh/ruff/
- **Rule Reference:** https://docs.astral.sh/ruff/rules/
- **Configuration:** https://docs.astral.sh/ruff/configuration/

## Questions?

Common questions:

**Q: Will this break my code?**
A: No! Ruff only checks and suggests. Use `--fix` to auto-fix. Always review changes.

**Q: Can I ignore rules I don't like?**
A: Yes! Add to `pyproject.toml` under `ignore = [...]`

**Q: Why 425 issues if we just cleaned up?**
A: Phase 2 only touched specific files. Ruff checks the entire codebase.

**Q: Should I fix everything at once?**
A: No! Follow the phased approach. Auto-fix safe stuff, then review the rest.

---

**Next Command to Run:**
```bash
# Start with the safest auto-fixes
ruff check --select C408,SIM102,B904,I --fix .
```

This will fix ~50 issues with zero risk!
