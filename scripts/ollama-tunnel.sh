#!/usr/bin/env bash
# Keep the model on the homelab while application code and sample data stay local.
set -euo pipefail
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  echo "Usage: bash scripts/ollama-tunnel.sh <ssh-host-alias-or-user@host>"
  echo "Keep this terminal open; Ctrl-C closes the tunnel."
  exit 0
fi
if [[ $# -ne 1 || -z "$1" || "$1" == -* ]]; then
  echo "Usage: bash scripts/ollama-tunnel.sh <ssh-host-alias-or-user@host>" >&2
  exit 2
fi
echo "Forwarding local 127.0.0.1:11434 to homelab Ollama."
echo "If port 11434 is busy, stop the existing local Ollama/tunnel first."
exec ssh -N -T \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:11434:127.0.0.1:11434 "$1"
