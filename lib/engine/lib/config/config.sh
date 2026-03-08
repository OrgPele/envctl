#!/usr/bin/env bash

LIB_DIR="${LIB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

if [ -f "$LIB_DIR/run_all_trees_cli.sh" ]; then
    # shellcheck source=/dev/null
    source "$LIB_DIR/run_all_trees_cli.sh"
fi

print_run_all_trees_usage() {
    run_all_trees_cli_print_usage
}

init_run_all_trees_config() {
    run_all_trees_cli_init_config "$@"
}

parse_run_all_trees_args() {
    run_all_trees_cli_parse_args "$@"
}
