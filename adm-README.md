# adm-README — Admin & Management Command Reference

This directory contains two admin reference files maintained alongside the codebase:

- **`adm-management-commands.md`** — catalog of all Django management commands across the `mixtape-release-core` monolith. Updated whenever commands are added, changed, or removed.

## How to use

All commands run from `mixtape-release-core/app/` with the virtual environment active:

```
cd app
python manage.py <command_name> [options]
```

## Keeping this up to date

Update `adm-management-commands.md` when:
- A new management command is added to any app
- An existing command gains or loses options
- A one-off command is retired (mark it with a **[RETIRED]** note rather than deleting)

The catalog is organized by app. Each entry includes the command name, a one-line purpose, and its options.
