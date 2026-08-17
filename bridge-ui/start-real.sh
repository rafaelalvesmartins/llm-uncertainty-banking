#!/bin/bash
# ============================================
# start-real.sh — Bridge UI against the REAL local Ollama model
# ============================================
# Thin wrapper over start-demo.sh that opts out of the demo-safe FakeBackend and
# points the pipeline at a real local LLM (Ollama). Because start-demo.sh runs the
# backend in a restart loop and inherits this environment, the backend STAYS in
# real mode across auto-restarts — use this instead of start-demo.sh when you want
# the demo to call a real model, so the two don't flip the backend between
# fake/real ("port war").
#
# Usage (Git Bash on Windows or any *nix shell):
#   ./start-real.sh                      # default model llama3.1:8b
#   OLLAMA_MODEL=qwen3-coder:30b ./start-real.sh   # pick another loaded model
#
# Prereqs: Ollama running locally with the chosen model pulled
#   (ollama list  → must show OLLAMA_MODEL). Otherwise the backend falls back to
#   FakeBackend (or fails if BRIDGE_USE_REAL_LLM=required).

export BRIDGE_DEMO_SAFE=off          # opt out of the master fake-only switch
export BRIDGE_USE_REAL_LLM=auto      # probe Ollama at startup; use it if the model is loaded
export OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

echo "Bridge UI — REAL LLM mode (Ollama model: $OLLAMA_MODEL @ $OLLAMA_URL)"
echo "  (set OLLAMA_MODEL=... to choose another; Ctrl+C stops both halves)"
exec "$(dirname "$0")/start-demo.sh"
