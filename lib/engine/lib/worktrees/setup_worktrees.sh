#!/usr/bin/env bash

# Helpers for setup-worktrees.sh.

setup_worktrees_print_usage() {
    cat <<'USAGE'
Unified Worktree Setup Script

Usage:
  ./setup-worktrees.sh --single <FEATURE_NAME> <ITERATION_NUMBER> [options]
  ./setup-worktrees.sh <FEATURE_NAME> <COUNT> [options]

Options:
  --skip-install        Skip backend/frontend dependency installs
  --backend-only        Configure backend only
  --frontend-only       Configure frontend only
  --existing            Reuse existing single worktree/branch instead of failing
  --recreate            Recreate existing single worktree/branch (destructive)
  --help, -h            Show this help
USAGE
}

setup_worktrees_init_config() {
    MODE="multi"
    POSITIONAL=()
    SKIP_INSTALL=false
    RUN_BACKEND_SETUP=true
    RUN_FRONTEND_SETUP=true
    REUSE_EXISTING=false
    RECREATE_EXISTING=false
    SHOW_HELP=false
}

setup_worktrees_parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --single)
                MODE="single"
                shift
                ;;
            --skip-install)
                SKIP_INSTALL=true
                shift
                ;;
            --backend-only)
                RUN_FRONTEND_SETUP=false
                shift
                ;;
            --frontend-only)
                RUN_BACKEND_SETUP=false
                shift
                ;;
            --existing)
                REUSE_EXISTING=true
                shift
                ;;
            --recreate)
                RECREATE_EXISTING=true
                shift
                ;;
            --help|-h|help)
                SHOW_HELP=true
                shift
                ;;
            --)
                shift
                break
                ;;
            *)
                POSITIONAL+=("$1")
                shift
                ;;
        esac
    done
    if [ $# -gt 0 ]; then
        POSITIONAL+=("$@")
    fi
}

setup_worktrees_validate_config() {
    if [ "$RUN_BACKEND_SETUP" = false ] && [ "$RUN_FRONTEND_SETUP" = false ]; then
        echo -e "${RED}Error: --backend-only and --frontend-only cannot both be set.${NC}"
        return 1
    fi
    if [ "$REUSE_EXISTING" = true ] && [ "$RECREATE_EXISTING" = true ]; then
        echo -e "${RED}Error: --existing and --recreate cannot both be set.${NC}"
        return 1
    fi
    return 0
}

setup_worktrees_print_port_config() {
    echo -e "${CYAN}Port Configuration:${NC}"
    echo -e "  Backend Base Port: ${BACKEND_PORT_BASE}"
    echo -e "  Frontend Base Port: ${FRONTEND_PORT_BASE}"
    echo -e "  DB Base Port: ${DB_PORT_BASE}"
    echo -e "  Redis Base Port: ${REDIS_PORT_BASE}"
    echo -e "  Port Spacing: ${PORT_SPACING}"
    echo ""
}

setup_worktrees_compute_ports() {
    local iteration=$1
    local offset=$(((iteration - 1) * PORT_SPACING))
    local backend_port=$((BACKEND_PORT_BASE + offset))
    local frontend_port=$((FRONTEND_PORT_BASE + offset))
    local db_port=$((DB_PORT_BASE + offset))
    local redis_port=$((REDIS_PORT_BASE + offset))

    backend_port=$(find_free_port "$backend_port")
    frontend_port=$(find_free_port "$frontend_port")
    db_port=$(find_free_port "$db_port")
    redis_port=$(find_free_port "$redis_port")

    printf '%s|%s|%s|%s\n' "$backend_port" "$frontend_port" "$db_port" "$redis_port"
}
