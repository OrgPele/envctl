#!/usr/bin/env bash

# Analysis helpers.

resolve_analysis_selection() {
    local selection=$1
    ANALYSIS_SCOPE="all"
    ANALYSIS_PROJECTS=()

    if [ "$selection" = "__ALL__" ]; then
        while IFS= read -r project; do
            [ -n "$project" ] && ANALYSIS_PROJECTS+=("$project")
        done < <(get_project_names)
        return 0
    fi

    if [[ "$selection" == "__PROJECT__:"* ]]; then
        ANALYSIS_PROJECTS+=("${selection#__PROJECT__:}")
        return 0
    fi

    if [[ "$selection" == *" Backend" ]]; then
        ANALYSIS_SCOPE="backend"
        ANALYSIS_PROJECTS+=("${selection% Backend}")
        return 0
    fi

    if [[ "$selection" == *" Frontend" ]]; then
        ANALYSIS_SCOPE="frontend"
        ANALYSIS_PROJECTS+=("${selection% Frontend}")
        return 0
    fi

    ANALYSIS_PROJECTS+=("$selection")
}


list_project_iterations() {
    local project_dir=$1
    local iterations=()
    if [ -d "$project_dir" ]; then
        for iter_dir in "$project_dir"/*/; do
            [ -d "$iter_dir" ] || continue
            if [ -f "$iter_dir/.git" ] || [ -d "$iter_dir/.git" ]; then
                iterations+=("$(basename "$iter_dir")")
            fi
        done
    fi
    printf '%s\n' "${iterations[@]}"
}


analysis_selection_has_multiple_iterations() {
    local project
    for project in "${ANALYSIS_PROJECTS[@]}"; do
        local project_dir="$BASE_DIR/$TREES_DIR_NAME/$project"
        local iterations=()

        if [ -d "$project_dir" ]; then
            while IFS= read -r iter; do
                [ -n "$iter" ] && iterations+=("$iter")
            done < <(list_project_iterations "$project_dir")
        fi

        if [ ${#iterations[@]} -eq 0 ]; then
            local root
            root=$(project_root_from_project_name "$project" 2>/dev/null || true)
            if [ -n "$root" ]; then
                project_dir=$(dirname "$root")
                iterations=("$(basename "$root")")
            fi
        fi

        if [ ${#iterations[@]} -gt 1 ]; then
            return 0
        fi
    done

    return 1
}


run_tree_change_analysis() {
    local selection=$1
    local mode=$2
    resolve_analysis_selection "$selection"
    local scope="$ANALYSIS_SCOPE"
    local projects=("${ANALYSIS_PROJECTS[@]}")

    if [ ${#projects[@]} -eq 0 ]; then
        echo -e "${YELLOW}No projects found for analysis${NC}"
        return 1
    fi

    local analyze_script="$BASE_DIR/utils/analyze-tree-changes.sh"
    if [ ! -f "$analyze_script" ]; then
        echo -e "${RED}analyze-tree-changes.sh not found at $analyze_script${NC}"
        return 1
    fi

    local outputs=()
    local project
    for project in "${projects[@]}"; do
        local project_dir="$BASE_DIR/$TREES_DIR_NAME/$project"
        local iterations=()

        if [ "$mode" = "grouped" ]; then
            while IFS= read -r iter; do
                [ -n "$iter" ] && iterations+=("$iter")
            done < <(list_project_iterations "$project_dir")
        fi

        if [ ${#iterations[@]} -eq 0 ]; then
            local root
            root=$(project_root_from_project_name "$project" 2>/dev/null || true)
            if [ -n "$root" ]; then
                project_dir=$(dirname "$root")
                iterations=("$(basename "$root")")
            fi
        fi

        if [ ${#iterations[@]} -eq 0 ] && [ -d "$project_dir" ]; then
            while IFS= read -r iter; do
                [ -n "$iter" ] && iterations+=("$iter")
            done < <(list_project_iterations "$project_dir")
        fi

        if [ ${#iterations[@]} -eq 0 ]; then
            echo -e "${YELLOW}No tree iterations found for ${project}${NC}"
            continue
        fi

        if [ "$mode" = "single" ] && [ ${#iterations[@]} -gt 1 ]; then
            iterations=("${iterations[0]}")
        fi

        local approach="optimal"
        local extra_args=()
        if [ "$mode" = "grouped" ] && [ ${#iterations[@]} -gt 1 ]; then
            approach="combine"
        else
            extra_args+=("security-check=true" "performance-check=true")
        fi

        local trees_csv
        trees_csv=$(IFS=','; echo "${iterations[*]}")
        local ts
        ts=$(date +"%Y%m%d_%H%M%S")
        local safe_project
        safe_project=$(sanitize_label "$project")
        local safe_scope
        safe_scope=$(sanitize_label "$scope")
        local output_dir="tree-diffs/analysis_${safe_project}_${safe_scope}_${mode}_${ts}"

        local args=("trees=$trees_csv" "approach=$approach" "output-dir=$output_dir")
        if [ "$scope" != "all" ]; then
            args+=("scope=$scope")
        fi
        if [ ${#extra_args[@]} -gt 0 ]; then
            args+=("${extra_args[@]}")
        fi

        echo -e "${CYAN}Analyzing ${project} (${scope}, ${mode})...${NC}"
        BASE_DIR="$BASE_DIR" BACKEND_DIR_NAME="$BACKEND_DIR_NAME" FRONTEND_DIR_NAME="$FRONTEND_DIR_NAME" TREES_DIR_NAME="$project_dir" "$analyze_script" "${args[@]}"

        outputs+=("$BASE_DIR/$output_dir/all.md")
    done

    if [ ${#outputs[@]} -gt 0 ]; then
        echo -e "${GREEN}✓ Analysis complete. Files:${NC}"
        printf '  - %s\n' "${outputs[@]}"
    fi
}

analysis_init_config() {
    SPECIFIC_TREES=""
    BASE_BRANCH="dev"
    INCLUDE_UNCOMMITTED=true
    VERBOSE_MODE=false
    CONTEXT_LINES=3
    EXCLUDE_LOCK_FILES=true
    MD_ONLY=false

    APPROACH="optimal"
    VALIDATE_TESTS=true
    VALIDATE_REQUIREMENTS=true
    MERGE_PLAN=true
    SECURITY_CHECK=false
    PERFORMANCE_CHECK=false
    ORIGINAL_REQUEST_FILE=""
    DEFECT_REPORT_FILE=""
    SCOPE="all"
    PATH_FILTER=""
    OUTPUT_DIR_OVERRIDE=""

    BACKEND_DIR_NAME="${BACKEND_DIR_NAME:-backend}"
    FRONTEND_DIR_NAME="${FRONTEND_DIR_NAME:-frontend}"
    TREES_DIR_NAME="${TREES_DIR_NAME:-trees}"
    SHOW_HELP=false
}

analysis_show_help() {
    local script_name=${1:-$(basename "$0")}
    cat << EOF
Directory Changes Analyzer

Analyzes git changes (committed and uncommitted) in tree directories
and generates an LLM-optimized evaluation prompt following Claude Code best practices.

USAGE:
    ${script_name} [OPTIONS]

OPTIONS:
    --help, -h                    Show this help message
    --tree=N                      Analyze specific tree (e.g., --tree=1)
    --trees=N,M,O                 Analyze specific trees (e.g., --trees=1,2,3)
    --base=BRANCH                 Compare against BRANCH (default: dev)
    --uncommitted=false           Exclude uncommitted/staged changes
    --include-all=true            Include lock files and build artifacts
    --md-only=true, --md-only     Only analyze markdown files (shows list of excluded files)
    --verbose=true, -v            Show detailed output
    --context=N                   Number of context lines in diffs (default: 3)

    Analysis Options:
    --approach=optimal|combine    Choose analysis approach (default: optimal)
                                 optimal: Find the best single tree implementation
                                 combine: Combine best parts from multiple trees
    --validate-tests=true|false   Validate testing & breaking changes (default: true)
    --validate-requirements=true|false  Validate requirements & fix gaps (default: true)
    --merge-plan=true|false       Provide merge execution plan (default: true)
    --security-check=true|false   Security vulnerability assessment (default: false)
    --performance-check=true|false  Performance analysis (default: false)
    --original-request=FILE       Path to file containing original request/plan (optional)
    --scope=all|backend|frontend  Limit analysis to backend or frontend changes (default: all)
    --path-filter=PATH            Limit analysis to a specific path (overrides --scope)
    --output-dir=DIR              Write results to DIR (default: tree-diffs/analysis_TIMESTAMP)

    Note: All options also work without -- prefix (e.g., tree=1, md-only=true)

    Directory Configuration:
    TREES_DIR_NAME=my-trees             Custom trees directory name (default: trees)

EXAMPLES:
    ${script_name}                     # Analyze all trees
    ${script_name} --tree=1            # Analyze only tree 1
    ${script_name} --trees=1,2,3       # Analyze trees 1, 2, and 3
    ${script_name} --base=main         # Compare against main branch
    ${script_name} --md-only           # Only analyze markdown files
    ${script_name} --md-only=true      # Also works with =true
    ${script_name} --uncommitted=false # Only show committed changes

    Advanced Analysis Examples:
    ${script_name} --approach=combine --merge-plan=true  # Find best combination
    ${script_name} --security-check=true --performance-check=true  # Full audit
    ${script_name} --validate-tests=false --merge-plan=false  # Quick review
    ${script_name} --original-request=docs/plan.md --approach=optimal  # Include original plan

    Directory Configuration Examples:
    TREES_DIR_NAME=worktrees ${script_name}   # Use worktrees directory
    TREES_DIR_NAME=my-trees ${script_name} --tree=1  # Custom directory with specific tree

OUTPUT:
    Results are saved to tree-diffs/analysis_TIMESTAMP/
    - Individual tree changes in implementation-<name>/ subdirectories
    - Prompt file as prompt.md
    - All-in-one file as all.md (prompt + summary + docs + changes)
    - Root docs copied to context_docs/ (docs/*.md)
    - Summary file with quick statistics (summary_short.txt)

NOTES:
    - By default, excludes lock files and untracked files ignored by git
    - By default, includes both committed and uncommitted changes
    - Automatically handles git worktrees
    - Token estimation: ~1 token per 4 characters
EOF
}

analysis_parse_args() {
    local arg
    for arg in "$@"; do
        case $arg in
            --help|-h|help)
                SHOW_HELP=true
                ;;
            tree=*|--tree=*)
                SPECIFIC_TREES="${arg#*tree=}"
                ;;
            trees=*|--trees=*)
                SPECIFIC_TREES="${arg#*trees=}"
                ;;
            base=*|--base=*)
                BASE_BRANCH="${arg#*base=}"
                ;;
            uncommitted=false|--uncommitted=false|UNCOMMITTED=false)
                INCLUDE_UNCOMMITTED=false
                ;;
            verbose=true|--verbose=true|VERBOSE=true|v=true|-v|--verbose)
                VERBOSE_MODE=true
                ;;
            context=*|--context=*)
                CONTEXT_LINES="${arg#*context=}"
                ;;
            include-all=true|--include-all=true|INCLUDE_ALL=true)
                EXCLUDE_LOCK_FILES=false
                ;;
            md-only=true|--md-only=true|MD_ONLY=true|markdown-only=true|--markdown-only=true|MARKDOWN_ONLY=true)
                MD_ONLY=true
                ;;
            --md-only|--markdown-only)
                MD_ONLY=true
                ;;
            approach=*|--approach=*)
                APPROACH="${arg#*approach=}"
                ;;
            validate-tests=*|--validate-tests=*)
                VALIDATE_TESTS="${arg#*validate-tests=}"
                ;;
            validate-requirements=*|--validate-requirements=*)
                VALIDATE_REQUIREMENTS="${arg#*validate-requirements=}"
                ;;
            merge-plan=*|--merge-plan=*)
                MERGE_PLAN="${arg#*merge-plan=}"
                ;;
            security-check=*|--security-check=*)
                SECURITY_CHECK="${arg#*security-check=}"
                ;;
            performance-check=*|--performance-check=*)
                PERFORMANCE_CHECK="${arg#*performance-check=}"
                ;;
            original-request=*|--original-request=*)
                ORIGINAL_REQUEST_FILE="${arg#*original-request=}"
                ;;
            scope=*|--scope=*)
                SCOPE="${arg#*scope=}"
                ;;
            path-filter=*|--path-filter=*|path=*|--path=*)
                PATH_FILTER="${arg#*=}"
                ;;
            output-dir=*|--output-dir=*|output=*|--output=*)
                OUTPUT_DIR_OVERRIDE="${arg#*=}"
                ;;
        esac
    done
}

analysis_set_base_dir() {
    local script_dir=$1
    BASE_DIR="${BASE_DIR:-$script_dir}"
}

analysis_resolve_scope_filter() {
    if [ -z "$PATH_FILTER" ]; then
        case "$SCOPE" in
            backend)
                PATH_FILTER="$BACKEND_DIR_NAME"
                ;;
            frontend)
                PATH_FILTER="$FRONTEND_DIR_NAME"
                ;;
            all|"")
                ;;
            *)
                echo -e "${YELLOW}Unknown scope '$SCOPE'; defaulting to all${NC}"
                ;;
        esac
    fi

    PATHSPEC_ARGS=()
    if [ -n "$PATH_FILTER" ]; then
        PATHSPEC_ARGS=(-- "$PATH_FILTER")
    fi
}

analysis_prepare_output_dir() {
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    if [ -n "$OUTPUT_DIR_OVERRIDE" ]; then
        if [[ "$OUTPUT_DIR_OVERRIDE" = /* ]]; then
            OUTPUT_DIR="$OUTPUT_DIR_OVERRIDE"
        else
            OUTPUT_DIR="$BASE_DIR/$OUTPUT_DIR_OVERRIDE"
        fi
    else
        OUTPUT_DIR="$BASE_DIR/tree-diffs/analysis_$timestamp"
    fi
    mkdir -p "$OUTPUT_DIR"
    SAFE_BASE_BRANCH="${BASE_BRANCH//\//_}"
}

analysis_ensure_base_dir() {
    if [ -d "$BASE_DIR/$TREES_DIR_NAME" ]; then
        return 0
    fi

    local parent
    parent=$(dirname "$BASE_DIR")
    if [ -d "$parent/$TREES_DIR_NAME" ]; then
        BASE_DIR="$parent"
    fi
}

# analyze-tree-changes helpers (expect globals from analyze-tree-changes.sh)

get_grep_exclusions() {
    # Base exclusions for lock files and build artifacts
    local pattern="(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lock|poetry\.lock|Pipfile\.lock|composer\.lock|Gemfile\.lock|Cargo\.lock|go\.sum|\.min\.js$|\.min\.css$|\.bundle\.js$|\.chunk\.js$|\.map$|\.log$|\.cache$|\.DS_Store|thumbs\.db|\.pyc$|\.class$|\.o$|\.so$|__pycache__|/dist/|/build/|/coverage/|/node_modules/)"
    echo "$pattern"
}

analysis_should_include_file() {
    local file=$1
    local exclusion_pattern=$2

    if [ "$MD_ONLY" = true ] && [[ "$file" != *.md ]]; then
        return 1
    fi
    if [ -n "$exclusion_pattern" ] && [[ "$file" =~ $exclusion_pattern ]]; then
        return 1
    fi
    return 0
}

analysis_filter_files() {
    local -n input_files=$1
    local -n output_files=$2
    local exclusion_pattern=$3
    local file

    output_files=()
    for file in "${input_files[@]}"; do
        if analysis_should_include_file "$file" "$exclusion_pattern"; then
            output_files+=("$file")
        fi
    done
}

analysis_write_name_status_list() {
    local output_file=$1
    shift
    local -a cmd=("$@")
    local status=""
    local path=""
    local old_path=""

    : > "$output_file"
    while IFS= read -r -d '' status; do
        case "$status" in
            R*|C*)
                IFS= read -r -d '' old_path || break
                IFS= read -r -d '' path || break
                printf '%s\t%s\t%s\n' "$status" "$old_path" "$path" >> "$output_file"
                ;;
            *)
                IFS= read -r -d '' path || break
                printf '%s\t%s\n' "$status" "$path" >> "$output_file"
                ;;
        esac
    done < <("${cmd[@]}" 2>/dev/null)
}

analysis_extract_paths_from_status_list() {
    local list_file=$1
    [ -f "$list_file" ] || return 0

    while IFS= read -r line; do
        [ -n "$line" ] || continue
        local file="${line#*$'\t'}"
        file="${file##*$'\t'}"
        printf '%s\n' "$file"
    done < "$list_file"
}

analysis_extract_non_md_files() {
    local list_file=$1
    local -a files=()
    local file

    while IFS= read -r file; do
        [ -n "$file" ] || continue
        if [[ "$file" != *.md ]]; then
            files+=("$file")
        fi
    done < <(analysis_extract_paths_from_status_list "$list_file")

    if [ ${#files[@]} -gt 0 ]; then
        printf '%s\n' "${files[@]}" | sort -u
    fi
}

analyze_tree_changes() {
    local name=$1
    local dir=$2

    echo -e "\n${CYAN}Analyzing Tree $name...${NC}"

    if [ ! -d "$dir" ]; then
        echo -e "${RED}Directory not found: $dir${NC}"
        return 1
    fi

    # Check if it's a git repository or worktree
    if ! git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo -e "${YELLOW}Not a git repository: $dir${NC}"
        return 1
    fi

    local git_cmd=("git" "-C" "$dir")
    local exclusion_pattern=""
    if [ "$EXCLUDE_LOCK_FILES" = true ]; then
        exclusion_pattern=$(get_grep_exclusions)
    fi

    # Get current branch
    local current_branch
    current_branch=$("${git_cmd[@]}" branch --show-current 2>/dev/null || echo "unknown")
    tree_branches["$name"]="$current_branch"
    tree_dirs["$name"]="$dir"
    echo -e "${BLUE}Current branch: $current_branch${NC}"

    local git_state=""
    git_state=$(git_state_for_dir "$dir" 2>/dev/null || true)
    if [ -n "$git_state" ]; then
        IFS='|' read -r git_head git_status_hash git_status_lines <<< "$git_state"
        tree_git_head["$name"]="$git_head"
        tree_git_status_hash["$name"]="$git_status_hash"
        tree_git_status_lines["$name"]="$git_status_lines"
    fi

    local main_task_file="${dir%/}/MAIN_TASK.md"
    if [ -s "$main_task_file" ]; then
        tree_main_task_files["$name"]="$main_task_file"
    fi

    # Create tree-specific directory
    local tree_dir="$OUTPUT_DIR/implementation-$name"
    local diff_dir="$tree_dir/diffs"
    local list_dir="$tree_dir/lists"
    mkdir -p "$diff_dir" "$list_dir"

    local has_changes=false

    # Check uncommitted changes if requested
    if [ "$INCLUDE_UNCOMMITTED" = true ]; then
        # Check for any uncommitted changes (modified, staged, or untracked)
        local has_uncommitted=false

        # Check unstaged changes
        local unstaged_stats=$("${git_cmd[@]}" diff --shortstat "${PATHSPEC_ARGS[@]}" 2>/dev/null || echo "")
        if [ -n "$unstaged_stats" ]; then
            echo -e "${YELLOW}Unstaged changes: $unstaged_stats${NC}"
            has_uncommitted=true
            has_changes=true

            # Save unstaged changes
            local -a changed_files=()
            mapfile -d '' -t changed_files < <("${git_cmd[@]}" diff --name-only -z "${PATHSPEC_ARGS[@]}" 2>/dev/null)

            # Save original file list before filtering
            analysis_write_name_status_list "$list_dir/all_unstaged.list" "${git_cmd[@]}" diff --name-status -z "${PATHSPEC_ARGS[@]}"

            # Apply filters
            local -a filtered_changed_files=()
            analysis_filter_files changed_files filtered_changed_files "$exclusion_pattern"

            if [ ${#filtered_changed_files[@]} -gt 0 ]; then
                # Generate diff only for filtered files
                "${git_cmd[@]}" diff -U$CONTEXT_LINES -- "${filtered_changed_files[@]}" > "$diff_dir/unstaged.patch" 2>&1
                analysis_write_name_status_list "$list_dir/unstaged.list" "${git_cmd[@]}" diff --name-status -z -- "${filtered_changed_files[@]}"
            else
                echo "No changes after filtering" > "$diff_dir/unstaged.patch"
                : > "$list_dir/unstaged.list"
            fi
        fi

        # Check staged changes
        local staged_stats=$("${git_cmd[@]}" diff --cached --shortstat "${PATHSPEC_ARGS[@]}" 2>/dev/null || echo "")
        if [ -n "$staged_stats" ]; then
            echo -e "${MAGENTA}Staged changes: $staged_stats${NC}"
            has_uncommitted=true
            has_changes=true

            # Save staged changes
            local -a staged_files=()
            mapfile -d '' -t staged_files < <("${git_cmd[@]}" diff --cached --name-only -z "${PATHSPEC_ARGS[@]}" 2>/dev/null)

            # Save original file list before filtering
            analysis_write_name_status_list "$list_dir/all_staged.list" "${git_cmd[@]}" diff --cached --name-status -z "${PATHSPEC_ARGS[@]}"

            # Apply filters
            local -a filtered_staged_files=()
            analysis_filter_files staged_files filtered_staged_files "$exclusion_pattern"

            if [ ${#filtered_staged_files[@]} -gt 0 ]; then
                # Generate diff only for filtered files
                "${git_cmd[@]}" diff --cached -U$CONTEXT_LINES -- "${filtered_staged_files[@]}" > "$diff_dir/staged.patch" 2>&1
                analysis_write_name_status_list "$list_dir/staged.list" "${git_cmd[@]}" diff --cached --name-status -z -- "${filtered_staged_files[@]}"
            else
                echo "No changes after filtering" > "$diff_dir/staged.patch"
                : > "$list_dir/staged.list"
            fi
        fi

        # Check untracked files
        local -a untracked_files=()
        while IFS= read -r -d '' file; do
            untracked_files+=("$file")
        done < <("${git_cmd[@]}" ls-files --others --exclude-standard -z "${PATHSPEC_ARGS[@]}" 2>/dev/null)

        # Save original list before filtering
        printf '%s\n' "${untracked_files[@]}" > "$list_dir/all_untracked.list"

        if [ ${#untracked_files[@]} -gt 0 ]; then
            local -a filtered_untracked=()
            analysis_filter_files untracked_files filtered_untracked "$exclusion_pattern"
            untracked_files=("${filtered_untracked[@]}")
        fi

        local untracked_count=${#untracked_files[@]}
        if [ "$untracked_count" -gt 0 ]; then
            echo -e "${CYAN}Untracked files: $untracked_count new files${NC}"
            has_uncommitted=true
            has_changes=true

            # Save list of untracked files
            printf '%s\n' "${untracked_files[@]}" > "$list_dir/untracked.list"

            # Create a pseudo-patch showing new file contents
            local max_untracked_bytes=200000
            {
                for file in "${untracked_files[@]}"; do
                    [ -z "$file" ] && continue
                    local file_path="${dir%/}/$file"
                    if [ -f "$file_path" ]; then
                        local file_size
                        file_size=$(wc -c < "$file_path" 2>/dev/null || echo 0)
                        local is_text=true
                        if [ -s "$file_path" ] && ! LC_ALL=C grep -Iq . "$file_path" 2>/dev/null; then
                            is_text=false
                        fi
                        echo "diff --git a/$file b/$file"
                        echo "new file mode 100644"
                        echo "index 0000000..0000000"
                        echo "--- /dev/null"
                        echo "+++ b/$file"
                        if [ "$file_size" -gt "$max_untracked_bytes" ] || [ "$is_text" != true ]; then
                            echo "@@ -0,0 +1,1 @@"
                            if [ "$is_text" != true ]; then
                                echo "+[omitted: binary file]"
                            else
                                echo "+[omitted: file size ${file_size} bytes exceeds ${max_untracked_bytes} bytes]"
                            fi
                        else
                            echo "@@ -0,0 +1,$(wc -l < "$file_path" 2>/dev/null || echo 1) @@"
                            # Include all lines of the file
                            sed 's/^/+/' < "$file_path"
                        fi
                        echo ""
                    fi
                done
            } > "$diff_dir/new_files.patch"
        fi

        # Calculate total uncommitted stats
        if [ "$has_uncommitted" = true ]; then
            local total_modified=$("${git_cmd[@]}" diff --name-only "${PATHSPEC_ARGS[@]}" | wc -l 2>/dev/null || echo 0)
            local total_staged=$("${git_cmd[@]}" diff --cached --name-only "${PATHSPEC_ARGS[@]}" | wc -l 2>/dev/null || echo 0)
            local total_files=0
            local -a status_files=()
            while IFS= read -r line; do
                [ -z "$line" ] && continue
                local file="${line#?? }"
                file="${file##* -> }"
                status_files+=("$file")
            done < <("${git_cmd[@]}" status --porcelain "${PATHSPEC_ARGS[@]}" 2>/dev/null)
            if [ ${#status_files[@]} -gt 0 ]; then
                total_files=$(printf '%s\n' "${status_files[@]}" | sort -u | grep -c .)
            fi
            tree_uncommitted_stats["$name"]="$total_files files (${total_modified} modified, ${total_staged} staged, ${untracked_count} untracked)"
        else
            tree_uncommitted_stats["$name"]="No uncommitted changes"
        fi
    fi

    # Check committed changes vs base branch
    # Check if base branch exists
    if "${git_cmd[@]}" rev-parse --verify "$BASE_BRANCH" >/dev/null 2>&1; then
        local committed_stats=$("${git_cmd[@]}" diff "$BASE_BRANCH" --shortstat "${PATHSPEC_ARGS[@]}" 2>/dev/null || echo "")
        if [ -z "$committed_stats" ]; then
            committed_stats="0 files"
        fi
        tree_committed_stats["$name"]="$committed_stats"

        if [[ ! "$committed_stats" =~ "0 files" ]] && [[ -n "$committed_stats" ]]; then
            echo -e "${GREEN}Committed changes vs $BASE_BRANCH: $committed_stats${NC}"
            has_changes=true

            # Save committed changes
            local -a committed_files=()
            mapfile -d '' -t committed_files < <("${git_cmd[@]}" diff "$BASE_BRANCH" --name-only -z "${PATHSPEC_ARGS[@]}" 2>/dev/null)

            # Save original file list before filtering
            analysis_write_name_status_list "$list_dir/all_committed.list" "${git_cmd[@]}" diff "$BASE_BRANCH" --name-status -z "${PATHSPEC_ARGS[@]}"

            # Apply filters
            local -a filtered_committed_files=()
            analysis_filter_files committed_files filtered_committed_files "$exclusion_pattern"

            if [ ${#filtered_committed_files[@]} -gt 0 ]; then
                # Generate diff only for filtered files
                "${git_cmd[@]}" diff "$BASE_BRANCH" -U$CONTEXT_LINES -- "${filtered_committed_files[@]}" > "$diff_dir/committed_vs_${SAFE_BASE_BRANCH}.patch" 2>&1
                analysis_write_name_status_list "$list_dir/committed.list" "${git_cmd[@]}" diff "$BASE_BRANCH" --name-status -z -- "${filtered_committed_files[@]}"
            else
                echo "No changes after filtering" > "$diff_dir/committed_vs_${SAFE_BASE_BRANCH}.patch"
                : > "$list_dir/committed.list"
            fi
        fi
    else
        echo -e "${YELLOW}Base branch '$BASE_BRANCH' not found in this tree${NC}"
        tree_committed_stats["$name"]="N/A (no $BASE_BRANCH branch)"
    fi

    tree_has_changes["$name"]=$has_changes

    if [ "$has_changes" = false ]; then
        echo -e "${GREEN}No changes found${NC}"
    fi

    analyzed_trees+=("$name")
    return 0
}

estimate_tokens() {
    local file=$1
    local chars=$(wc -c < "$file" 2>/dev/null || echo 0)
    echo $((chars / 4))
}

copy_root_docs_markdown() {
    local docs_dir="$BASE_DIR/docs"
    local dest_dir="$OUTPUT_DIR/context_docs"
    local copied=0

    if [ ! -d "$docs_dir" ]; then
        return 0
    fi

    mkdir -p "$dest_dir"
    for doc in "$docs_dir"/*.md; do
        [ -e "$doc" ] || continue
        cp -p "$doc" "$dest_dir/"
        ((copied++))
    done

    if [ "$copied" -gt 0 ]; then
        echo -e "${BLUE}Copied $copied docs/*.md file(s) to:${NC} $dest_dir"
    fi
}

create_evaluation_request() {
    local output=""
    local changed_trees=0
    local single_tree_review=false
    local analysis_subject="each tree"

    for tree in "${analyzed_trees[@]}"; do
        if [ "${tree_has_changes[$tree]}" = true ]; then
            ((changed_trees++))
        fi
    done

    if [ "$changed_trees" -le 1 ]; then
        single_tree_review=true
        analysis_subject="this implementation"
    fi

    # Dynamic header based on approach
    if [ "$single_tree_review" = true ]; then
        output+="
# 🔍 Single Tree Implementation Review

Your task is to **produce a deep, production-focused review** of this implementation. Evaluate correctness, completeness, risks, and readiness to merge.
"
    elif [ "$APPROACH" = "combine" ]; then
        output+="
# 🔀 Multi-Tree Integration Analysis

Your task is to **engineer the optimal solution** by combining the best elements from multiple tree implementations. This is not about choosing one tree, but about creating a superior hybrid approach.
"
    else
        output+="
# 🎯 Optimal Tree Selection Analysis

Your task is to **identify the single best tree implementation** that provides the most complete, robust, and production-ready solution.
"
    fi

    # Original request section if file provided
    if [ -n "$ORIGINAL_REQUEST_FILE" ] && [ -f "$ORIGINAL_REQUEST_FILE" ]; then
        if [ "$single_tree_review" = true ]; then
            output+="
## 📋 Original Development Context

**CRITICAL**: This is the original request/plan that prompted this implementation. Your analysis must evaluate how well it addresses these specific requirements.

### Original Request:

"
        else
            output+="
## 📋 Original Development Context

**CRITICAL**: This is the original request/plan that prompted these implementations. Your analysis must evaluate how well each tree addresses these specific requirements.

### Original Request:

"
        fi
        # Read and include the content of the original request file
        output+="\`\`\`
$(cat "$ORIGINAL_REQUEST_FILE")
\`\`\`

"
        if [ "$single_tree_review" = true ]; then
            output+="
**Analysis Focus**: Compare this implementation against the requirements stated above. Look for:
- Which requirements are fully implemented
- Which requirements are partially addressed
- Which requirements are missing
- Any features implemented beyond the original request

---
"
        else
            output+="
**Analysis Focus**: Compare each implementation against the requirements stated above. Look for:
- Which requirements are fully implemented
- Which requirements are partially addressed
- Which requirements are missing
- Any features implemented beyond the original request

---
"
        fi
    elif [ -n "$ORIGINAL_REQUEST_FILE" ]; then
        # File was specified but doesn't exist
        output+="
## ⚠️ Original Request File Not Found

**Warning**: Original request file specified but not found: $ORIGINAL_REQUEST_FILE

**Fallback Analysis**: Look for context clues in:
- Commit messages that explain the \"why\"
- Code comments that reference requirements
- File changes that indicate the scope of work
- Test cases that reveal expected behavior

---
"
    else
        local main_task_entries=()
        local tree
        for tree in "${analyzed_trees[@]}"; do
            local task_file="${tree_main_task_files[$tree]:-}"
            if [ -n "$task_file" ] && [ -s "$task_file" ]; then
                main_task_entries+=("$tree|$task_file")
            fi
        done
        if [ ${#main_task_entries[@]} -gt 0 ]; then
            output+="
## 📋 Per-Tree MAIN_TASK Context

**CRITICAL**: Each selected tree has its own MAIN_TASK.md. Your analysis must evaluate each tree against its own MAIN_TASK requirements.

"
            local entry
            for entry in "${main_task_entries[@]}"; do
                local tree_name="${entry%%|*}"
                local task_file="${entry#*|}"
                output+="### Tree ${tree_name} MAIN_TASK.md (${task_file})

\`\`\`
$(cat "$task_file")
\`\`\`

"
            done
            output+="
**Analysis Focus**: Compare each implementation against its own MAIN_TASK.md. Call out gaps per tree and avoid mixing requirements across trees unless explicitly combining them.

---
"
        fi
    fi

    output+="
## 🧯 Real-World Defect Focus (REQUIRED)

Your analysis must prioritize identifying **real, evidence-backed flaws** in the current implementation(s). Avoid speculative or hypothetical issues.

**Defect Listing Requirements**
- List only issues you can justify from the diffs, tests, or behavior shown.
- Provide file paths and line references where possible.
- Classify severity (High/Medium/Low) and impact.
- Include concrete reproduction or reasoning for each defect.
- If no defects are found in a category, state that explicitly.

Provide a **Defect Register** section in your response:

| Severity | Area | Defect | Evidence (file/line or log) | Impact | Fix Summary |
|----------|------|--------|-----------------------------|--------|-------------|

"

    if [ -n "${DEFECT_REPORT_FILE:-}" ]; then
        output+="
## 📝 Output File (REQUIRED)

Write the full, detailed analysis (including the Defect Register and all required sections) to:
\`${DEFECT_REPORT_FILE}\`

Ensure the Defect Register appears near the top of that file. If no defects are found, state that explicitly.

"
    fi

    output+="
## 🔍 Analysis Framework

### Phase 1: Deep Code Understanding (MANDATORY)

For ${analysis_subject}, you MUST systematically analyze:

**🏗️ Architecture & Design**
- What design patterns are used?
- How is the code structured and organized?
- Are there proper abstractions and separation of concerns?
- Does it follow SOLID principles?

**⚙️ Implementation Quality**
- Is the logic correct and complete?
- Are edge cases handled properly?
- Is error handling comprehensive?
- Are there any obvious bugs or logical errors?

**🔗 Integration Points**
- How does it interact with existing systems?
- What dependencies does it introduce or modify?
- Are there any breaking changes to existing APIs?
- How does it affect the overall system architecture?
"

    # Add testing validation with specific requirements
    if [ "$VALIDATE_TESTS" = true ]; then
        if [ "$single_tree_review" = true ]; then
            output+="
**🧪 Testing & Stability Analysis**
YOU MUST evaluate:
- **Test Coverage**: Are all new/modified code paths tested?
- **Test Quality**: Do tests cover edge cases, error conditions, and integration scenarios?
- **Breaking Changes**: Will this break existing functionality? Run through likely usage scenarios.
- **Regression Risk**: What existing features might be affected?
- **Test Execution**: Can you identify if tests would actually pass?

For this implementation, provide:
1. **Test Coverage Score (1-10)**: How well is the code tested?
2. **Breaking Change Risk (Low/Medium/High)**: Impact on existing functionality
3. **Missing Test Scenarios**: Specific test cases that should be added
4. **Recommended Test Improvements**: Concrete suggestions with examples
"
        else
            output+="
**🧪 Testing & Stability Analysis**
YOU MUST evaluate:
- **Test Coverage**: Are all new/modified code paths tested?
- **Test Quality**: Do tests cover edge cases, error conditions, and integration scenarios?
- **Breaking Changes**: Will this break existing functionality? Run through likely usage scenarios.
- **Regression Risk**: What existing features might be affected?
- **Test Execution**: Can you identify if tests would actually pass?

For each tree, provide:
1. **Test Coverage Score (1-10)**: How well is the code tested?
2. **Breaking Change Risk (Low/Medium/High)**: Impact on existing functionality
3. **Missing Test Scenarios**: Specific test cases that should be added
4. **Recommended Test Improvements**: Concrete suggestions with examples
"
        fi
    fi

    # Add security analysis with specific focus areas
    if [ "$SECURITY_CHECK" = true ]; then
        if [ "$single_tree_review" = true ]; then
            output+="
**🔒 Security Analysis**
Systematically review this implementation for:

**Input Validation & Sanitization**
- Are all user inputs properly validated?
- Is there protection against injection attacks (SQL, XSS, etc.)?
- Are file uploads handled securely?

**Authentication & Authorization** 
- Are access controls properly implemented?
- Is sensitive data properly protected?
- Are there any privilege escalation risks?

**Data Security**
- Is sensitive data encrypted at rest and in transit?
- Are credentials and secrets properly managed?
- Is there any unintentional data exposure?

**Dependencies & Supply Chain**
- Are new dependencies from trusted sources?
- Do dependencies have known vulnerabilities?
- Is the dependency tree minimal and necessary?

For each security issue found, provide:
1. **Vulnerability Description**: What exactly is the risk?
2. **Impact Assessment**: What could go wrong?
3. **Concrete Fix**: Specific code changes to address the issue
4. **Security Test**: How to verify the fix works
"
        else
            output+="
**🔒 Security Analysis**
Systematically review each tree for:

**Input Validation & Sanitization**
- Are all user inputs properly validated?
- Is there protection against injection attacks (SQL, XSS, etc.)?
- Are file uploads handled securely?

**Authentication & Authorization** 
- Are access controls properly implemented?
- Is sensitive data properly protected?
- Are there any privilege escalation risks?

**Data Security**
- Is sensitive data encrypted at rest and in transit?
- Are credentials and secrets properly managed?
- Is there any unintentional data exposure?

**Dependencies & Supply Chain**
- Are new dependencies from trusted sources?
- Do dependencies have known vulnerabilities?
- Is the dependency tree minimal and necessary?

For each security issue found, provide:
1. **Vulnerability Description**: What exactly is the risk?
2. **Impact Assessment**: What could go wrong?
3. **Concrete Fix**: Specific code changes to address the issue
4. **Security Test**: How to verify the fix works
"
        fi
    fi

    # Add performance analysis with measurable criteria
    if [ "$PERFORMANCE_CHECK" = true ]; then
        if [ "$single_tree_review" = true ]; then
            output+="
**⚡ Performance Analysis**
Evaluate this implementation for:

**Algorithmic Efficiency**
- What is the time complexity of key operations?
- Are there more efficient algorithms available?
- Are there unnecessary loops or redundant operations?

**Resource Usage**
- Memory allocation patterns and potential leaks
- Database query efficiency and N+1 problems
- File I/O and network call optimization
- CPU-intensive operations that could be optimized

**Scalability Considerations**
- How will this perform under load?
- Are there potential bottlenecks?
- Is caching properly implemented?
- Are there opportunities for parallelization?

**Measurement & Optimization**
For performance issues, provide:
1. **Performance Bottleneck**: Specific code that's inefficient
2. **Expected Impact**: How much slower/resource-intensive
3. **Optimization Strategy**: Concrete improvement approach
4. **Code Example**: Show the optimized version
5. **Measurement Plan**: How to verify improvement
"
        else
            output+="
**⚡ Performance Analysis**
Evaluate each tree for:

**Algorithmic Efficiency**
- What is the time complexity of key operations?
- Are there more efficient algorithms available?
- Are there unnecessary loops or redundant operations?

**Resource Usage**
- Memory allocation patterns and potential leaks
- Database query efficiency and N+1 problems
- File I/O and network call optimization
- CPU-intensive operations that could be optimized

**Scalability Considerations**
- How will this perform under load?
- Are there potential bottlenecks?
- Is caching properly implemented?
- Are there opportunities for parallelization?

**Measurement & Optimization**
For performance issues, provide:
1. **Performance Bottleneck**: Specific code that's inefficient
2. **Expected Impact**: How much slower/resource-intensive
3. **Optimization Strategy**: Concrete improvement approach
4. **Code Example**: Show the optimized version
5. **Measurement Plan**: How to verify improvement
"
        fi
    fi

    # Add requirements validation with gap analysis
    if [ "$VALIDATE_REQUIREMENTS" = true ]; then
        if [ "$single_tree_review" = true ]; then
            output+="
### Phase 2: Requirements Validation & Gap Analysis

**📝 Requirement Reconstruction**
From the code changes, infer the original requirements:
1. **Functional Requirements**: What should the system do?
2. **Non-Functional Requirements**: Performance, security, usability constraints
3. **Business Rules**: What logic or workflows are being implemented?
4. **Integration Requirements**: How should it work with existing systems?

**🔍 Gap Analysis Matrix**
For this implementation, create a detailed assessment:

| Requirement | Implementation | Status | Gap Description | Fix Needed |
|-------------|----------------|--------|-----------------|------------|
| REQ-001: [Description] | [How it addresses it] | ✅ Complete / ⚠️ Partial / ❌ Missing | [What's missing] | [Specific fix] |

**🛠️ Gap Remediation**
For any gaps found, provide:
1. **Missing Functionality**: Exactly what needs to be implemented
2. **Implementation Approach**: How to add the missing pieces
3. **Code Examples**: Specific code to fill the gaps
4. **Integration Points**: How the fixes integrate with existing code
5. **Testing Strategy**: How to verify the gaps are filled
"
        else
            output+="
### Phase 2: Requirements Validation & Gap Analysis

**📝 Requirement Reconstruction**
From the code changes, infer the original requirements:
1. **Functional Requirements**: What should the system do?
2. **Non-Functional Requirements**: Performance, security, usability constraints
3. **Business Rules**: What logic or workflows are being implemented?
4. **Integration Requirements**: How should it work with existing systems?

**🔍 Gap Analysis Matrix**
For each tree, create a detailed assessment:

| Requirement | Tree Implementation | Status | Gap Description | Fix Needed |
|-------------|-------------------|---------|-----------------|------------|
| REQ-001: [Description] | [How tree addresses it] | ✅ Complete / ⚠️ Partial / ❌ Missing | [What's missing] | [Specific fix] |

**🛠️ Gap Remediation**
For any gaps found, provide:
1. **Missing Functionality**: Exactly what needs to be implemented
2. **Implementation Approach**: How to add the missing pieces
3. **Code Examples**: Specific code to fill the gaps
4. **Integration Points**: How the fixes integrate with existing code
5. **Testing Strategy**: How to verify the gaps are filled
"
        fi
    fi

    if [ "$single_tree_review" = true ]; then
        output+="
### Phase 3: Implementation Review & Recommendation

**Quality and Readiness Assessment**
- **Overall Quality Score (1-10)**: Code quality, maintainability, and correctness
- **Production Readiness**: Ready / Needs Work / Not Ready
- **Key Risks**: Top risks with concrete impact
- **Required Fixes**: Specific changes with file/line references

**Recommendation**
- **Merge Readiness**: Yes/No with rationale
- **Preconditions**: Must-fix items before merge
"
    else
        output+="
### Phase 3: Comparative Analysis
"

        if [ "$APPROACH" = "combine" ]; then
            output+="
**🔀 Element Extraction & Combination Strategy**

**Best-of-Breed Analysis**
Break down each tree into components and identify the superior approach for each:

| Component | Tree 1 Approach | Tree 2 Approach | Tree 3 Approach | Best Choice | Rationale |
|-----------|----------------|----------------|----------------|-------------|-----------|
| Core Algorithm | [Description] | [Description] | [Description] | Tree X | [Why it's superior] |
| Error Handling | [Description] | [Description] | [Description] | Tree Y | [Why it's superior] |
| Data Validation | [Description] | [Description] | [Description] | Tree Z | [Why it's superior] |

**Integration Engineering**
Design how to combine the best elements:
1. **Component Integration Map**: How pieces fit together
2. **Interface Harmonization**: Resolving API differences between components
3. **Dependency Resolution**: Managing conflicting requirements
4. **Performance Impact**: How combination affects overall performance
5. **Testing Strategy**: Ensuring combined solution works correctly

**Hybrid Implementation Plan**
Provide the actual combined solution:
- **Complete Code**: The integrated implementation using best parts
- **Architecture Diagram**: How components interact
- **Migration Strategy**: Steps to move from current state to hybrid solution
"
        else
            output+="
**🎯 Single Tree Selection Criteria**

**Weighted Scoring Matrix**
Evaluate each tree across key dimensions:

| Criteria | Weight | Tree 1 Score | Tree 2 Score | Tree 3 Score | Notes |
|----------|--------|--------------|--------------|--------------|-------|
| Functionality Completeness | 30% | X/10 | Y/10 | Z/10 | [Specific gaps/strengths] |
| Code Quality | 25% | X/10 | Y/10 | Z/10 | [Architecture, maintainability] |
| Production Readiness | 20% | X/10 | Y/10 | Z/10 | [Error handling, logging, etc.] |"

        if [ "$VALIDATE_TESTS" = true ]; then
            output+="
| Test Coverage | 15% | X/10 | Y/10 | Z/10 | [Test quality and coverage] |"
        fi

        if [ "$SECURITY_CHECK" = true ]; then
            output+="
| Security Posture | 5% | X/10 | Y/10 | Z/10 | [Vulnerability assessment] |"
        fi

        if [ "$PERFORMANCE_CHECK" = true ]; then
            output+="
| Performance | 5% | X/10 | Y/10 | Z/10 | [Efficiency and scalability] |"
        fi

        output+="

**Final Recommendation**
- **Winning Tree**: Tree X with weighted score of Y/10
- **Key Advantages**: Why this tree is superior
- **Required Improvements**: What needs to be fixed before merge
"
        fi
    fi

    # Add merge plan with executable instructions
    if [ "$MERGE_PLAN" = true ]; then
        output+="
### Phase 4: Merge Execution Plan

**🚀 Step-by-Step Merge Strategy**

**Pre-Merge Preparation**
1. **Code Improvements**: Apply any fixes identified in analysis
2. **Test Additions**: Add missing test cases
3. **Documentation Updates**: Update relevant docs
4. **Dependency Management**: Resolve any dependency conflicts

**Merge Sequence** (Provide exact git commands)
\`\`\`bash
# 1. Prepare target branch
git checkout $BASE_BRANCH
git pull origin $BASE_BRANCH

# 2. Create merge branch
git checkout -b merge-tree-implementation

# 3. Merge strategy (specific commands)
[Provide exact merge commands based on analysis]

# 4. Conflict resolution strategy
[Specific guidance for expected conflicts]

# 5. Post-merge verification
[Test commands to run]
\`\`\`

**Conflict Resolution Guide**
For each likely conflict, provide:
- **File**: Where conflict will occur
- **Conflict Type**: What kind of conflict (merge, semantic, etc.)
- **Resolution Strategy**: How to resolve it
- **Code Example**: What the resolved code should look like

**Post-Merge Verification**
\`\`\`bash
# Required tests to run
npm test                    # Unit tests
npm run integration-test    # Integration tests
npm run lint               # Code quality
npm run security-scan      # Security check (if applicable)
\`\`\`

**Rollback Plan**
If merge causes issues:
\`\`\`bash
# Emergency rollback commands
git reset --hard [safe-commit-hash]
# OR
git revert [merge-commit-hash]
\`\`\`
"
    fi

    if [ "$single_tree_review" = true ]; then
        output+="
## 📊 Executive Summary

Provide a concise summary table:

| Item | Assessment |
|------|------------|
| Branch | branch-name |
| Overall Quality | X/10 |
"
        if [ "$VALIDATE_TESTS" = true ]; then
            output+="| Test Score | X/10 |
"
        fi
        if [ "$SECURITY_CHECK" = true ]; then
            output+="| Security Risk | Low/Medium/High |
"
        fi
        if [ "$PERFORMANCE_CHECK" = true ]; then
            output+="| Performance Risk | Low/Medium/High |
"
        fi
        if [ "$VALIDATE_REQUIREMENTS" = true ]; then
            output+="| Requirements Met | XX% |
"
        fi
        output+="| Ready to Merge | Yes/No |
| Critical Issues | [List] |

"
    else
        output+="
## 📊 Executive Summary

Provide a concise summary table:

| Tree | Branch | Quality Score | "

        if [ "$VALIDATE_TESTS" = true ]; then
            output+="Test Score | "
        fi

        if [ "$SECURITY_CHECK" = true ]; then
            output+="Security Score | "
        fi

        if [ "$PERFORMANCE_CHECK" = true ]; then
            output+="Performance Score | "
        fi

        if [ "$VALIDATE_REQUIREMENTS" = true ]; then
            output+="Requirements Met | "
        fi

        output+="Ready to Merge | Critical Issues |
|------|--------|---------------|"

        if [ "$VALIDATE_TESTS" = true ]; then
            output+="------------|"
        fi

        if [ "$SECURITY_CHECK" = true ]; then
            output+="---------------|"
        fi

        if [ "$PERFORMANCE_CHECK" = true ]; then
            output+="------------------|"
        fi

        if [ "$VALIDATE_REQUIREMENTS" = true ]; then
            output+="------------------|"
        fi

        output+="---------------|----------------|
| Tree 1 | branch-name | X/10 | "

        if [ "$VALIDATE_TESTS" = true ]; then
            output+="X/10 | "
        fi

        if [ "$SECURITY_CHECK" = true ]; then
            output+="X/10 | "
        fi

        if [ "$PERFORMANCE_CHECK" = true ]; then
            output+="X/10 | "
        fi

        if [ "$VALIDATE_REQUIREMENTS" = true ]; then
            output+="XX% | "
        fi

        output+="Yes/No | [List] |

"
    fi

    if [ "$single_tree_review" = true ]; then
        output+="
## 🎯 Final Recommendation: Implementation Review

**MERGE READINESS**: Yes/No

**JUSTIFICATION**: 
- [Key reasons for the decision]
- [Specific risks or strengths]

**REQUIRED IMPROVEMENTS** (before merge):
1. [Specific improvement with file/line references]
2. [Specific improvement with code example]
3. [Specific improvement with test requirements]
"
    elif [ "$APPROACH" = "combine" ]; then
        output+="
## 🎯 Final Deliverable: Hybrid Solution

**YOU MUST PROVIDE:**
1. **Complete Hybrid Implementation**: Working code that combines the best elements
2. **Integration Architecture**: How the combined solution is structured
3. **Migration Guide**: Step-by-step process to implement the hybrid solution
4. **Test Suite**: Comprehensive tests for the hybrid approach
5. **Documentation**: Updated docs reflecting the combined approach
"
    else
        output+="
## 🎯 Final Recommendation: Best Tree Selection

**SELECTED TREE**: Tree X

**JUSTIFICATION**: 
- Scores highest on weighted criteria (X.X/10 overall)
- Most complete implementation of requirements
- Highest code quality and maintainability
- [Additional specific reasons]

**REQUIRED IMPROVEMENTS** (before merge):
1. [Specific improvement with file/line references]
2. [Specific improvement with code example]
3. [Specific improvement with test requirements]
"
    fi

    local guidelines_file="$BASE_DIR/utils/templates/analysis-prompt.md"
    if [ -f "$guidelines_file" ]; then
        output+="
$(cat "$guidelines_file")
"
    else
        output+="
---

## 🔍 Analysis Guidelines

**CRITICAL SUCCESS FACTORS:**
1. **Be Specific**: Reference actual files, functions, and line numbers
2. **Provide Examples**: Show concrete code improvements
3. **Be Actionable**: Every recommendation should be implementable
4. **Consider Context**: Understand the original problem being solved
5. **Think Production**: Consider real-world usage and maintenance

**AVOID:**
- Generic feedback without specific references
- Recommendations without implementation details
- Analysis without considering the original requirements
- Overlooking integration and system-wide impacts

**REMEMBER**: Your analysis will directly inform development decisions. Be thorough, specific, and actionable.
"
    fi

    echo "$output"
}

generate_llm_prompt() {
    local prompt_file="$OUTPUT_DIR/prompt.md"
    local all_file="$OUTPUT_DIR/all.md"
    local changed_trees=0
    local analysis_intro="You are tasked with evaluating different implementations across multiple development trees. Each tree may contain both committed and uncommitted changes."

    for tree in "${analyzed_trees[@]}"; do
        if [ "${tree_has_changes[$tree]}" = true ]; then
            ((changed_trees++))
        fi
    done

    if [ "$changed_trees" -le 1 ]; then
        analysis_intro="You are tasked with reviewing a single implementation from one development tree. This tree may contain both committed and uncommitted changes."
    fi

    echo -e "\n${CYAN}Generating LLM evaluation prompt...${NC}"

    DEFECT_REPORT_FILE="${OUTPUT_DIR}/analysis_${SAFE_BASE_BRANCH}_defects.md"
    printf 'Path: %s\n\n# Defect-Focused Analysis Report\n\n' "$DEFECT_REPORT_FILE" > "$DEFECT_REPORT_FILE"

    # If MD_ONLY is true, collect all non-markdown files that were changed
    local excluded_files_content=""
    if [ "$MD_ONLY" = true ]; then
        excluded_files_content="\n## Files Excluded from Analysis (Non-Markdown)\n\nThe following files were changed but excluded from the detailed analysis because --md-only was specified:\n"

        for tree in "${analyzed_trees[@]}"; do
            if [ "${tree_has_changes[$tree]}" = true ]; then
                local tree_dir="$OUTPUT_DIR/implementation-$tree"
                local list_dir="$tree_dir/lists"
                local tree_excluded=""

                # Collect excluded files from each tree
                local excluded_count=0

                # Check committed files
                if [ -f "$list_dir/all_committed.list" ]; then
                    local non_md_files
                    non_md_files=$(analysis_extract_non_md_files "$list_dir/all_committed.list")
                    if [ -n "$non_md_files" ]; then
                        tree_excluded="$tree_excluded$non_md_files\n"
                        excluded_count=$(echo "$non_md_files" | wc -l)
                    fi
                fi

                # Check unstaged files
                if [ -f "$list_dir/all_unstaged.list" ]; then
                    local non_md_unstaged
                    non_md_unstaged=$(analysis_extract_non_md_files "$list_dir/all_unstaged.list")
                    if [ -n "$non_md_unstaged" ]; then
                        # Add only if not already in list
                        while IFS= read -r file; do
                            if ! echo -e "$tree_excluded" | grep -q "^$file$"; then
                                tree_excluded="$tree_excluded$file\n"
                                ((excluded_count++))
                            fi
                        done <<< "$non_md_unstaged"
                    fi
                fi

                # Check staged files
                if [ -f "$list_dir/all_staged.list" ]; then
                    local non_md_staged
                    non_md_staged=$(analysis_extract_non_md_files "$list_dir/all_staged.list")
                    if [ -n "$non_md_staged" ]; then
                        # Add only if not already in list
                        while IFS= read -r file; do
                            if ! echo -e "$tree_excluded" | grep -q "^$file$"; then
                                tree_excluded="$tree_excluded$file\n"
                                ((excluded_count++))
                            fi
                        done <<< "$non_md_staged"
                    fi
                fi

                # Check untracked files
                if [ -f "$list_dir/all_untracked.list" ]; then
                    local non_md_untracked
                    non_md_untracked=$(analysis_extract_non_md_files "$list_dir/all_untracked.list")
                    if [ -n "$non_md_untracked" ]; then
                        # Add only if not already in list
                        while IFS= read -r file; do
                            if [ -n "$file" ] && ! echo -e "$tree_excluded" | grep -q "^$file$"; then
                                tree_excluded="$tree_excluded$file\n"
                                ((excluded_count++))
                            fi
                        done <<< "$non_md_untracked"
                    fi
                fi

                # Add to content if there are excluded files
                if [ $excluded_count -gt 0 ]; then
                    excluded_files_content="$excluded_files_content\n### Tree $tree (${tree_branches[$tree]}) - $excluded_count non-markdown files:\n\`\`\`\n$(echo -e "$tree_excluded" | sort -u | grep -v '^$')\`\`\`\n"
                fi
            fi
        done
    fi

    # Gather all tree content files
    local tree_contents=()
    for tree in "${analyzed_trees[@]}"; do
        if [ "${tree_has_changes[$tree]}" = true ]; then
            local tree_content_file="$OUTPUT_DIR/.tree_${tree}_content"
            > "$tree_content_file"

            echo -e "\n### Tree $tree (Branch: ${tree_branches[$tree]})\n" >> "$tree_content_file"

            local tree_dir="$OUTPUT_DIR/implementation-$tree"
            local diff_dir="$tree_dir/diffs"

            # Add uncommitted changes if exist
            if [ "$INCLUDE_UNCOMMITTED" = true ]; then
                # Add unstaged changes
                if [ -f "$diff_dir/unstaged.patch" ] && [ -s "$diff_dir/unstaged.patch" ]; then
                    echo "#### Unstaged Changes" >> "$tree_content_file"
                    echo '```diff' >> "$tree_content_file"
                    cat "$diff_dir/unstaged.patch" >> "$tree_content_file"
                    echo '```' >> "$tree_content_file"
                    echo "" >> "$tree_content_file"
                fi

                # Add staged changes
                if [ -f "$diff_dir/staged.patch" ] && [ -s "$diff_dir/staged.patch" ]; then
                    echo "#### Staged Changes" >> "$tree_content_file"
                    echo '```diff' >> "$tree_content_file"
                    cat "$diff_dir/staged.patch" >> "$tree_content_file"
                    echo '```' >> "$tree_content_file"
                    echo "" >> "$tree_content_file"
                fi

                # Add untracked files
                if [ -f "$diff_dir/new_files.patch" ] && [ -s "$diff_dir/new_files.patch" ]; then
                    echo "#### New Untracked Files" >> "$tree_content_file"
                    echo '```diff' >> "$tree_content_file"
                    cat "$diff_dir/new_files.patch" >> "$tree_content_file"
                    echo '```' >> "$tree_content_file"
                    echo "" >> "$tree_content_file"
                fi
            fi

            # Add committed changes if exist
            if [ -f "$diff_dir/committed_vs_${SAFE_BASE_BRANCH}.patch" ] && [ -s "$diff_dir/committed_vs_${SAFE_BASE_BRANCH}.patch" ]; then
                echo -e "\n#### Committed Changes (vs $BASE_BRANCH)" >> "$tree_content_file"
                echo '```diff' >> "$tree_content_file"
                cat "$diff_dir/committed_vs_${SAFE_BASE_BRANCH}.patch" >> "$tree_content_file"
                echo '```' >> "$tree_content_file"
            fi

            tree_contents+=("$tree_content_file")
        fi
    done

    local prompt_content
    prompt_content=$(create_evaluation_request)
    printf 'Path: %s\n\n' "$prompt_file" > "$prompt_file"
    printf '%s\n' "$prompt_content" >> "$prompt_file"

    # Build all.md with prompt at the top
    printf 'Path: %s\n\n' "$all_file" > "$all_file"
    printf '%s\n' "$prompt_content" >> "$all_file"
    printf '\n## Analysis Overview\n\n' >> "$all_file"
    printf '%s\n\n' "$analysis_intro" >> "$all_file"
    printf 'Base branch for comparison: **%s**\n\n' "$BASE_BRANCH" >> "$all_file"
    printf '### Summary Table\n\n' >> "$all_file"

    if [ "$INCLUDE_UNCOMMITTED" = true ]; then
        printf '| Tree | Branch | Uncommitted Changes | Committed Changes | Has Changes |\n' >> "$all_file"
        printf '|------|--------|-------------------|-------------------|-------------|\n' >> "$all_file"

        for tree in "${analyzed_trees[@]}"; do
            local branch="${tree_branches[$tree]}"
            local uncommitted="${tree_uncommitted_stats[$tree]:-N/A}"
            local committed="${tree_committed_stats[$tree]}"
            local has_changes="${tree_has_changes[$tree]}"
            printf '| Tree %s | %s | %s | %s | %s |\n' "$tree" "$branch" "$uncommitted" "$committed" "$has_changes" >> "$all_file"
        done
    else
        printf '| Tree | Branch | Committed Changes vs %s | Has Changes |\n' "$BASE_BRANCH" >> "$all_file"
        printf '|------|--------|----------------------------------|-------------|\n' >> "$all_file"

        for tree in "${analyzed_trees[@]}"; do
            local branch="${tree_branches[$tree]}"
            local committed="${tree_committed_stats[$tree]}"
            local has_changes="${tree_has_changes[$tree]}"
            printf '| Tree %s | %s | %s | %s |\n' "$tree" "$branch" "$committed" "$has_changes" >> "$all_file"
        done
    fi

    # Add excluded files section if MD_ONLY is true
    if [ "$MD_ONLY" = true ] && [ -n "$excluded_files_content" ]; then
        printf '%b\n' "$excluded_files_content" >> "$all_file"
    fi

    # Include context docs
    local docs_dir="$BASE_DIR/docs"
    local docs_found=0
    for doc in "$docs_dir"/*.md; do
        [ -e "$doc" ] || continue
        if [ "$docs_found" -eq 0 ]; then
            printf '\n## Context Docs\n' >> "$all_file"
        fi
        docs_found=$((docs_found + 1))
        printf '\n### docs/%s\n\n' "$(basename "$doc")" >> "$all_file"
        printf '```md\n' >> "$all_file"
        cat "$doc" >> "$all_file"
        printf '\n```\n' >> "$all_file"
    done

    printf '\n## Detailed Changes\n' >> "$all_file"
    for tree_file in "${tree_contents[@]}"; do
        cat "$tree_file" >> "$all_file"
    done

    echo -e "${GREEN}✓ Prompt saved${NC}"
    echo -e "${BLUE}📄 Prompt:${NC} $prompt_file"
    echo -e "${BLUE}📄 All-in-one:${NC} $all_file"
    local tokens=$(estimate_tokens "$all_file")
    echo -e "${CYAN}Estimated tokens (all.md): ~$tokens${NC}"

    # Clean up temp files
    for tree_file in "${tree_contents[@]}"; do
        rm -f "$tree_file"
    done
}

create_scoring_template() {
    cat << 'EOF'
## Scoring Methodology

Use this template for consistent evaluation:

### Functionality Score (1-10)
- 10: Complete implementation, all edge cases handled
- 8-9: Nearly complete, minor gaps
- 6-7: Core functionality works, some missing pieces
- 4-5: Partial implementation, significant gaps
- 1-3: Minimal functionality, major issues

### Code Quality Score (1-10)
- 10: Exemplary code, follows all best practices
- 8-9: High quality, minor improvements needed
- 6-7: Good code, some refactoring opportunities
- 4-5: Adequate but needs improvement
- 1-3: Poor quality, significant issues

### Production Readiness Score (1-10)
- 10: Ready for production deployment
- 8-9: Minor polish needed
- 6-7: Some production concerns to address
- 4-5: Significant work needed for production
- 1-3: Not ready for production use
EOF
}

generate_enhanced_summary() {
    local summary_file="$OUTPUT_DIR/summary.md"
    local summary_tmp="${summary_file}.tmp"

    cat > "$summary_tmp" << EOF
# Tree Analysis Summary

**Generated**: $(date)
**Base Branch**: $BASE_BRANCH
**Analysis Approach**: $APPROACH
**Trees Analyzed**: ${#analyzed_trees[@]}

## Analysis Configuration

- **Approach**: $([ "$APPROACH" = "combine" ] && echo "Combine best elements" || echo "Select optimal tree")
- **Test Validation**: $VALIDATE_TESTS
- **Requirements Validation**: $VALIDATE_REQUIREMENTS
- **Merge Planning**: $MERGE_PLAN
- **Security Analysis**: $SECURITY_CHECK
- **Performance Analysis**: $PERFORMANCE_CHECK
- **Original Request File**: $([ -n "$ORIGINAL_REQUEST_FILE" ] && echo "$ORIGINAL_REQUEST_FILE" || echo "Not provided")

## Trees Overview

| Tree | Branch | Has Changes | Status |
|------|--------|-------------|---------|
EOF

    for tree in "${analyzed_trees[@]}"; do
        local branch="${tree_branches[$tree]}"
        local has_changes="${tree_has_changes[$tree]}"
        local status="Ready for Analysis"

        if [ "$has_changes" = false ]; then
            status="No Changes"
        fi

        echo "| Tree $tree | $branch | $has_changes | $status |" >> "$summary_file"
    done

    cat >> "$summary_file" << EOF

## Next Steps

1. **Review Generated Output**: Check \`all.md\`
2. **Run Analysis**: Copy prompt to Claude for evaluation
3. **Apply Recommendations**: Implement suggested improvements
4. **Execute Merge Plan**: Follow provided merge instructions

## Quick Reference

- **All-in-one File**: \`all.md\`
- **Prompt File**: \`prompt.md\`
- **Tree Details**: \`implementation-*/\` subdirectories
- **Context Docs**: \`context_docs/\`
- **Analysis Config**: See configuration section above

EOF

    printf 'Path: %s\n\n' "$summary_file" > "$summary_file"
    cat "$summary_tmp" >> "$summary_file"
    rm -f "$summary_tmp"

    echo -e "${GREEN}✓ Enhanced summary saved${NC}"
    echo -e "${BLUE}📋 Enhanced Summary:${NC} $summary_file"
}

analysis_collect_tree_paths() {
    local base_dir=$1
    local trees_dir_name=$2
    local -n out_paths=$3

    out_paths=()
    while IFS= read -r path; do
        [ -n "$path" ] && out_paths+=("$path")
    done < <(list_tree_paths "$base_dir" "$trees_dir_name")

    if [ ${#out_paths[@]} -eq 0 ]; then
        return 1
    fi
    return 0
}

analysis_resolve_trees_to_analyze() {
    local base_dir=$1
    local trees_dir_name=$2
    local specific_trees=$3
    local -n all_paths=$4
    local -n out_trees=$5
    local tree
    local tree_dir
    local name
    local identity

    out_trees=()
    if [ ${#all_paths[@]} -eq 0 ]; then
        return 1
    fi

    if [ -n "$specific_trees" ]; then
        # Parse comma-separated list
        local -a tree_list=()
        IFS=',' read -ra tree_list <<< "$specific_trees"
        for tree in "${tree_list[@]}"; do
            tree=$(echo "$tree" | tr -d ' ')
            [ -n "$tree" ] || continue

            local -a local_matches=()
            if [[ "$tree" == */* ]]; then
                for candidate in "${all_paths[@]}"; do
                    if [[ "${candidate#$base_dir/}" == "${trees_dir_name}/${tree}" ]] || [[ "${candidate}" == *"/${tree}" ]]; then
                        local_matches+=("$candidate")
                    fi
                done
            else
                for candidate in "${all_paths[@]}"; do
                    if [ "$(basename "$candidate")" = "$tree" ]; then
                        local_matches+=("$candidate")
                    fi
                done
            fi

            if [ ${#local_matches[@]} -eq 1 ]; then
                tree_dir="${local_matches[0]}"
                name=$(basename "$tree_dir")
                identity=$(worktree_identity_from_dir "$tree_dir" "$base_dir" "$trees_dir_name" 2>/dev/null || true)
                if [ -n "$identity" ]; then
                    IFS='|' read -r feature iter <<< "$identity"
                    if [ -n "$feature" ] && [ -n "$iter" ]; then
                        name="${feature}-${iter}"
                    fi
                fi
                out_trees+=("$name|${tree_dir%/}")
            elif [ ${#local_matches[@]} -gt 1 ]; then
                echo -e "${YELLOW}Warning: Tree '$tree' is ambiguous; use feature/iter${NC}"
            else
                echo -e "${YELLOW}Warning: Tree '$tree' not found${NC}"
            fi
        done
    else
        for tree_dir in "${all_paths[@]}"; do
            [ -d "$tree_dir" ] || continue
            name=$(basename "$tree_dir")
            identity=$(worktree_identity_from_dir "$tree_dir" "$base_dir" "$trees_dir_name" 2>/dev/null || true)
            if [ -n "$identity" ]; then
                IFS='|' read -r feature iter <<< "$identity"
                if [ -n "$feature" ] && [ -n "$iter" ]; then
                    name="${feature}-${iter}"
                fi
            fi
            out_trees+=("$name|${tree_dir%/}")
        done
    fi

    if [ ${#out_trees[@]} -eq 0 ]; then
        return 1
    fi
    return 0
}

analysis_run_trees() {
    local base_dir=$1
    local -n trees=$2

    for tree_info in "${trees[@]}"; do
        IFS='|' read -r name dir <<< "$tree_info"
        # Convert relative path to absolute path
        if [[ "$dir" != /* ]]; then
            dir="$base_dir/$dir"
        fi
        analyze_tree_changes "$name" "$dir"
    done

    if [ -z "$ORIGINAL_REQUEST_FILE" ] && [ ${#analyzed_trees[@]} -eq 1 ]; then
        local only_tree="${analyzed_trees[0]}"
        local tree_dir="${tree_dirs[$only_tree]:-}"
        if [ -n "$tree_dir" ]; then
            local main_task_file="${tree_dir%/}/MAIN_TASK.md"
            if [ -s "$main_task_file" ]; then
                ORIGINAL_REQUEST_FILE="$main_task_file"
                echo -e "${BLUE}Using MAIN_TASK.md as original request: ${main_task_file}${NC}"
            fi
        fi
    fi
}

analysis_write_state_file() {
    local state_file="${OUTPUT_DIR}/analysis_state.txt"

    {
        printf 'Path: %s\n\n' "$state_file"
        echo "Generated at: $(date)"
        echo "Base branch: $BASE_BRANCH"
        echo "state|tree|dir|head|status_hash|status_lines"
        for tree in "${analyzed_trees[@]}"; do
            echo "state|${tree}|${tree_dirs[$tree]:-}|${tree_git_head[$tree]:-}|${tree_git_status_hash[$tree]:-}|${tree_git_status_lines[$tree]:-0}"
        done
    } > "$state_file"
}

analysis_write_summary_short() {
    local summary_file="$OUTPUT_DIR/summary_short.txt"

    {
        echo "Tree Changes Analysis Summary"
        echo "============================"
        echo "Generated at: $(date)"
        echo "Base branch: $BASE_BRANCH"
        echo "Trees analyzed: ${#analyzed_trees[@]}"
        echo ""

        echo "Trees with changes:"
        for tree in "${analyzed_trees[@]}"; do
            if [ "${tree_has_changes[$tree]}" = true ]; then
                echo "  - Tree $tree (${tree_branches[$tree]}):"
                if [ "$INCLUDE_UNCOMMITTED" = true ] && [ -n "${tree_uncommitted_stats[$tree]:-}" ]; then
                    echo "    Uncommitted: ${tree_uncommitted_stats[$tree]}"
                fi
                echo "    Committed: ${tree_committed_stats[$tree]}"
            fi
        done

        echo ""
        echo "Trees with no changes:"
        for tree in "${analyzed_trees[@]}"; do
            if [ "${tree_has_changes[$tree]}" = false ]; then
                echo "  - Tree $tree (${tree_branches[$tree]})"
            fi
        done
    } > "$summary_file"
}

analysis_print_completion() {
    echo -e "\n${CYAN}════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}                 ANALYSIS COMPLETE                   ${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════${NC}"

    echo -e "\n${GREEN}✓ Analysis completed successfully!${NC}"
    echo -e "\n${BLUE}📁 Results:${NC} $OUTPUT_DIR"
    echo -e "${BLUE}📋 Summary:${NC} $OUTPUT_DIR/summary_short.txt"

    local trees_with_changes=0
    for tree in "${analyzed_trees[@]}"; do
        [ "${tree_has_changes[$tree]}" = true ] && ((trees_with_changes++))
    done

    echo -e "\n${CYAN}Quick Stats:${NC}"
    echo -e "  Trees analyzed: ${#analyzed_trees[@]}"
    echo -e "  Trees with changes: $trees_with_changes"
    echo -e "  Trees with no changes: $((${#analyzed_trees[@]} - trees_with_changes))"
}

analysis_print_output_dir() {
    echo -e "\n${BLUE}📁 Output directory:${NC} $OUTPUT_DIR"
}

analysis_print_tree_selection() {
    local -n trees=$1
    echo -e "\n${BLUE}Found ${#trees[@]} tree(s) to analyze${NC}"
    echo -e "${BLUE}Base branch: $BASE_BRANCH${NC}"
}

analysis_print_verbose_details() {
    if [ "$VERBOSE_MODE" != true ]; then
        return 0
    fi

    echo -e "\n${CYAN}Tree Details:${NC}"
    for tree in "${analyzed_trees[@]}"; do
        if [ "${tree_has_changes[$tree]}" = true ]; then
            echo -e "  ${GREEN}Tree $tree (${tree_branches[$tree]}):${NC}"
            if [ "$INCLUDE_UNCOMMITTED" = true ] && [ -n "${tree_uncommitted_stats[$tree]:-}" ]; then
                echo -e "    Uncommitted: ${tree_uncommitted_stats[$tree]}"
            fi
            echo -e "    Committed: ${tree_committed_stats[$tree]}"
        fi
    done
}

analysis_print_next_steps() {
    echo -e "\n${YELLOW}Next steps:${NC}"
    echo "1. Review the generated output at: $OUTPUT_DIR/all.md"
    echo "2. Copy its contents to Claude (claude.ai or Claude Code CLI)"
    echo "3. Review Claude's analysis and recommendations"
    if [ -n "${DEFECT_REPORT_FILE:-}" ]; then
        echo "4. Save the detailed analysis to: $DEFECT_REPORT_FILE"
    fi
    echo ""
    echo -e "${CYAN}Tips for best results:${NC}"
    echo "- The prompt uses structured steps to guide thorough analysis"
    echo "- Claude will provide a summary table for quick reference"
    echo "- Look for specific file/line references in the recommendations"
    echo "- Consider running follow-up questions on specific concerns"
}
