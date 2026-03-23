#!/usr/bin/env bash

set -euo pipefail

MODE="preview"
ACTION="trash"
SHOW_ALL=0
TRASH_DIR="${HOME}/.Trash"

usage() {
  cat <<'EOF'
Usage:
  scripts/storage_cleanup_candidates.sh
  scripts/storage_cleanup_candidates.sh --execute
  scripts/storage_cleanup_candidates.sh --execute --delete
  scripts/storage_cleanup_candidates.sh --show-all

Behavior:
  - Default mode is a dry run.
  - Default execute action is to move items to ~/.Trash.
  - Use --delete to permanently remove items instead of moving them to Trash.
  - Use --show-all to also print missing paths.

Why this script exists:
  - The candidate lists are meant to be edited directly in this file.
  - Safer items are enabled by default.
  - Riskier items are listed in commented sections near the bottom.

Important:
  - Read and edit the path lists before running with --execute.
  - This script does not attempt Docker cleanup. Docker needs separate review.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute)
      MODE="execute"
      ;;
    --delete)
      ACTION="delete"
      ;;
    --show-all)
      SHOW_ALL=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

human_size() {
  local path="$1"
  du -sh "$path" 2>/dev/null | awk '{print $1}'
}

delete_path() {
  local path="$1"
  if [[ "$ACTION" == "trash" ]]; then
    mkdir -p "$TRASH_DIR"
    local base target
    base="$(basename "$path")"
    target="${TRASH_DIR}/${base}"
    if [[ -e "$target" ]]; then
      target="${TRASH_DIR}/${base}.$(date +%Y%m%d-%H%M%S)"
    fi
    mv "$path" "$target"
  else
    rm -rf "$path"
  fi
}

process_group() {
  local label="$1"
  shift
  local -a items=("$@")
  local found=0

  printf '\n== %s ==\n' "$label"

  for path in "${items[@]}"; do
    if [[ -e "$path" ]]; then
      found=1
      local size
      size="$(human_size "$path")"
      if [[ "$MODE" == "preview" ]]; then
        printf '[preview] %8s  %s\n' "${size:-?}" "$path"
      else
        printf '[remove ] %8s  %s\n' "${size:-?}" "$path"
        delete_path "$path"
      fi
    elif [[ "$SHOW_ALL" -eq 1 ]]; then
      printf '[missing]          %s\n' "$path"
    fi
  done

  if [[ "$found" -eq 0 && "$SHOW_ALL" -eq 0 ]]; then
    printf '[none found]\n'
  fi
}

# Edit these lists directly.
# Keep only the paths you actually want this script to touch.

# High-confidence duplicate installers and backup bundles.
SAFE_DUPLICATES=(
  "$HOME/Applications/OmniRoute 2.3.13.backup.app"
  "$HOME/Downloads/Antigravity (1).dmg"
  "$HOME/Downloads/Codex (1).dmg"
  "$HOME/Downloads/Codex (2).dmg"
  "$HOME/Downloads/Notion-7.8.0-arm64 (1).dmg"
)

# Old installers and extracted installer leftovers.
SAFE_INSTALLERS_AND_EXTRACTS=(
  "$HOME/Downloads/Docker.dmg"
  "$HOME/Downloads/comet_latest.dmg"
  "$HOME/Downloads/Claude.dmg"
  "$HOME/Downloads/kiro-ide-0.10.32-stable-darwin-arm64.dmg"
  "$HOME/Downloads/OmniRoute-2.5.4-arm64.dmg"
  "$HOME/Downloads/OmniRoute-2.5.9-arm64.dmg"
  "$HOME/Downloads/OmniRoute-2.6.10-arm64.dmg"
  "$HOME/Downloads/ProtonVPN_mac_v6.4.0.dmg"
  "$HOME/Downloads/Kap-3.6.0-arm64.dmg"
  "$HOME/Downloads/Stremio_arm64.dmg"
  "$HOME/Downloads/OpenCode Desktop.dmg"
  "$HOME/Downloads/Windscribe_2.16.14_universal.dmg"
  "$HOME/Downloads/Zoom.pkg"
  "$HOME/Downloads/T3-Code-0.0.11-arm64.zip"
  "$HOME/Downloads/T3-Code-0.0.11-arm64"
  "$HOME/Downloads/logioptionsplus_installer.app"
  "$HOME/Downloads/platform-tools-mac.zip"
)

# Dated log directories from old runs.
SAFE_OLD_LOGS=(
  "$HOME/projects/supportopia/logs/run_20260125_094949"
  "$HOME/projects/supportopia/logs/run_20260126_103941"
  "$HOME/projects/supportopia/logs/run_20260215_113918"
  "$HOME/projects/supportopia/logs/run_20260122_155152"
  "$HOME/projects/supportopia/logs/run_20260122_202704"
  "$HOME/projects/supportopia/logs/run_20260119_191136"
)

# Regenerable caches.
SAFE_CACHES=(
  "$HOME/.npm/_cacache"
  "$HOME/.npm/_npx/47ababa9653307a4"
  "$HOME/.npm/_npx/7e8097cdcf4185b5"
  "$HOME/.cache/puppeteer"
  "$HOME/Library/Caches/ms-playwright"
  "$HOME/Library/Caches/Google"
  "$HOME/Library/Caches/Comet"
  "$HOME/Library/Caches/pip"
  "$HOME/Library/Caches/go-build"
  "$HOME/Library/Caches/net.whatsapp.WhatsApp/org.sparkle-project.Sparkle"
  "$HOME/Library/Caches/com.todesktop.230313mzl4w4u92.ShipIt/update.smtxLpE"
  "$HOME/Library/Caches/com.todesktop.230313mzl4w4u92.ShipIt/update.TTajZXa"
  "$HOME/.bun/install/cache"
)

# Generated local build output and environments.
SAFE_GENERATED_OUTPUT=(
  "$HOME/projects/claudia/src-tauri/target"
  "$HOME/projects/opencode/node_modules"
  "$HOME/projects/remotion-videos/example/node_modules"
  "$HOME/projects/supportopia/venv"
  "$HOME/projects/supportopia/backend/venv"
  "$HOME/projects/supportopia/frontend/node_modules"
  "$HOME/projects/supportopia/.mypy_cache"
  "$HOME/projects/supportopia/backend/.mypy_cache"
)

# Review carefully before enabling these.
# They are likely stale, but deleting them is more opinionated.
OPTIONAL_REVIEW_ONLY=(
  "$HOME/Downloads/flasher"
  "$HOME/Downloads/Super Flasher Global 602"
  "$HOME/Downloads/Super Flasher Global 703"
  "$HOME/Downloads/SuperHybrid_DerpFest-v16"
  "$HOME/fix_oneplus"
  "$HOME/projects/claudia/trees-commands"
  "$HOME/projects/old/supportopia/trees"
  "$HOME/Library/Application Support/kiro-cli/cli-checkouts/0e3ef79d-fe71-4aff-af97-e61e489bd817/objects/pack/tmp_pack_VM2lro"
)

# Large consumers that are intentionally not touched by this script.
# These are shown so you can see what is expensive but excluded because it
# looks like active app data, source repos, browser profiles, or system state.
PROTECTED_BIG_CONSUMERS=(
  "$HOME/Library/Containers/com.docker.docker"
  "$HOME/Library/Application Support/Google"
  "$HOME/Library/Application Support/Google/Chrome/Profile 2"
  "$HOME/Library/Application Support/Code"
  "$HOME/Library/Application Support/stremio-server"
  "$HOME/projects/claudia"
  "$HOME/projects/supportopia"
  "$HOME/projects/current/envctl"
  "$HOME/projects/opencode"
  "$HOME/projects/OmniRoute"
  "$HOME/.rustup"
  "$HOME/go"
  "/private/var/vm/sleepimage"
  "/Applications"
)

printf 'Mode: %s\n' "$MODE"
printf 'Action on execute: %s\n' "$ACTION"
printf 'Tip: edit the arrays near the top of this script before using --execute.\n'
printf 'This script shows both deletion candidates and intentionally protected big consumers.\n'

process_group "Safe Duplicates" "${SAFE_DUPLICATES[@]}"
process_group "Safe Installers And Extracts" "${SAFE_INSTALLERS_AND_EXTRACTS[@]}"
process_group "Safe Old Logs" "${SAFE_OLD_LOGS[@]}"
process_group "Safe Caches" "${SAFE_CACHES[@]}"
process_group "Safe Generated Output" "${SAFE_GENERATED_OUTPUT[@]}"

printf '\n== Optional Review Only ==\n'
printf 'These are intentionally not removed by the script.\n'
for path in "${OPTIONAL_REVIEW_ONLY[@]}"; do
  if [[ -e "$path" ]]; then
    printf '[review ] %8s  %s\n' "$(human_size "$path")" "$path"
  elif [[ "$SHOW_ALL" -eq 1 ]]; then
    printf '[missing]          %s\n' "$path"
  fi
done

printf '\n== Protected Big Consumers ==\n'
printf 'These consume substantial space but are intentionally excluded from deletion.\n'
for path in "${PROTECTED_BIG_CONSUMERS[@]}"; do
  if [[ -e "$path" ]]; then
    printf '[keep   ] %8s  %s\n' "$(human_size "$path")" "$path"
  elif [[ "$SHOW_ALL" -eq 1 ]]; then
    printf '[missing]          %s\n' "$path"
  fi
done

if [[ "$MODE" == "preview" ]]; then
  printf '\nDry run only. Re-run with --execute to move listed items to ~/.Trash.\n'
  if [[ "$ACTION" == "delete" ]]; then
    printf 'If you also pass --delete with --execute, removal will be permanent.\n'
  fi
else
  if [[ "$ACTION" == "trash" ]]; then
    printf '\nSelected items were moved to %s.\n' "$TRASH_DIR"
  else
    printf '\nSelected items were permanently removed.\n'
  fi
fi
