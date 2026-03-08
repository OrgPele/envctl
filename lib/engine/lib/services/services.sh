#!/usr/bin/env bash

# Service and process helpers (split into modules).

LIB_DIR="${LIB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# shellcheck source=/dev/null
source "$LIB_DIR/services_registry.sh"
# shellcheck source=/dev/null
source "$LIB_DIR/services_worktrees.sh"
# shellcheck source=/dev/null
source "$LIB_DIR/services_logs.sh"
# shellcheck source=/dev/null
source "$LIB_DIR/services_lifecycle.sh"
