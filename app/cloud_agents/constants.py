"""Provider identifiers shared by Atrium and tenant runtime integrations."""

PROVIDER_ANTHROPIC_CLAUDE_CODE = "anthropic-claude-code"
PROVIDER_ANTHROPIC_API = "anthropic-api"
PROVIDER_OPENAI_CODEX = "openai-codex"

PROVIDER_CHOICES = [
    (PROVIDER_ANTHROPIC_API, "Anthropic API"),
    (PROVIDER_ANTHROPIC_CLAUDE_CODE, "Claude Code"),
    (PROVIDER_OPENAI_CODEX, "OpenAI Codex"),
]
