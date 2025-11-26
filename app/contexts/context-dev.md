Where future devs will look

Business rule lives in: earthlab/services.py (single function)

Auto behavior lives in: earthlab/signals.py and is flagged by EARTHLAB_AUTO_CREATE_DEFAULT_CHAT

Vocabulary/data lives in: ContextDefinition seed migration

Manual re-run lives in: Admin action (and optional DRF endpoint)

This makes the rule visible in code, admin, API, and tests—and easy to switch off per environment.