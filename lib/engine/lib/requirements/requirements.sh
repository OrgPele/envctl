#!/usr/bin/env bash

# Requirement helpers (split into modules).

LIB_DIR="${LIB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# shellcheck source=/dev/null
source "$LIB_DIR/requirements_core.sh"
# shellcheck source=/dev/null
source "$LIB_DIR/requirements_supabase.sh"
# shellcheck source=/dev/null
source "$LIB_DIR/requirements_seed.sh"
