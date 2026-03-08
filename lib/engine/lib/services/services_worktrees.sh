#!/usr/bin/env bash

# Service worktree helpers.

if [ -z "${PROJECT_ROOT_CACHE+x}" ]; then
    declare -A PROJECT_ROOT_CACHE=()
fi

project_name_from_service_name() {
    local name=$1
    local project_name="${name% Backend}"
    if [ "$project_name" = "$name" ]; then
        project_name="${name% Frontend}"
    fi
    echo "$project_name"
}

service_type_from_name() {
    case "$1" in
        *"Backend")
            echo "backend"
            ;;
        *"Frontend")
            echo "frontend"
            ;;
        *)
            echo ""
            ;;
    esac
}

sanitize_label() {
    local raw=$1
    printf '%s' "$raw" | tr ' /' '__' | tr -c 'A-Za-z0-9._-' '_'
}

ANALYSIS_SCOPE="all"
ANALYSIS_PROJECTS=()

project_root_from_service_name() {
    local name=$1
    local pid port log type dir
    service_info_fields "$name" pid port log type dir || return 1
    if [ -z "$dir" ]; then
        return 1
    fi
    echo "$(dirname "$dir")"
    return 0
}

project_root_from_project_name() {
    local project_name=$1
    if [ -n "$project_name" ]; then
        local cached="${PROJECT_ROOT_CACHE[$project_name]:-}"
        if [ -n "$cached" ]; then
            echo "$cached"
            return 0
        fi
    fi
    local service
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        local svc_project
        svc_project=$(project_name_from_service_name "$name")
        if [ "$svc_project" = "$project_name" ]; then
            local root
            root=$(project_root_from_service_name "$name") || continue
            if [ -n "$root" ]; then
                if [ -n "$project_name" ]; then
                    PROJECT_ROOT_CACHE["$project_name"]="$root"
                fi
                echo "$root"
                return 0
            fi
        fi
    done
    return 1
}

worktree_branch_for_path() {
    local target=$1
    target=$(cd "$target" && pwd -P 2>/dev/null) || return 1
    local current_path=""
    local current_real=""
    local line=""
    while IFS= read -r line; do
        case "$line" in
            worktree\ *)
                current_path="${line#worktree }"
                current_real=""
                if [ -n "$current_path" ]; then
                    current_real=$(cd "$current_path" && pwd -P 2>/dev/null || true)
                fi
                ;;
            branch\ *)
                if [ "$current_path" = "$target" ] || [ "$current_real" = "$target" ]; then
                    local branch_ref="${line#branch }"
                    echo "${branch_ref#refs/heads/}"
                    return 0
                fi
                ;;
            detached)
                if [ "$current_path" = "$target" ] || [ "$current_real" = "$target" ]; then
                    echo ""
                    return 0
                fi
                ;;
        esac
    done < <(git -C "$BASE_DIR" worktree list --porcelain 2>/dev/null)
    return 1
}

worktree_path_for_branch() {
    local branch=$1
    [ -n "$branch" ] || return 1
    local current_path=""
    local line=""
    while IFS= read -r line; do
        case "$line" in
            worktree\ *)
                current_path="${line#worktree }"
                ;;
            branch\ *)
                if [ "${line#branch }" = "refs/heads/${branch}" ]; then
                    if [ -n "$current_path" ]; then
                        echo "$current_path"
                        return 0
                    fi
                fi
                ;;
        esac
    done < <(git -C "$BASE_DIR" worktree list --porcelain 2>/dev/null)
    return 1
}
