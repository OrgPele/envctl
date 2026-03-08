#!/usr/bin/env bash

# CLI parsing helpers for run.sh.

run_all_trees_cli_print_usage() {
    cat <<'USAGE'
Development Server Runner

Usage:
  ./run.sh [command] [options]

Commands:
  plan                         Create worktrees from planning selection and run with parallel tree startup
  sequential-plan              Create worktrees from planning selection and run one-by-one (sequential startup)
  parallel-plan                Alias for plan
  dashboard                    Show runtime dashboard (services + health + run hints) and exit
  config                       Open the local startup configuration wizard
  delete-worktree              Interactive worktree cleanup (delete one/all)
  blast-worktree               Alias for delete-worktree
  stop                         Stop specified projects
  stop-all                     Stop all projects
  blast-all                    Aggressively kill all ecosystem processes and Docker containers OS-wide
  restart                      Restart explicitly targeted projects/services (implies --skip-startup)
  test, tests                  Run tests against targets (implies --skip-startup)
  logs                         Tail logs for targets (implies --skip-startup)
  health                       Check health of running services (implies --skip-startup)
  analyze                      Analyze changes for targets (implies --skip-startup)
  migrate                      Run migrations for targets (implies --skip-startup)
  pr, prs                      Create PRs for targets (implies --skip-startup)
  commit                       Commit targeted project directories (implies --skip-startup)
  errors                       Show explicit error diagnostics (implies --skip-startup)
  show-config                  Print effective local startup config
  show-state                   Print latest saved runtime state
  explain-startup              Explain startup selection/resume behavior without starting services
  debug-pack                   Python-runtime only debug bundle pack command (not available in shell fallback)

Options:
  trees=true, --tree, --trees Run all trees
  trees=false                  Run main project only
  main=true, --main            Run main project only
  ENVCTL_DEFAULT_MODE=main|trees  Default startup mode when no mode flag is passed (default: main)
  fresh=true                   Force fresh dependency install
  --headless, --batch, -b      Non-interactive mode (--headless preferred)
  --json                       Emit machine-readable JSON for supported inspection commands
  --stdin-json                 Read JSON payload from stdin (config command)
  --resume                     Resume previous session
  --no-resume                  Disable auto-resume
  --docker                     Build and run via Docker Compose
  --stop-docker-on-exit        Stop Docker if this script started it (alias: --docker-temp)
  --force, -f                  Force kill processes on default ports
  --setup-worktrees <FEATURE> <COUNT>
  --setup-worktree <FEATURE> <ITER>
  --reuse-existing-worktree    Reuse existing single worktree if branch/path already exist (alias: --setup-worktree-existing)
  --recreate-existing-worktree Recreate existing single worktree (destructive; alias: --setup-worktree-recreate)
  --include-existing-worktrees <a,b>  Include additional existing worktree iterations when using setup flags (alias: --setup-include-worktrees)
  --plan, --plan-selection [SELECTION]  Create worktrees from planning selection with parallel tree startup (alias: --planning-envs)
  --sequential-plan [SELECTION] Create worktrees from planning selection with one-by-one startup
  --parallel-plan [SELECTION]  Alias for --plan
  --planning-prs [SELECTION]
  --keep-plan                 Keep planning files in place (do not move to Done)
  ENVCTL_PLANNING_DIR=<path>  Planning root path (default: docs/planning; relative to repo root or absolute)
  --seed-requirements-from-base    Seed per-tree DB/Redis from base (alias: --copy-db-storage)
  --no-seed-requirements-from-base Disable per-tree DB/Redis seeding (alias: --no-copy-db-storage)
  --command <cmd>              Run a single command non-interactively
  --action <cmd>               Alias for --command
  --doctor                      Run diagnostics (ports, locks, states, orphans) and exit
  --dashboard                   Show runtime dashboard and exit
  --config                      Open the local startup configuration wizard
  --delete-worktree             Interactive worktree cleanup (alias for delete-worktree command)
  --blast-worktree              Alias for delete-worktree command
  --interactive                Keep interactive command loop for dashboard command
  --project <name>             Target a project (repeatable; trees startup/resume filter)
  --projects <a,b>             Target multiple projects (trees startup/resume filter)
  --service <name>             Target a service
  --all                        Target all services/projects
  --untested                   Target untested projects (tests only)
  --pr-base <branch>           Base branch for PR creation
  --commit-message <msg>       Commit message for non-interactive commits
  --commit-message-file <path> Commit message file for non-interactive commits
  --stop-all-remove-volumes    Remove volumes for stop-all
  --blast-keep-worktree-volumes Keep worktree Docker volumes during blast-all (no prompt)
  --blast-remove-main-volumes  Remove main project Docker volumes during blast-all (no prompt)
  --blast-keep-main-volumes    Keep main project Docker volumes during blast-all (no prompt)
  --logs-tail <n>              Tail last N lines for logs (default 200)
  --logs-follow                Follow logs (use with --logs-duration)
  --logs-duration <sec>        Follow logs duration in seconds
  --logs-no-color              Disable colored log prefixes
  --skip-startup               Skip startup, run command against saved state (alias: --command-only)
  --load-state                 Load last state before running command (alias: --command-resume)
  --list-commands              Print supported commands and exit
  --list-targets               Print available targets and exit
  --list-trees                 Print available tree targets and exit
  --set KEY=VALUE              Apply config value in headless config mode (repeatable)
  --analyze-mode <single|grouped>  Analysis mode for analyze command
  --fast                       Enable fast startup caches
  --refresh-cache              Force full scan and refresh fast caches
  --parallel-trees             Enable parallel tree startup workers
  --no-parallel-trees          Disable parallel tree startup workers
  --parallel-trees-max <n>     Max parallel tree startup workers (default 4)
  --clear-port-state           Remove saved port state and exit (alias: --clear-ports)
  --debug-trace                Enable debug trace logging to a file
  --debug-trace-log <path>     Write debug trace log to path
  --debug-trace-no-xtrace      Disable bash xtrace in debug log
  --debug-trace-no-stdio       Do not tee stdout/stderr to debug log
  --debug-trace-no-interactive Disable xtrace during interactive rendering
  --log-profile <profile>      Set backend + frontend log profile (quiet/info/debug, standard/verbose)
  --log-level <level>          Set backend + frontend log level (overrides profile)
  --backend-log-profile <profile>
  --backend-log-level <level>
  --frontend-log-profile <profile>
  --frontend-log-level <level>
  --frontend-test-runner <runner>  Frontend test runner (bun default; auto, npm, bun)
  --main-services-local        Run Main with local Supabase/n8n (ignore .env.main overrides; alias: --main-local)
  --main-services-remote       Run Main with remote services via .env.main (alias: --main-remote)
  --key-debug                  Enable TTY key debug logging
  --help, -h                   Show this help
USAGE
}

run_all_trees_cli_init_config() {
    TREES_MODE=false
    MAIN_MODE=false
    FORCE_MAIN_MODE=false
    FRESH_INSTALL=false
    INTERACTIVE_MODE=true
    FORCE_PORTS=false
    RESUME_MODE=false
    DOCKER_MODE=false
    DOCKER_TEMP_MODE=false
    ORIGINAL_ARGS=("$@")
    SETUP_WORKTREES=false
    SETUP_WORKTREES_MODE=""
    SETUP_WORKTREES_FEATURE=""
    SETUP_WORKTREES_COUNT=""
    SETUP_WORKTREES_ITER=""
    SETUP_WORKTREE_EXISTING=false
    SETUP_WORKTREE_RECREATE=false
    SETUP_INCLUDE_WORKTREES_RAW=""
    PLANNING_ENVS=false
    PLANNING_SELECTION_RAW=""
    PLANNING_CREATE_PRS=false
    PLANNING_PRS_ONLY=false
    PLANNING_KEEP_PLAN="${PLANNING_KEEP_PLAN:-false}"
    AUTO_RESUME="${AUTO_RESUME:-true}"
    SHOW_HELP=false
    KEY_DEBUG=${KEY_DEBUG:-false}
    MAIN_REQUIREMENTS_MODE="${MAIN_REQUIREMENTS_MODE:-}"
    FRONTEND_TEST_RUNNER="${FRONTEND_TEST_RUNNER:-bun}"
    RUN_SH_FAST_STARTUP="${RUN_SH_FAST_STARTUP:-false}"
    RUN_SH_REFRESH_CACHE="${RUN_SH_REFRESH_CACHE:-false}"
    RUN_SH_CLEAR_PORTS="${RUN_SH_CLEAR_PORTS:-false}"
    RUN_SH_OPT_PARALLEL_TREES="${RUN_SH_OPT_PARALLEL_TREES:-true}"
    RUN_SH_OPT_PARALLEL_TREES_EXPLICIT="${RUN_SH_OPT_PARALLEL_TREES_EXPLICIT:-false}"
    RUN_SH_OPT_PARALLEL_TREES_MAX="${RUN_SH_OPT_PARALLEL_TREES_MAX:-4}"
    RUN_SH_DEBUG="${RUN_SH_DEBUG:-false}"
    RUN_SH_DEBUG_LOG="${RUN_SH_DEBUG_LOG:-}"
    RUN_SH_DEBUG_XTRACE="${RUN_SH_DEBUG_XTRACE:-true}"
    RUN_SH_DEBUG_STDIO="${RUN_SH_DEBUG_STDIO:-true}"
    RUN_SH_DEBUG_TRACE_INTERACTIVE="${RUN_SH_DEBUG_TRACE_INTERACTIVE:-true}"
    LOG_PROFILE_OVERRIDE="${LOG_PROFILE_OVERRIDE:-}"
    LOG_LEVEL_OVERRIDE="${LOG_LEVEL_OVERRIDE:-}"
    BACKEND_LOG_PROFILE_OVERRIDE="${BACKEND_LOG_PROFILE_OVERRIDE:-}"
    BACKEND_LOG_LEVEL_OVERRIDE="${BACKEND_LOG_LEVEL_OVERRIDE:-}"
    FRONTEND_LOG_PROFILE_OVERRIDE="${FRONTEND_LOG_PROFILE_OVERRIDE:-}"
    FRONTEND_LOG_LEVEL_OVERRIDE="${FRONTEND_LOG_LEVEL_OVERRIDE:-}"
    RUN_SH_COMMAND="${RUN_SH_COMMAND:-}"
    RUN_SH_DOCTOR="${RUN_SH_DOCTOR:-false}"
    RUN_SH_COMMAND_TARGETS=()
    RUN_SH_COMMAND_ONLY="${RUN_SH_COMMAND_ONLY:-false}"
    RUN_SH_COMMAND_RESUME="${RUN_SH_COMMAND_RESUME:-false}"
    RUN_SH_COMMAND_MODE="${RUN_SH_COMMAND_MODE:-}"
    RUN_SH_COMMAND_LIST_COMMANDS="${RUN_SH_COMMAND_LIST_COMMANDS:-false}"
    RUN_SH_COMMAND_LIST_TARGETS="${RUN_SH_COMMAND_LIST_TARGETS:-false}"
    RUN_SH_COMMAND_PR_BASE="${RUN_SH_COMMAND_PR_BASE:-}"
    RUN_SH_COMMAND_COMMIT_MESSAGE="${RUN_SH_COMMAND_COMMIT_MESSAGE:-}"
    RUN_SH_COMMAND_COMMIT_MESSAGE_FILE="${RUN_SH_COMMAND_COMMIT_MESSAGE_FILE:-}"
    RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES="${RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES:-}"
    RUN_SH_COMMAND_BLAST_KEEP_WORKTREE_VOLUMES="${RUN_SH_COMMAND_BLAST_KEEP_WORKTREE_VOLUMES:-false}"
    RUN_SH_COMMAND_BLAST_REMOVE_MAIN_VOLUMES="${RUN_SH_COMMAND_BLAST_REMOVE_MAIN_VOLUMES:-}"
    RUN_SH_COMMAND_LOGS_TAIL="${RUN_SH_COMMAND_LOGS_TAIL:-200}"
    RUN_SH_COMMAND_LOGS_FOLLOW="${RUN_SH_COMMAND_LOGS_FOLLOW:-false}"
    RUN_SH_COMMAND_LOGS_DURATION="${RUN_SH_COMMAND_LOGS_DURATION:-}"
    RUN_SH_COMMAND_LOGS_NO_COLOR="${RUN_SH_COMMAND_LOGS_NO_COLOR:-false}"
    RUN_SH_COMMAND_ANALYZE_MODE="${RUN_SH_COMMAND_ANALYZE_MODE:-}"
    RUN_SH_COMMAND_DASHBOARD_INTERACTIVE="${RUN_SH_COMMAND_DASHBOARD_INTERACTIVE:-false}"
    RUN_ALL_TREES_ARG_ERRORS=()
}

run_all_trees_cli_parse_args() {
    local -a errors=()
    local -a original_args=("$@")
    local trees_mode=false
    local main_mode=false
    local force_main_mode=false
    local fresh_install=false
    local interactive_mode=true
    local force_ports=false
    local resume_mode=false
    local docker_mode=false
    local docker_temp_mode=false
    local setup_worktrees=false
    local setup_worktrees_mode=""
    local setup_worktrees_feature=""
    local setup_worktrees_count=""
    local setup_worktrees_iter=""
    local setup_worktree_existing=false
    local setup_worktree_recreate=false
    local setup_include_worktrees_raw=""
    local planning_envs=false
    local planning_selection_raw=""
    local planning_create_prs=false
    local planning_prs_only=false
    local planning_keep_plan="${PLANNING_KEEP_PLAN:-false}"
    local seed_requirements_from_base="${SEED_REQUIREMENTS_FROM_BASE:-false}"
    local auto_resume="${AUTO_RESUME:-true}"
    local show_help=false
    local key_debug="${KEY_DEBUG:-false}"
    local main_requirements_mode="${MAIN_REQUIREMENTS_MODE:-}"
    local frontend_test_runner="${FRONTEND_TEST_RUNNER:-}"
    local run_sh_fast_startup="${RUN_SH_FAST_STARTUP:-false}"
    local run_sh_refresh_cache="${RUN_SH_REFRESH_CACHE:-false}"
    local run_sh_clear_ports="${RUN_SH_CLEAR_PORTS:-false}"
    local run_sh_opt_parallel_trees="${RUN_SH_OPT_PARALLEL_TREES:-true}"
    local run_sh_opt_parallel_trees_explicit="${RUN_SH_OPT_PARALLEL_TREES_EXPLICIT:-false}"
    local run_sh_opt_parallel_trees_max="${RUN_SH_OPT_PARALLEL_TREES_MAX:-4}"
    local run_sh_debug="${RUN_SH_DEBUG:-false}"
    local run_sh_debug_log="${RUN_SH_DEBUG_LOG:-}"
    local run_sh_debug_xtrace="${RUN_SH_DEBUG_XTRACE:-true}"
    local run_sh_debug_stdio="${RUN_SH_DEBUG_STDIO:-true}"
    local run_sh_debug_trace_interactive="${RUN_SH_DEBUG_TRACE_INTERACTIVE:-true}"
    local log_profile="${LOG_PROFILE_OVERRIDE:-}"
    local log_level="${LOG_LEVEL_OVERRIDE:-}"
    local backend_log_profile="${BACKEND_LOG_PROFILE_OVERRIDE:-}"
    local backend_log_level="${BACKEND_LOG_LEVEL_OVERRIDE:-}"
    local frontend_log_profile="${FRONTEND_LOG_PROFILE_OVERRIDE:-}"
    local frontend_log_level="${FRONTEND_LOG_LEVEL_OVERRIDE:-}"
    local setup_mode_seen=""
    local run_sh_command="${RUN_SH_COMMAND:-}"
    local run_sh_doctor="${RUN_SH_DOCTOR:-false}"
    local run_sh_command_only="${RUN_SH_COMMAND_ONLY:-false}"
    local run_sh_command_resume="${RUN_SH_COMMAND_RESUME:-false}"
    local run_sh_command_mode="${RUN_SH_COMMAND_MODE:-}"
    local run_sh_command_list_commands="${RUN_SH_COMMAND_LIST_COMMANDS:-false}"
    local run_sh_command_list_targets="${RUN_SH_COMMAND_LIST_TARGETS:-false}"
    local run_sh_command_pr_base="${RUN_SH_COMMAND_PR_BASE:-}"
    local run_sh_command_commit_message="${RUN_SH_COMMAND_COMMIT_MESSAGE:-}"
    local run_sh_command_commit_message_file="${RUN_SH_COMMAND_COMMIT_MESSAGE_FILE:-}"
    local run_sh_command_stop_all_remove_volumes="${RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES:-}"
    local run_sh_command_blast_keep_worktree_volumes="${RUN_SH_COMMAND_BLAST_KEEP_WORKTREE_VOLUMES:-false}"
    local run_sh_command_blast_remove_main_volumes="${RUN_SH_COMMAND_BLAST_REMOVE_MAIN_VOLUMES:-}"
    local run_sh_command_logs_tail="${RUN_SH_COMMAND_LOGS_TAIL:-200}"
    local run_sh_command_logs_follow="${RUN_SH_COMMAND_LOGS_FOLLOW:-false}"
    local run_sh_command_logs_duration="${RUN_SH_COMMAND_LOGS_DURATION:-}"
    local run_sh_command_logs_no_color="${RUN_SH_COMMAND_LOGS_NO_COLOR:-false}"
    local run_sh_command_analyze_mode="${RUN_SH_COMMAND_ANALYZE_MODE:-}"
    local run_sh_command_dashboard_interactive="${RUN_SH_COMMAND_DASHBOARD_INTERACTIVE:-false}"
    local -a run_sh_command_targets=()
    local default_mode_raw="${ENVCTL_DEFAULT_MODE:-main}"
    local default_mode=""

    default_mode=$(printf '%s' "$default_mode_raw" | tr '[:upper:]' '[:lower:]')
    case "$default_mode" in
        trees)
            trees_mode=true
            ;;
        main|"")
            trees_mode=false
            ;;
        *)
            errors+=("Invalid ENVCTL_DEFAULT_MODE: ${default_mode_raw} (expected: main or trees)")
            trees_mode=false
            ;;
    esac

    if [ -n "${RUN_SH_COMMAND_TARGETS:-}" ]; then
        IFS=',' read -r -a run_sh_command_targets <<< "$RUN_SH_COMMAND_TARGETS"
    fi

    while [ $# -gt 0 ]; do
        case "$1" in
            --command|--action)
                run_sh_command="${2:-}"
                if [ -z "$run_sh_command" ] || [[ "$run_sh_command" == -* ]]; then
                    errors+=("Missing value for --command.")
                    run_sh_command=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --command=*|--action=*)
                run_sh_command="${1#*=}"
                shift
                ;;
            --doctor)
                run_sh_doctor=true
                run_sh_command="doctor"
                shift
                ;;
            delete-worktree|delete-worktrees|remove-worktrees|--delete-worktree|--delete-worktrees|--remove-worktrees|blast-worktree|blast-worktrees|--blast-worktree|--blast-worktrees)
                run_sh_command="delete-worktree"
                shift
                ;;
            dashboard|--dashboard)
                run_sh_command="dashboard"
                shift
                ;;
            --project)
                local project_name="${2:-}"
                if [ -z "$project_name" ] || [[ "$project_name" == -* ]]; then
                    errors+=("Missing value for --project.")
                else
                    local -a parsed_projects=()
                    IFS=',' read -r -a parsed_projects <<< "$project_name"
                    local project
                    for project in "${parsed_projects[@]}"; do
                        project="${project#"${project%%[![:space:]]*}"}"
                        project="${project%"${project##*[![:space:]]}"}"
                        [ -n "$project" ] && run_sh_command_targets+=("project:${project}")
                    done
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --project=*)
                local project_name="${1#*=}"
                if [ -z "$project_name" ]; then
                    errors+=("Missing value for --project.")
                else
                    local -a parsed_projects=()
                    IFS=',' read -r -a parsed_projects <<< "$project_name"
                    local project
                    for project in "${parsed_projects[@]}"; do
                        project="${project#"${project%%[![:space:]]*}"}"
                        project="${project%"${project##*[![:space:]]}"}"
                        [ -n "$project" ] && run_sh_command_targets+=("project:${project}")
                    done
                fi
                shift
                ;;
            --projects)
                local projects_csv="${2:-}"
                if [ -z "$projects_csv" ] || [[ "$projects_csv" == -* ]]; then
                    errors+=("Missing value for --projects.")
                else
                    local -a parsed_projects=()
                    IFS=',' read -r -a parsed_projects <<< "$projects_csv"
                    local project
                    for project in "${parsed_projects[@]}"; do
                        [ -n "$project" ] && run_sh_command_targets+=("project:${project}")
                    done
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --projects=*)
                local projects_csv="${1#*=}"
                if [ -z "$projects_csv" ]; then
                    errors+=("Missing value for --projects.")
                else
                    local -a parsed_projects=()
                    IFS=',' read -r -a parsed_projects <<< "$projects_csv"
                    local project
                    for project in "${parsed_projects[@]}"; do
                        project="${project#"${project%%[![:space:]]*}"}"
                        project="${project%"${project##*[![:space:]]}"}"
                        [ -n "$project" ] && run_sh_command_targets+=("project:${project}")
                    done
                fi
                shift
                ;;
            --service)
                local service_name="${2:-}"
                if [ -z "$service_name" ] || [[ "$service_name" == -* ]]; then
                    errors+=("Missing value for --service.")
                else
                    run_sh_command_targets+=("service:${service_name}")
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --all)
                run_sh_command_targets+=("all")
                shift
                ;;
            --untested)
                run_sh_command_targets+=("untested")
                shift
                ;;
            --pr-base)
                run_sh_command_pr_base="${2:-}"
                if [ -z "$run_sh_command_pr_base" ] || [[ "$run_sh_command_pr_base" == -* ]]; then
                    errors+=("Missing value for --pr-base.")
                    run_sh_command_pr_base=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --pr-base=*)
                run_sh_command_pr_base="${1#*=}"
                shift
                ;;
            --commit-message)
                run_sh_command_commit_message="${2:-}"
                if [ -z "$run_sh_command_commit_message" ] || [[ "$run_sh_command_commit_message" == -* ]]; then
                    errors+=("Missing value for --commit-message.")
                    run_sh_command_commit_message=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --commit-message=*)
                run_sh_command_commit_message="${1#*=}"
                shift
                ;;
            --commit-message-file)
                run_sh_command_commit_message_file="${2:-}"
                if [ -z "$run_sh_command_commit_message_file" ] || [[ "$run_sh_command_commit_message_file" == -* ]]; then
                    errors+=("Missing value for --commit-message-file.")
                    run_sh_command_commit_message_file=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --commit-message-file=*)
                run_sh_command_commit_message_file="${1#*=}"
                shift
                ;;
            stop|--stop)
                run_sh_command="stop"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            stop-all|--stop-all)
                run_sh_command="stop-all"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            blast-all|--blast-all)
                run_sh_command="blast-all"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            restart|--restart)
                run_sh_command="restart"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            test|tests|--test|--tests)
                run_sh_command="test"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            logs|--logs)
                run_sh_command="logs"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            health|--health)
                run_sh_command="health"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            analyze|--analyze)
                run_sh_command="analyze"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            migrate|migration|migrations|--migrate)
                run_sh_command="migrate"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            pr|prs|--pr|--prs)
                run_sh_command="pr"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            commit|--commit)
                run_sh_command="commit"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            errors|--errors)
                run_sh_command="errors"
                run_sh_command_only=true
                run_sh_command_resume=true
                shift
                ;;
            --stop-all-remove-volumes|--remove-volumes)
                run_sh_command_stop_all_remove_volumes=true
                shift
                ;;
            --blast-keep-worktree-volumes)
                run_sh_command_blast_keep_worktree_volumes=true
                shift
                ;;
            --blast-remove-worktree-volumes)
                run_sh_command_blast_keep_worktree_volumes=false
                shift
                ;;
            --blast-remove-main-volumes)
                run_sh_command_blast_remove_main_volumes=true
                shift
                ;;
            --blast-keep-main-volumes)
                run_sh_command_blast_remove_main_volumes=false
                shift
                ;;
            --logs-tail)
                run_sh_command_logs_tail="${2:-}"
                if [ -z "$run_sh_command_logs_tail" ] || [[ "$run_sh_command_logs_tail" == -* ]]; then
                    errors+=("Missing value for --logs-tail.")
                    run_sh_command_logs_tail=""
                elif ! [[ "$run_sh_command_logs_tail" =~ ^[0-9]+$ ]]; then
                    errors+=("Invalid value for --logs-tail: $run_sh_command_logs_tail")
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --logs-tail=*)
                run_sh_command_logs_tail="${1#*=}"
                shift
                ;;
            --logs-follow)
                run_sh_command_logs_follow=true
                shift
                ;;
            --logs-duration)
                run_sh_command_logs_duration="${2:-}"
                if [ -z "$run_sh_command_logs_duration" ] || [[ "$run_sh_command_logs_duration" == -* ]]; then
                    errors+=("Missing value for --logs-duration.")
                    run_sh_command_logs_duration=""
                elif ! [[ "$run_sh_command_logs_duration" =~ ^[0-9]+$ ]]; then
                    errors+=("Invalid value for --logs-duration: $run_sh_command_logs_duration")
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --logs-duration=*)
                run_sh_command_logs_duration="${1#*=}"
                shift
                ;;
            --logs-no-color)
                run_sh_command_logs_no_color=true
                shift
                ;;
            --skip-startup|--command-only)
                run_sh_command_only=true
                shift
                ;;
            --load-state|--command-resume)
                run_sh_command_resume=true
                shift
                ;;
            --list-commands)
                run_sh_command_list_commands=true
                shift
                ;;
            --list-targets)
                run_sh_command_list_targets=true
                shift
                ;;
            --list-trees)
                run_sh_command_list_targets=true
                trees_mode=true
                shift
                ;;
            --analyze-mode)
                run_sh_command_analyze_mode="${2:-}"
                if [ -z "$run_sh_command_analyze_mode" ] || [[ "$run_sh_command_analyze_mode" == -* ]]; then
                    errors+=("Missing value for --analyze-mode.")
                    run_sh_command_analyze_mode=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --analyze-mode=*)
                run_sh_command_analyze_mode="${1#*=}"
                shift
                ;;
            --tree|--tree=true|--trees|--trees=true|tree=true|TREE=true|trees=true|TREES=true|tees=true|TEES=true)
                trees_mode=true
                shift
                ;;
            --tree=false|--trees=false|tree=false|TREE=false|trees=false|TREES=false|tees=false|TEES=false)
                trees_mode=false
                force_main_mode=true
                shift
                ;;
            --main|--main=true|main=true|MAIN=true)
                trees_mode=false
                force_main_mode=true
                shift
                ;;
            main=false|MAIN=false)
                trees_mode=true
                shift
                ;;
            fresh=true|FRESH=true)
                fresh_install=true
                shift
                ;;
            --headless|--no-interactive|--batch|-b)
                interactive_mode=false
                shift
                ;;
            --interactive)
                interactive_mode=true
                run_sh_command_dashboard_interactive=true
                shift
                ;;
            resume|resume=true|RESUME=true|--resume)
                resume_mode=true
                shift
                ;;
            --no-resume|--no-auto-resume)
                auto_resume=false
                shift
                ;;
            docker=true|DOCKER=true|--docker)
                docker_mode=true
                shift
                ;;
            docker-temp=true|DOCKER_TEMP=true|--stop-docker-on-exit|--docker-temp|--temp-docker)
                docker_temp_mode=true
                shift
                ;;
            force=true|FORCE=true|--force|-f)
                force_ports=true
                shift
                ;;
            --setup-worktrees)
                setup_worktrees=true
                if [ -n "$setup_mode_seen" ] && [ "$setup_mode_seen" != "multi" ]; then
                    errors+=("Conflicting setup flags: use --setup-worktrees or --setup-worktree, not both.")
                fi
                setup_mode_seen="multi"
                setup_worktrees_mode="multi"
                setup_worktrees_feature="${2:-}"
                setup_worktrees_count="${3:-}"
                if [ -z "$setup_worktrees_feature" ] || [[ "$setup_worktrees_feature" == -* ]]; then
                    errors+=("Missing feature for --setup-worktrees.")
                    setup_worktrees_feature=""
                fi
                if [ -z "$setup_worktrees_count" ] || [[ "$setup_worktrees_count" == -* ]]; then
                    errors+=("Missing count for --setup-worktrees.")
                    setup_worktrees_count=""
                elif ! [[ "$setup_worktrees_count" =~ ^[0-9]+$ ]]; then
                    errors+=("Invalid count for --setup-worktrees: $setup_worktrees_count")
                fi
                if [ $# -ge 3 ]; then
                    shift 3
                else
                    shift "$#"
                fi
                ;;
            --setup-worktree)
                setup_worktrees=true
                if [ -n "$setup_mode_seen" ] && [ "$setup_mode_seen" != "single" ]; then
                    errors+=("Conflicting setup flags: use --setup-worktrees or --setup-worktree, not both.")
                fi
                setup_mode_seen="single"
                setup_worktrees_mode="single"
                setup_worktrees_feature="${2:-}"
                setup_worktrees_iter="${3:-}"
                if [ -z "$setup_worktrees_feature" ] || [[ "$setup_worktrees_feature" == -* ]]; then
                    errors+=("Missing feature for --setup-worktree.")
                    setup_worktrees_feature=""
                fi
                if [ -z "$setup_worktrees_iter" ] || [[ "$setup_worktrees_iter" == -* ]]; then
                    errors+=("Missing iteration for --setup-worktree.")
                    setup_worktrees_iter=""
                elif ! [[ "$setup_worktrees_iter" =~ ^[0-9]+$ ]]; then
                    errors+=("Invalid iteration for --setup-worktree: $setup_worktrees_iter")
                fi
                if [ $# -ge 3 ]; then
                    shift 3
                else
                    shift "$#"
                fi
                ;;
            --reuse-existing-worktree|--setup-worktree-existing)
                setup_worktree_existing=true
                shift
                ;;
            --recreate-existing-worktree|--setup-worktree-recreate)
                setup_worktree_recreate=true
                shift
                ;;
            --include-existing-worktrees|--setup-include-worktrees)
                setup_include_worktrees_raw="${2:-}"
                if [ -z "$setup_include_worktrees_raw" ] || [[ "$setup_include_worktrees_raw" == -* ]]; then
                    errors+=("Missing value for --include-existing-worktrees.")
                    setup_include_worktrees_raw=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --include-existing-worktrees=*|--setup-include-worktrees=*)
                setup_include_worktrees_raw="${1#*=}"
                shift
                ;;
            plan|--plan|--plan-selection|--planning-envs)
                planning_envs=true
                run_sh_opt_parallel_trees=true
                run_sh_opt_parallel_trees_explicit=true
                if [ -n "${2:-}" ] && [[ "${2:-}" != -* ]]; then
                    planning_selection_raw="$2"
                    shift 2
                else
                    shift
                fi
                ;;
            sequential-plan|--sequential-plan|--plan-sequential)
                planning_envs=true
                run_sh_opt_parallel_trees=false
                run_sh_opt_parallel_trees_explicit=true
                if [ -n "${2:-}" ] && [[ "${2:-}" != -* ]]; then
                    planning_selection_raw="$2"
                    shift 2
                else
                    shift
                fi
                ;;
            parallel-plan|--parallel-plan|--plan-parallel)
                planning_envs=true
                run_sh_opt_parallel_trees=true
                run_sh_opt_parallel_trees_explicit=true
                if [ -n "${2:-}" ] && [[ "${2:-}" != -* ]]; then
                    planning_selection_raw="$2"
                    shift 2
                else
                    shift
                fi
                ;;
            --main-services-local|--main-local)
                main_requirements_mode="local"
                shift
                ;;
            --main-services-remote|--main-remote)
                main_requirements_mode="remote"
                shift
                ;;
            --key-debug)
                key_debug=true
                shift
                ;;
            --plan=*|--plan-selection=*|--planning-envs=*)
                planning_envs=true
                run_sh_opt_parallel_trees=true
                run_sh_opt_parallel_trees_explicit=true
                planning_selection_raw="${1#*=}"
                shift
                ;;
            --sequential-plan=*|--plan-sequential=*)
                planning_envs=true
                run_sh_opt_parallel_trees=false
                run_sh_opt_parallel_trees_explicit=true
                planning_selection_raw="${1#*=}"
                shift
                ;;
            --parallel-plan=*|--plan-parallel=*)
                planning_envs=true
                run_sh_opt_parallel_trees=true
                run_sh_opt_parallel_trees_explicit=true
                planning_selection_raw="${1#*=}"
                shift
                ;;
            --planning-prs)
                planning_envs=true
                planning_create_prs=true
                planning_prs_only=true
                if [ -n "${2:-}" ] && [[ "${2:-}" != -* ]]; then
                    planning_selection_raw="$2"
                    shift 2
                else
                    shift
                fi
                ;;
            --planning-prs=*)
                planning_envs=true
                planning_create_prs=true
                planning_prs_only=true
                planning_selection_raw="${1#*=}"
                shift
                ;;
            --keep-plan)
                planning_keep_plan=true
                shift
                ;;
            --log-profile)
                log_profile="${2:-}"
                if [ -z "$log_profile" ] || [[ "$log_profile" == -* ]]; then
                    errors+=("Missing value for --log-profile (quiet/info/debug, standard/verbose).")
                    log_profile=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --log-profile=*)
                log_profile="${1#*=}"
                shift
                ;;
            --log-level)
                log_level="${2:-}"
                if [ -z "$log_level" ] || [[ "$log_level" == -* ]]; then
                    errors+=("Missing value for --log-level (debug/info/warn/error).")
                    log_level=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --log-level=*)
                log_level="${1#*=}"
                shift
                ;;
            --backend-log-profile)
                backend_log_profile="${2:-}"
                if [ -z "$backend_log_profile" ] || [[ "$backend_log_profile" == -* ]]; then
                    errors+=("Missing value for --backend-log-profile (quiet/info/debug, standard/verbose).")
                    backend_log_profile=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --backend-log-profile=*)
                backend_log_profile="${1#*=}"
                shift
                ;;
            --backend-log-level)
                backend_log_level="${2:-}"
                if [ -z "$backend_log_level" ] || [[ "$backend_log_level" == -* ]]; then
                    errors+=("Missing value for --backend-log-level (debug/info/warn/error).")
                    backend_log_level=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --backend-log-level=*)
                backend_log_level="${1#*=}"
                shift
                ;;
            --frontend-log-profile)
                frontend_log_profile="${2:-}"
                if [ -z "$frontend_log_profile" ] || [[ "$frontend_log_profile" == -* ]]; then
                    errors+=("Missing value for --frontend-log-profile (quiet/info/debug).")
                    frontend_log_profile=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --frontend-log-profile=*)
                frontend_log_profile="${1#*=}"
                shift
                ;;
            --frontend-log-level)
                frontend_log_level="${2:-}"
                if [ -z "$frontend_log_level" ] || [[ "$frontend_log_level" == -* ]]; then
                    errors+=("Missing value for --frontend-log-level (debug/info/warn/error).")
                    frontend_log_level=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --frontend-log-level=*)
                frontend_log_level="${1#*=}"
                shift
                ;;
            --frontend-test-runner)
                frontend_test_runner="${2:-}"
                if [ -z "$frontend_test_runner" ] || [[ "$frontend_test_runner" == -* ]]; then
                    errors+=("Missing value for --frontend-test-runner (auto, npm, bun).")
                    frontend_test_runner=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --frontend-test-runner=*|frontend-test-runner=*|FRONTEND_TEST_RUNNER=*)
                frontend_test_runner="${1#*=}"
                shift
                ;;
            --seed-requirements-from-base|--copy-db-storage)
                seed_requirements_from_base=true
                shift
                ;;
            --no-seed-requirements-from-base|--no-copy-db-storage)
                seed_requirements_from_base=false
                shift
                ;;
            copy-db-storage=true|COPY_DB_STORAGE=true)
                seed_requirements_from_base=true
                shift
                ;;
            copy-db-storage=false|COPY_DB_STORAGE=false)
                seed_requirements_from_base=false
                shift
                ;;
            seed-requirements-from-base=true|SEED_REQUIREMENTS_FROM_BASE=true)
                seed_requirements_from_base=true
                shift
                ;;
            seed-requirements-from-base=false|SEED_REQUIREMENTS_FROM_BASE=false)
                seed_requirements_from_base=false
                shift
                ;;
            --fast|--fast-startup)
                run_sh_fast_startup=true
                shift
                ;;
            --refresh-cache)
                run_sh_refresh_cache=true
                run_sh_fast_startup=true
                shift
                ;;
            --parallel-trees)
                run_sh_opt_parallel_trees=true
                run_sh_opt_parallel_trees_explicit=true
                shift
                ;;
            --no-parallel-trees)
                run_sh_opt_parallel_trees=false
                run_sh_opt_parallel_trees_explicit=true
                shift
                ;;
            --parallel-trees-max)
                run_sh_opt_parallel_trees_max="${2:-}"
                if [ -z "$run_sh_opt_parallel_trees_max" ] || [[ "$run_sh_opt_parallel_trees_max" == -* ]]; then
                    errors+=("Missing value for --parallel-trees-max.")
                    run_sh_opt_parallel_trees_max=""
                elif ! [[ "$run_sh_opt_parallel_trees_max" =~ ^[0-9]+$ ]] || [ "$run_sh_opt_parallel_trees_max" -lt 1 ]; then
                    errors+=("Invalid value for --parallel-trees-max: $run_sh_opt_parallel_trees_max")
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --parallel-trees-max=*)
                run_sh_opt_parallel_trees_max="${1#*=}"
                if ! [[ "$run_sh_opt_parallel_trees_max" =~ ^[0-9]+$ ]] || [ "$run_sh_opt_parallel_trees_max" -lt 1 ]; then
                    errors+=("Invalid value for --parallel-trees-max: $run_sh_opt_parallel_trees_max")
                fi
                shift
                ;;
            parallel-trees=true|PARALLEL_TREES=true|RUN_SH_OPT_PARALLEL_TREES=true)
                run_sh_opt_parallel_trees=true
                run_sh_opt_parallel_trees_explicit=true
                shift
                ;;
            parallel-trees=false|PARALLEL_TREES=false|RUN_SH_OPT_PARALLEL_TREES=false)
                run_sh_opt_parallel_trees=false
                run_sh_opt_parallel_trees_explicit=true
                shift
                ;;
            parallel-trees-max=*|PARALLEL_TREES_MAX=*|RUN_SH_OPT_PARALLEL_TREES_MAX=*)
                run_sh_opt_parallel_trees_max="${1#*=}"
                if ! [[ "$run_sh_opt_parallel_trees_max" =~ ^[0-9]+$ ]] || [ "$run_sh_opt_parallel_trees_max" -lt 1 ]; then
                    errors+=("Invalid value for parallel-trees-max: $run_sh_opt_parallel_trees_max")
                fi
                shift
                ;;
            --clear-port-state|--clear-ports|--clear-port-cache)
                run_sh_clear_ports=true
                shift
                ;;
            --debug-trace)
                run_sh_debug=true
                shift
                ;;
            --debug-trace-log)
                run_sh_debug=true
                run_sh_debug_log="${2:-}"
                if [ -z "$run_sh_debug_log" ] || [[ "$run_sh_debug_log" == -* ]]; then
                    errors+=("Missing value for --debug-trace-log.")
                    run_sh_debug_log=""
                fi
                if [ $# -ge 2 ]; then
                    shift 2
                else
                    shift "$#"
                fi
                ;;
            --debug-trace-log=*)
                run_sh_debug=true
                run_sh_debug_log="${1#*=}"
                shift
                ;;
            --debug-trace-no-xtrace)
                run_sh_debug=true
                run_sh_debug_xtrace=false
                shift
                ;;
            --debug-trace-no-stdio)
                run_sh_debug=true
                run_sh_debug_stdio=false
                shift
                ;;
            --debug-trace-no-interactive)
                run_sh_debug=true
                run_sh_debug_trace_interactive=false
                shift
                ;;
            --help|-h|help)
                show_help=true
                shift
                ;;
            debug-pack|--debug-pack|--debug-ui-pack)
                errors+=("debug-pack is only available in Python runtime. Disable shell fallback or set ENVCTL_ENGINE_PYTHON_V1=true.")
                shift
                ;;
            *)
                if [[ "$1" == --* ]]; then
                    errors+=("Unknown option: $1")
                fi
                shift
                ;;
        esac
    done

    if [ -n "$run_sh_command_mode" ]; then
        case "$run_sh_command_mode" in
            only)
                run_sh_command_only=true
                ;;
            resume)
                run_sh_command_resume=true
                ;;
        esac
    fi

    if [ "$setup_worktree_existing" = true ] && [ "$setup_worktree_recreate" = true ]; then
        errors+=("Conflicting setup flags: use only one of --reuse-existing-worktree or --recreate-existing-worktree.")
    fi


    if [ "${TREES:-}" = "true" ]; then
        trees_mode=true
    fi
    if [ "${TREES:-}" = "false" ]; then
        trees_mode=false
        force_main_mode=true
    fi
    if [ "${MAIN:-}" = "true" ]; then
        trees_mode=false
        force_main_mode=true
    fi
    if [ "${MAIN:-}" = "false" ]; then
        trees_mode=true
    fi
    if [ "${FRESH:-false}" = "true" ]; then
        fresh_install=true
    fi
    if [ "${BATCH:-}" = "true" ] || [ "${NO_INTERACTIVE:-}" = "true" ]; then
        interactive_mode=false
    fi
    if [ "${RESUME:-}" = "true" ]; then
        resume_mode=true
    fi
    if [ "${DOCKER_MODE:-}" = "true" ] || [ "${DOCKER:-}" = "true" ]; then
        docker_mode=true
    fi
    if [ "${DOCKER_TEMP:-}" = "true" ]; then
        docker_temp_mode=true
    fi
    if [ "${FORCE:-false}" = "true" ]; then
        force_ports=true
    fi
    if [ "${RUN_SH_FAST_STARTUP:-false}" = "true" ]; then
        run_sh_fast_startup=true
    fi
    if [ "${RUN_SH_REFRESH_CACHE:-false}" = "true" ]; then
        run_sh_refresh_cache=true
        run_sh_fast_startup=true
    fi
    if [ "${RUN_SH_CLEAR_PORTS:-false}" = "true" ]; then
        run_sh_clear_ports=true
    fi

    if [ "$trees_mode" = true ]; then
        main_mode=false
    else
        main_mode=true
    fi
    if [ "$force_main_mode" = true ]; then
        main_mode=true
        auto_resume=false
    fi
    if [ -n "$log_profile" ]; then
        if [ -z "$backend_log_profile" ]; then
            backend_log_profile="$log_profile"
        fi
        if [ -z "$frontend_log_profile" ]; then
            frontend_log_profile="$log_profile"
        fi
    fi
    if [ -n "$log_level" ]; then
        if [ -z "$backend_log_level" ]; then
            backend_log_level="$log_level"
        fi
        if [ -z "$frontend_log_level" ]; then
            frontend_log_level="$log_level"
        fi
    fi

    TREES_MODE=$trees_mode
    MAIN_MODE=$main_mode
    FORCE_MAIN_MODE=$force_main_mode
    FRESH_INSTALL=$fresh_install
    INTERACTIVE_MODE=$interactive_mode
    FORCE_PORTS=$force_ports
    RESUME_MODE=$resume_mode
    DOCKER_MODE=$docker_mode
    DOCKER_TEMP_MODE=$docker_temp_mode
    ORIGINAL_ARGS=("${original_args[@]}")
    SETUP_WORKTREES=$setup_worktrees
    SETUP_WORKTREES_MODE=$setup_worktrees_mode
    SETUP_WORKTREES_FEATURE=$setup_worktrees_feature
    SETUP_WORKTREES_COUNT=$setup_worktrees_count
    SETUP_WORKTREES_ITER=$setup_worktrees_iter
    SETUP_WORKTREE_EXISTING=$setup_worktree_existing
    SETUP_WORKTREE_RECREATE=$setup_worktree_recreate
    SETUP_INCLUDE_WORKTREES_RAW=$setup_include_worktrees_raw
    PLANNING_ENVS=$planning_envs
    PLANNING_SELECTION_RAW=$planning_selection_raw
    PLANNING_CREATE_PRS=$planning_create_prs
    PLANNING_PRS_ONLY=$planning_prs_only
    PLANNING_KEEP_PLAN=$planning_keep_plan
    SEED_REQUIREMENTS_FROM_BASE=$seed_requirements_from_base
    AUTO_RESUME=$auto_resume
    SHOW_HELP=$show_help
    KEY_DEBUG=$key_debug
    MAIN_REQUIREMENTS_MODE="$main_requirements_mode"
    FRONTEND_TEST_RUNNER="$frontend_test_runner"
    RUN_SH_FAST_STARTUP="$run_sh_fast_startup"
    RUN_SH_REFRESH_CACHE="$run_sh_refresh_cache"
    RUN_SH_CLEAR_PORTS="$run_sh_clear_ports"
    RUN_SH_OPT_PARALLEL_TREES="$run_sh_opt_parallel_trees"
    RUN_SH_OPT_PARALLEL_TREES_EXPLICIT="$run_sh_opt_parallel_trees_explicit"
    RUN_SH_OPT_PARALLEL_TREES_MAX="$run_sh_opt_parallel_trees_max"
    RUN_SH_DEBUG="$run_sh_debug"
    RUN_SH_DEBUG_LOG="$run_sh_debug_log"
    RUN_SH_DEBUG_XTRACE="$run_sh_debug_xtrace"
    RUN_SH_DEBUG_STDIO="$run_sh_debug_stdio"
    RUN_SH_DEBUG_TRACE_INTERACTIVE="$run_sh_debug_trace_interactive"
    LOG_PROFILE_OVERRIDE="$log_profile"
    LOG_LEVEL_OVERRIDE="$log_level"
    BACKEND_LOG_PROFILE_OVERRIDE="$backend_log_profile"
    BACKEND_LOG_LEVEL_OVERRIDE="$backend_log_level"
    FRONTEND_LOG_PROFILE_OVERRIDE="$frontend_log_profile"
    FRONTEND_LOG_LEVEL_OVERRIDE="$frontend_log_level"
    RUN_SH_COMMAND="$run_sh_command"
    RUN_SH_DOCTOR="$run_sh_doctor"
    RUN_SH_COMMAND_TARGETS=("${run_sh_command_targets[@]}")
    RUN_SH_COMMAND_ONLY="$run_sh_command_only"
    RUN_SH_COMMAND_RESUME="$run_sh_command_resume"
    RUN_SH_COMMAND_MODE="$run_sh_command_mode"
    RUN_SH_COMMAND_LIST_COMMANDS="$run_sh_command_list_commands"
    RUN_SH_COMMAND_LIST_TARGETS="$run_sh_command_list_targets"
    RUN_SH_COMMAND_PR_BASE="$run_sh_command_pr_base"
    RUN_SH_COMMAND_COMMIT_MESSAGE="$run_sh_command_commit_message"
    RUN_SH_COMMAND_COMMIT_MESSAGE_FILE="$run_sh_command_commit_message_file"
    RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES="$run_sh_command_stop_all_remove_volumes"
    RUN_SH_COMMAND_BLAST_KEEP_WORKTREE_VOLUMES="$run_sh_command_blast_keep_worktree_volumes"
    RUN_SH_COMMAND_BLAST_REMOVE_MAIN_VOLUMES="$run_sh_command_blast_remove_main_volumes"
    RUN_SH_COMMAND_LOGS_TAIL="$run_sh_command_logs_tail"
    RUN_SH_COMMAND_LOGS_FOLLOW="$run_sh_command_logs_follow"
    RUN_SH_COMMAND_LOGS_DURATION="$run_sh_command_logs_duration"
    RUN_SH_COMMAND_LOGS_NO_COLOR="$run_sh_command_logs_no_color"
    RUN_SH_COMMAND_ANALYZE_MODE="$run_sh_command_analyze_mode"
    RUN_SH_COMMAND_DASHBOARD_INTERACTIVE="$run_sh_command_dashboard_interactive"
    RUN_ALL_TREES_ARG_ERRORS=("${errors[@]}")
}

run_all_trees_cli_report_errors() {
    local err
    for err in "${RUN_ALL_TREES_ARG_ERRORS[@]}"; do
        if command -v log_error >/dev/null 2>&1; then
            log_error "$err"
        else
            printf '%s\n' "$err" >&2
        fi
    done
}
