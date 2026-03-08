#!/usr/bin/env bash

# PR and commit helpers.

replace_placeholder() {
    local template=$1
    local placeholder=$2
    local value=$3
    local output=$4

    if command -v python3 >/dev/null 2>&1; then
        python3 - "$template" "$placeholder" "$value" <<'PY' > "$output"
import sys
path = sys.argv[1]
placeholder = sys.argv[2]
value = sys.argv[3]
with open(path, "r", encoding="utf-8") as handle:
    data = handle.read()
print(data.replace(placeholder, value))
PY
        return 0
    fi

    if command -v perl >/dev/null 2>&1; then
        PLACEHOLDER="$placeholder" VALUE="$value" perl -0pe 's/\Q$ENV{PLACEHOLDER}\E/$ENV{VALUE}/g' "$template" > "$output"
        return 0
    fi

    # Fallback: no replacement, copy template as-is.
    cat "$template" > "$output"
}

default_pr_base_branch() {
    local remote="${PR_REMOTE:-origin}"
    local preferred_branch=""
    for preferred_branch in dev-staging staging-dev; do
        if git show-ref --verify --quiet "refs/heads/${preferred_branch}" || \
           git show-ref --verify --quiet "refs/remotes/${remote}/${preferred_branch}"; then
            echo "${preferred_branch}"
            return 0
        fi
    done
    local ref
    ref=$(git symbolic-ref "refs/remotes/${remote}/HEAD" 2>/dev/null || true)
    if [ -n "$ref" ]; then
        echo "${ref#refs/remotes/${remote}/}"
        return 0
    fi
    local fallback=""
    for fallback in dev main master; do
        if git show-ref --verify --quiet "refs/heads/${fallback}" || \
           git show-ref --verify --quiet "refs/remotes/${remote}/${fallback}"; then
            echo "${fallback}"
            return 0
        fi
    done
    echo "dev-staging"
}

pr_branch_exists() {
    local branch=$1
    [ -n "$branch" ] || return 1
    local remote="${PR_REMOTE:-origin}"
    git show-ref --verify --quiet "refs/heads/${branch}" && return 0
    git show-ref --verify --quiet "refs/remotes/${remote}/${branch}" && return 0
    return 1
}

build_commit_list() {
    local base_ref=$1
    local head_ref=$2
    local commits
    local main_task_title=""
    if main_task_title=$(read_main_task_title 2>/dev/null); then
        echo "- ${main_task_title}"
        return 0
    fi
    commits=$(git log --format='- %s' "${base_ref}..${head_ref}" 2>/dev/null || true)
    if [ -z "$commits" ]; then
        commits="- No commits found"
    fi
    echo "$commits"
}

find_template_file() {
    local template_file=$1
    if [ -n "$template_file" ] && [ -f "$template_file" ]; then
        echo "$template_file"
        return 0
    fi
    if [ -f ".github/PULL_REQUEST_TEMPLATE.md" ]; then
        echo ".github/PULL_REQUEST_TEMPLATE.md"
        return 0
    fi
    if [ -f ".github/pull_request_template.md" ]; then
        echo ".github/pull_request_template.md"
        return 0
    fi
    if [ -f "docs/PR_TEMPLATE.md" ]; then
        echo "docs/PR_TEMPLATE.md"
        return 0
    fi
    if [ -n "${BASE_DIR:-}" ] && [ -f "${BASE_DIR}/utils/templates/pr-body-default.md" ]; then
        echo "${BASE_DIR}/utils/templates/pr-body-default.md"
        return 0
    fi
    return 1
}

read_main_task_content() {
    local file="MAIN_TASK.md"
    if [ -f "$file" ] && grep -q '[^[:space:]]' "$file"; then
        cat "$file"
        return 0
    fi
    return 1
}

read_main_task_title() {
    local file="MAIN_TASK.md"
    if [ ! -f "$file" ]; then
        return 1
    fi
    local line=""
    line=$(awk 'NF {print; exit}' "$file" 2>/dev/null || true)
    line=$(trim "$line")
    line=$(printf "%s" "$line" | sed -E 's/^#+[[:space:]]*//')
    line=$(trim "$line")
    if [ -n "$line" ]; then
        echo "$line"
        return 0
    fi
    return 1
}

apply_main_task_to_body() {
    local out_file=$1
    local main_task=""
    local has_main_task=false
    if main_task=$(read_main_task_content); then
        has_main_task=true
    fi

    if grep -q "{{MAIN_TASK}}" "$out_file"; then
        replace_placeholder "$out_file" "{{MAIN_TASK}}" "$main_task" "${out_file}.tmp"
        mv "${out_file}.tmp" "$out_file"
        return 0
    fi

    if [ "$has_main_task" = true ]; then
        {
            printf "\n\n## Main Task\n\n"
            printf "%s\n" "$main_task"
        } >> "$out_file"
    fi
}

build_pr_body_file() {
    local base_ref=$1
    local head_ref=$2
    local out_file=$3
    local body=$4
    local body_file=$5
    local template_file=$6
    local include_commits=${7:-true}

    if [ -n "$body_file" ]; then
        cp "$body_file" "$out_file"
        return 0
    fi

    if [ -n "$body" ]; then
        printf "%s\n" "$body" > "$out_file"
        return 0
    fi

    local commits=""
    if [ "$include_commits" = true ]; then
        commits=$(build_commit_list "$base_ref" "$head_ref")
    fi

    local template
    if template=$(find_template_file "$template_file"); then
        if grep -q "{{COMMITS}}" "$template"; then
            replace_placeholder "$template" "{{COMMITS}}" "$commits" "$out_file"
        else
            cat "$template" > "$out_file"
            if [ -n "$commits" ]; then
                printf "\n\n## Changes\n%s\n" "$commits" >> "$out_file"
            fi
        fi
        return 0
    fi

    {
        echo "## Description"
        echo ""
        echo "## Changes"
        if [ -n "$commits" ]; then
            echo "$commits"
        else
            echo "-"
        fi
        echo ""
        echo "## Testing"
        echo "- [ ] Not run (explain why)"
    } > "$out_file"
}

prompt_commit_message() {
    local message=""
    if [ -e /dev/tty ]; then
        printf "Enter commit message: " > /dev/tty
        read -r message < /dev/tty || true
    fi
    message=$(trim "$message")
    if [ -n "$message" ]; then
        printf "%s" "$message"
        return 0
    fi
    return 1
}

commit_unstaged_changes() {
    local message_file=${1:-MAIN_TASK.md}

    local status
    status=$(git status --porcelain)
    if [ -z "$status" ]; then
        return 0
    fi

    git add -A
    if git diff --cached --quiet; then
        return 0
    fi

    if [ -f "$message_file" ] && grep -q '[^[:space:]]' "$message_file"; then
        echo -e "${CYAN}Committing changes using ${message_file}...${NC}"
        git commit -F "$message_file"
        return 0
    fi

    local message=""
    if message=$(prompt_commit_message); then
        echo -e "${CYAN}Committing changes...${NC}"
        git commit -m "$message"
        return 0
    fi

    echo -e "${RED}${message_file} is missing or empty and no commit message provided.${NC}"
    return 1
}

pr_status_for_branch() {
    local branch=$1
    if [ "${HAS_GH:-false}" != true ] || [ -z "$branch" ]; then
        echo ""
        return 0
    fi

    local now
    now=$(date +%s)
    local cached_ts=${PR_STATUS_CACHE_TS[$branch]:-0}
    if [ $((now - cached_ts)) -lt "${PR_STATUS_TTL:-30}" ]; then
        echo "${PR_STATUS_CACHE[$branch]:-}"
        return 0
    fi

    local status
    status=$(gh pr list --head "$branch" --state all --json state --jq '.[0].state' 2>/dev/null || true)
    PR_STATUS_CACHE_TS[$branch]=$now
    if [ -z "$status" ]; then
        PR_STATUS_CACHE[$branch]=""
        echo ""
        return 0
    fi
    if [ "$status" = "OPEN" ]; then
        PR_STATUS_CACHE[$branch]="open"
    elif [ "$status" = "MERGED" ]; then
        PR_STATUS_CACHE[$branch]="merged"
    elif [ "$status" = "CLOSED" ]; then
        PR_STATUS_CACHE[$branch]="closed"
    else
        PR_STATUS_CACHE[$branch]=""
    fi
    echo "${PR_STATUS_CACHE[$branch]}"
}

pr_url_for_branch() {
    local branch=$1
    if [ -z "$branch" ]; then
        return 1
    fi

    local url=""
    if [ "${HAS_GH:-false}" = true ]; then
        url=$(gh pr list --head "$branch" --state all --json url --jq '.[0].url' 2>/dev/null || true)
    fi
    if [ -n "$url" ]; then
        echo "$url"
        return 0
    fi

    local remote="${PR_REMOTE:-origin}"
    local origin_url
    origin_url=$(git -C "${BASE_DIR:-.}" config --get remote."$remote".url 2>/dev/null || true)
    if [ -n "$origin_url" ]; then
        local slug=""
        if slug=$(extract_repo_slug "$origin_url"); then
            local base_branch="${PR_BASE_BRANCH:-$(default_pr_base_branch)}"
            echo "https://github.com/${slug}/compare/${base_branch}...${branch}?expand=1"
            return 0
        fi
    fi

    return 1
}

pr_url_for_branch_if_exists() {
    local branch=$1
    if [ -z "$branch" ]; then
        return 1
    fi
    if [ "${HAS_GH:-false}" = true ]; then
        gh pr list --head "$branch" --state all --json url --jq '.[0].url' 2>/dev/null || true
    fi
    return 0
}

pr_label_for_project() {
    local project_name=$1
    local root
    root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
    if [ -z "$root" ]; then
        echo ""
        return 0
    fi
    local branch
    branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
        echo ""
        return 0
    fi
    local label=""
    local cwd="$PWD"
    if cd "$root" 2>/dev/null; then
        label=$(pr_status_for_branch "$branch")
        cd "$cwd" 2>/dev/null || true
    fi
    echo "$label"
}

pr_info_for_project() {
    local project_name=$1
    local root
    root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
    if [ -z "$root" ]; then
        printf '%s|%s\n' "" ""
        return 0
    fi
    local branch
    branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
        printf '%s|%s\n' "" ""
        return 0
    fi
    local label=""
    local url=""
    label=$(pr_status_for_branch "$branch")
    url=$(pr_url_for_branch_if_exists "$branch" 2>/dev/null || true)
    printf '%s|%s\n' "$label" "$url"
}

pr_url_for_project() {
    local project_name=$1
    local root
    root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
    if [ -z "$root" ]; then
        echo ""
        return 0
    fi
    local branch
    branch=$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
        echo ""
        return 0
    fi
    local url=""
    local cwd="$PWD"
    if cd "$root" 2>/dev/null; then
        url=$(pr_url_for_branch_if_exists "$branch")
        cd "$cwd" 2>/dev/null || true
    fi
    if [ -n "$url" ]; then
        echo "$url"
        return 0
    fi
    echo ""
    return 0
}

read_main_task_message() {
    local workdir=$1
    local file="$workdir/MAIN_TASK.md"
    if [ -f "$file" ] && grep -q '[^[:space:]]' "$file"; then
        echo "$file"
        return 0
    fi
    return 1
}

read_tree_changelog_message() {
    local workdir=$1
    local identity=""
    identity=$(worktree_identity_from_dir "$workdir" "${BASE_DIR:-}" "${TREES_DIR_NAME:-trees}" 2>/dev/null || true)
    local tree_name="main"
    if [ -n "$identity" ]; then
        local feature iter
        IFS='|' read -r feature iter <<< "$identity"
        if [ -n "$feature" ] && [ -n "$iter" ]; then
            tree_name="${feature}-${iter}"
        fi
    fi
    local changelog_dir="$workdir/docs/changelog"
    local file="$changelog_dir/${tree_name}_changelog.md"
    if [ -f "$file" ] && grep -q '[^[:space:]]' "$file"; then
        echo "$file"
        return 0
    fi
    return 1
}

commit_paths() {
    local label=$1
    shift
    local paths=("$@")

    if [ ${#paths[@]} -eq 0 ]; then
        echo -e "${RED}No worktrees selected for commit.${NC}"
        return 1
    fi

    local remote="${PR_REMOTE:-origin}"
    local committed=0
    local skipped=0
    local failed=0
    local summary_entries=()
    local commit_message_override="${COMMIT_MESSAGE_OVERRIDE:-}"
    local commit_message_file_override="${COMMIT_MESSAGE_FILE_OVERRIDE:-}"

    if [ -n "$label" ]; then
        echo -e "${CYAN}Committing changes for ${label}...${NC}"
    else
        echo -e "${CYAN}Committing changes...${NC}"
    fi

    declare -A seen_paths=()
    local tree_dir
    for tree_dir in "${paths[@]}"; do
        [ -n "$tree_dir" ] || { ((skipped++)); continue; }
        if [ -n "${seen_paths[$tree_dir]:-}" ]; then
            continue
        fi
        seen_paths["$tree_dir"]=1
        [ -d "$tree_dir" ] || { ((skipped++)); continue; }

        local branch
        branch=$(git -C "$tree_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
        if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
            echo -e "${YELLOW}Skipping ${tree_dir} (detached HEAD)${NC}"
            ((skipped++))
            continue
        fi

        echo -e "${BLUE}→ Commit for ${branch}${NC}"
        if ! git -C "$tree_dir" add -A; then
            echo -e "${RED}Failed to stage changes for ${branch}${NC}"
            ((failed++))
            continue
        fi

        if git -C "$tree_dir" diff --cached --quiet; then
            echo -e "${YELLOW}No changes to commit for ${branch}${NC}"
            ((skipped++))
            continue
        fi

        local commit_message=""
        local message_file=""
        if [ -n "$commit_message_override" ]; then
            commit_message="$commit_message_override"
        elif [ -n "$commit_message_file_override" ]; then
            if [ -f "$commit_message_file_override" ] && grep -q '[^[:space:]]' "$commit_message_file_override"; then
                message_file="$commit_message_file_override"
            else
                echo -e "${RED}Commit message file is missing or empty: ${commit_message_file_override}${NC}"
                ((failed++))
                continue
            fi
        elif message_file=$(read_tree_changelog_message "$tree_dir"); then
            commit_message=""
        elif message_file=$(read_main_task_message "$tree_dir"); then
            commit_message=""
        elif [ "${INTERACTIVE_MODE:-true}" = true ] && commit_message=$(prompt_commit_message); then
            message_file=""
        else
            echo -e "${RED}MAIN_TASK.md is missing or empty and no commit message provided for ${branch}.${NC}"
            ((failed++))
            continue
        fi

        if [ -n "$commit_message" ]; then
            if ! git -C "$tree_dir" commit -m "$commit_message"; then
                echo -e "${RED}Commit failed for ${branch}${NC}"
                ((failed++))
                continue
            fi
        else
            if ! git -C "$tree_dir" commit -F "$message_file"; then
                echo -e "${RED}Commit failed for ${branch}${NC}"
                ((failed++))
                continue
            fi
        fi

        if git -C "$tree_dir" push -u "$remote" "$branch"; then
            ((committed++))
            summary_entries+=("$branch")
        else
            echo -e "${RED}Push failed for ${branch}${NC}"
            ((failed++))
        fi
    done

    echo -e "${GREEN}Commits pushed:${NC} ${committed}  ${YELLOW}Skipped:${NC} ${skipped}  ${RED}Failed:${NC} ${failed}"
    if [ ${#summary_entries[@]} -gt 0 ]; then
        echo -e "${CYAN}Branches pushed:${NC}"
        local entry
        for entry in "${summary_entries[@]}"; do
            echo -e "  ${BLUE}${entry}${NC}"
        done
    fi
    if [ "$failed" -gt 0 ]; then
        return 1
    fi
    return 0
}

create_prs_for_paths() {
    local label=$1
    local show_summary=${2:-false}
    shift
    shift
    local paths=("$@")

    local create_script="${BASE_DIR:-.}/utils/create-pr.sh"
    if [ ! -x "$create_script" ]; then
        echo -e "${RED}PR helper not found or not executable: $create_script${NC}"
        return 1
    fi

    if [ ${#paths[@]} -eq 0 ]; then
        echo -e "${RED}No worktrees selected for PR creation.${NC}"
        return 1
    fi

    local base_arg=()
    if [ -n "${PR_BASE_BRANCH:-}" ]; then
        base_arg=(--base "$PR_BASE_BRANCH")
    fi

    local created=0
    local skipped=0
    local failed=0
    local summary_entries=()

    if [ -n "$label" ]; then
        echo -e "${CYAN}Creating PRs for ${label}...${NC}"
    else
        echo -e "${CYAN}Creating PRs...${NC}"
    fi

    declare -A seen_paths=()
    local tree_dir
    for tree_dir in "${paths[@]}"; do
        [ -n "$tree_dir" ] || { ((skipped++)); continue; }
        if [ -n "${seen_paths[$tree_dir]:-}" ]; then
            continue
        fi
        seen_paths["$tree_dir"]=1
        [ -d "$tree_dir" ] || { ((skipped++)); continue; }
        local branch
        branch=$(git -C "$tree_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
        if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
            echo -e "${YELLOW}Skipping ${tree_dir} (detached HEAD)${NC}"
            ((skipped++))
            continue
        fi

        echo -e "${BLUE}→ PR for ${branch}${NC}"
        local pr_output=""
        local pr_status=0
        if [ -e /dev/tty ]; then
            pr_output=$("$create_script" "${base_arg[@]}" --head "$branch" --workdir "$tree_dir" 2>&1 | tee /dev/tty)
            pr_status=${PIPESTATUS[0]}
        else
            pr_output=$("$create_script" "${base_arg[@]}" --head "$branch" --workdir "$tree_dir" 2>&1)
            pr_status=$?
            printf "%s\n" "$pr_output"
        fi

        if [ "$pr_status" -eq 0 ]; then
            ((created++))
            if [ "$show_summary" = true ]; then
                local pr_url=""
                pr_url=$(printf '%s\n' "$pr_output" | grep -Eo 'https?://[^ ]+/pull/[0-9]+' | tail -n 1)
                if [ -z "$pr_url" ]; then
                    pr_url=$(pr_url_for_branch "$branch" 2>/dev/null || true)
                fi
                summary_entries+=("${branch}|${pr_url}")
            fi
        else
            ((failed++))
        fi
    done

    echo -e "${GREEN}PRs created:${NC} ${created}  ${YELLOW}Skipped:${NC} ${skipped}  ${RED}Failed:${NC} ${failed}"
    if [ "$show_summary" = true ] && [ ${#summary_entries[@]} -gt 0 ]; then
        echo -e "${CYAN}PR URLs:${NC}"
        local entry
        for entry in "${summary_entries[@]}"; do
            IFS='|' read -r branch url <<< "$entry"
            if [ -n "$url" ]; then
                echo -e "  ${BLUE}${branch}:${NC} $url"
            else
                echo -e "  ${BLUE}${branch}:${NC} ${YELLOW}(URL unavailable)${NC}"
            fi
        done
    fi
    if [ "$failed" -gt 0 ]; then
        return 1
    fi
    return 0
}

create_prs_for_planning_paths() {
    if [ ${#TREES_TARGET_PATHS[@]} -eq 0 ]; then
        echo -e "${RED}No planning worktrees selected for PR creation.${NC}"
        return 1
    fi
    create_prs_for_paths "selected planning worktrees" false "${TREES_TARGET_PATHS[@]}"
}

prompt_pr_base_branch() {
    local default_branch
    default_branch=$(default_pr_base_branch)

    if [ -n "${PR_BASE_BRANCH:-}" ]; then
        echo "$PR_BASE_BRANCH"
        return 0
    fi

    if [ -e /dev/tty ]; then
        printf "Base branch for PRs (default: %s): " "$default_branch" > /dev/tty
        local input=""
        read -r input < /dev/tty || true
        input=$(trim "$input")
        if [ -z "$input" ]; then
            input="$default_branch"
        fi
        if ! pr_branch_exists "$input"; then
            printf "${YELLOW}⚠ Base branch '%s' not found; using %s.${NC}\n" "$input" "$default_branch" > /dev/tty
            input="$default_branch"
        fi
        echo "$input"
        return 0
    fi

    echo "$default_branch"
}
