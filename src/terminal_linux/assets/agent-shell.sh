#!/usr/bin/env bash
# Clean interactive shell for the guest agent-terminal.
export TERM="${TERM:-xterm-256color}"
export LANG=C LC_ALL=C
if [[ -n "${TERMINAL_LINUX_GUEST_HOME:-}" ]]; then
  export HOME="$TERMINAL_LINUX_GUEST_HOME"
  cd "$HOME" || true
fi
export PS1='\[\e[38;5;114m\]agent\[\e[0m\] \[\e[38;5;75m\]\w\[\e[0m\] \$ '
clear
printf '\n'
printf '  \033[1mterminal-linux\033[0m · agent-terminal\n'
printf '  Guest shell for AI agents. Host desktop is not controlled.\n'
printf '\n'
printf '  %s\n' "$(uname -srm)"
printf '\n'
exec bash --noprofile --norc
