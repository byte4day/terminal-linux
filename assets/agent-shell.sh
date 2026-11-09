#!/usr/bin/env bash
# Clean interactive shell for the guest agent-terminal.
export TERM="${TERM:-xterm-256color}"
export PS1='\[\e[38;5;114m\]agent\[\e[0m\] \[\e[38;5;75m\]\w\[\e[0m\] \$ '
clear
cat <<'EOF'

  terminal-linux · agent-terminal
  Type commands here. The host desktop is not controlled.

EOF
uname -srm
date
echo
exec bash --noprofile --norc
