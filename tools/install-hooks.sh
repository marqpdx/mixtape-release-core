#!/bin/bash
# install-hooks.sh — link core's tracked hooks (tools/hooks/) into this clone.
# Run once per clone (laptop, Cass, Crossroads). Safe to re-run. Leaves other hooks alone.
set -e
CORE="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
HOOKS="$(git -C "$CORE" config --get core.hooksPath || echo "$(git -C "$CORE" rev-parse --git-path hooks)")"
case "$HOOKS" in /*) ;; *) HOOKS="$CORE/$HOOKS" ;; esac
mkdir -p "$HOOKS"
for hook in "$CORE"/tools/hooks/*; do
  name="$(basename "$hook")"
  target="$HOOKS/$name"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "skip $name: $target exists and isn't a link (not overwritten)"; continue
  fi
  ln -sf "$hook" "$target" && echo "linked $name -> $target"
done
