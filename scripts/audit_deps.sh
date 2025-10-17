#!/usr/bin/env bash
set -euo pipefail

STAMP=${1:-$(date +%Y%m%d)}
OUT_DIR="docs/audits"
mkdir -p "$OUT_DIR"

run_or_note() {
  local cmd="$1"
  local outfile="$2"
  echo "==> Running $cmd" | tee "$outfile"
  if command -v ${cmd%% *} >/dev/null 2>&1; then
    if ${cmd} >>"$outfile" 2>&1; then
      echo "[ok] $cmd" | tee -a "$outfile"
    else
      status=$?
      echo "[error] $cmd exited with status $status" | tee -a "$outfile"
    fi
  else
    echo "[missing] ${cmd%% *} no está instalado en el entorno" | tee -a "$outfile"
  fi
}

run_or_note "pip-audit" "$OUT_DIR/${STAMP}-pip-audit.txt"
run_or_note "safety check" "$OUT_DIR/${STAMP}-safety.txt"
run_or_note "deptry ." "$OUT_DIR/${STAMP}-deptry.txt"
