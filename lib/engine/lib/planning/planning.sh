#!/usr/bin/env bash

# Planning selection helpers.

planning_dir_raw() {
    local raw="${ENVCTL_PLANNING_DIR:-docs/planning}"
    raw="${raw%/}"
    if [ -z "$raw" ]; then
        raw="docs/planning"
    fi
    printf '%s\n' "$raw"
}

planning_dir_path() {
    local raw
    raw=$(planning_dir_raw)
    if [[ "$raw" = /* ]]; then
        printf '%s\n' "$raw"
        return 0
    fi
    printf '%s/%s\n' "$BASE_DIR" "$raw"
}

planning_dir_display() {
    local dir
    dir=$(planning_dir_path)
    if [[ "$dir" == "$BASE_DIR/"* ]]; then
        printf '%s\n' "${dir#"$BASE_DIR"/}"
        return 0
    fi
    printf '%s\n' "$dir"
}

planning_file_path() {
    local rel=${1:-}
    local planning_dir
    planning_dir=$(planning_dir_path)
    printf '%s/%s\n' "$planning_dir" "$rel"
}

planning_normalize_selection_token() {
    local token=${1:-}
    local planning_raw planning_dir
    planning_raw=$(planning_dir_raw)
    planning_dir=$(planning_dir_path)

    token="${token#./}"
    token="${token#docs/planning/}"
    token="${token#${planning_raw}/}"
    token="${token#${planning_dir}/}"
    if [[ "$planning_raw" != /* ]]; then
        token="${token#${BASE_DIR}/${planning_raw}/}"
    fi
    printf '%s\n' "$token"
}

list_planning_files() {
    local planning_dir
    planning_dir=$(planning_dir_path)
    if [ ! -d "$planning_dir" ]; then
        return 1
    fi
    find "$planning_dir" -mindepth 2 -maxdepth 2 -type f -name "*.md" \
        ! -path "$planning_dir/Done/*/*" \
        ! -name "README.md" ! -name "*_PLAN.md" 2>/dev/null | \
        sed "s|^$planning_dir/||" | sort
}

list_done_planning_files() {
    local planning_dir
    planning_dir=$(planning_dir_path)
    local done_dir="$planning_dir/Done"
    if [ ! -d "$done_dir" ]; then
        return 0
    fi
    find "$done_dir" -mindepth 2 -maxdepth 2 -type f -name "*.md" \
        ! -name "README.md" ! -name "*_PLAN.md" 2>/dev/null | \
        sed "s|^$planning_dir/||" | sort
}


select_planning_files_interactive() {
    local files=("$@")
    local total=${#files[@]}
    if [ $total -eq 0 ]; then
        return 1
    fi

    local done_files=()
    if [ ${#PLANNING_DONE_FILES[@]} -gt 0 ]; then
        done_files=("${PLANNING_DONE_FILES[@]}")
    fi
    local done_total=${#done_files[@]}
    local menu_lines=$total
    if [ $done_total -gt 0 ]; then
        menu_lines=$((menu_lines + done_total + 1))
    fi

    declare -A selected=()
    local current=0
    local redraw=false
    local tty_state=""
    tty_state=$(tty_raw_on 2>/dev/null || true)
    menu_setup
    tty_flush_input
    tput civis >&2 2>/dev/null || true
    echo -e "${CYAN}Select planning files (↑/↓ move, Space toggle, ←/→ adjust count, Enter confirm, q cancel):${NC}" >&2

    for i in "${!files[@]}"; do
        local existing_count=${PLANNING_EXISTING_COUNTS["${files[$i]}"]:-0}
        selected[$i]=$existing_count
        local mark="[ ]"
        if [ "${selected[$i]:-0}" -gt 0 ]; then
            mark="[${selected[$i]}x]"
        fi
        if [ "$i" -eq "$current" ]; then
            local suffix=""
            if [ "$existing_count" -gt 0 ]; then
                suffix=" (existing ${existing_count})"
            fi
            echo -e "  ${GREEN}▶${NC} ${mark} ${CYAN}${files[$i]}${NC}${suffix}" >&2
        else
            local suffix=""
            if [ "$existing_count" -gt 0 ]; then
                suffix=" (existing ${existing_count})"
            fi
            echo -e "    ${mark} ${files[$i]}${suffix}" >&2
        fi
    done
    if [ $done_total -gt 0 ]; then
        echo -e "  ${BLUE}Done plans (read-only):${NC}" >&2
        for done_file in "${done_files[@]}"; do
            local done_key="${done_file#Done/}"
            local done_count=${PLANNING_DONE_COUNTS["$done_key"]:-0}
            local mark="[0x]"
            if [ "$done_count" -gt 0 ]; then
                mark="[${done_count}x]"
            fi
            echo -e "    ${BLUE}${mark} ${done_file}${NC}" >&2
        done
    fi

    while true; do
        key=$(read_key)
        case "$key" in
            noop)
                continue
                ;;
            esc|q|Q)
                tput cnorm >&2 2>/dev/null || true
                menu_cleanup "$tty_state"
                echo "" >&2
                echo ""
                return 1
                ;;
            '[A'|'OA')
                        ((current = (current - 1 + total) % total))
                        redraw=true
                        ;;
            '[B'|'OB')
                        ((current = (current + 1) % total))
                        redraw=true
                        ;;
            '[C'|'OC')
                        selected[$current]=$(( ${selected[$current]:-0} + 1 ))
                        redraw=true
                        ;;
            '[D'|'OD')
                        if [ "${selected[$current]:-0}" -gt 0 ]; then
                            selected[$current]=$(( ${selected[$current]:-0} - 1 ))
                        fi
                        redraw=true
                        ;;
            ' ')
                local existing_count=${PLANNING_EXISTING_COUNTS["${files[$current]}"]:-0}
                if [ "${selected[$current]:-0}" -gt 0 ]; then
                    selected[$current]=0
                else
                    if [ "$existing_count" -gt 0 ]; then
                        selected[$current]=$existing_count
                    else
                        selected[$current]=1
                    fi
                fi
                redraw=true
                ;;
            ''|enter)
                tput cnorm >&2 2>/dev/null || true
                menu_cleanup "$tty_state"
                echo "" >&2
                local outputs=()
                for i in "${!files[@]}"; do
                    local count=${selected[$i]:-0}
                    local existing_count=${PLANNING_EXISTING_COUNTS["${files[$i]}"]:-0}
                    if [ "$count" -gt 0 ] || [ "$existing_count" -gt 0 ]; then
                        outputs+=("${files[$i]}|${count}")
                    fi
                done
                if [ ${#outputs[@]} -eq 0 ]; then
                    return 1
                fi
                printf '%s\n' "${outputs[@]}"
                return 0
                ;;
        esac

        if [ "$redraw" = true ]; then
            printf "\033[%dA" "$menu_lines" >&2
            for i in "${!files[@]}"; do
                printf "\r\033[K" >&2
                local mark="[ ]"
                if [ "${selected[$i]:-0}" -gt 0 ]; then
                    mark="[${selected[$i]}x]"
                fi
                if [ "$i" -eq "$current" ]; then
                    local suffix=""
                    local existing_count=${PLANNING_EXISTING_COUNTS["${files[$i]}"]:-0}
                    if [ "$existing_count" -gt 0 ]; then
                        suffix=" (existing ${existing_count})"
                    fi
                    echo -e "  ${GREEN}▶${NC} ${mark} ${CYAN}${files[$i]}${NC}${suffix}" >&2
                else
                    local suffix=""
                    local existing_count=${PLANNING_EXISTING_COUNTS["${files[$i]}"]:-0}
                    if [ "$existing_count" -gt 0 ]; then
                        suffix=" (existing ${existing_count})"
                    fi
                    echo -e "    ${mark} ${files[$i]}${suffix}" >&2
                fi
            done
            if [ $done_total -gt 0 ]; then
                printf "\r\033[K" >&2
                echo -e "  ${BLUE}Done plans (read-only):${NC}" >&2
                for done_file in "${done_files[@]}"; do
                    printf "\r\033[K" >&2
                    local done_key="${done_file#Done/}"
                    local done_count=${PLANNING_DONE_COUNTS["$done_key"]:-0}
                    local mark="[0x]"
                    if [ "$done_count" -gt 0 ]; then
                        mark="[${done_count}x]"
                    fi
                    echo -e "    ${BLUE}${mark} ${done_file}${NC}" >&2
                done
            fi
            redraw=false
        fi
    done
}


select_planning_files() {
    local files=()
    while IFS= read -r file; do
        [ -n "$file" ] && files+=("$file")
    done < <(list_planning_files)

    PLANNING_DONE_FILES=()

    if [ ${#files[@]} -eq 0 ]; then
        local planning_display
        planning_display=$(planning_dir_display)
        echo -e "${RED}No planning files found in ${planning_display}.${NC}" >&2
        return 1
    fi
    declare -A PLANNING_EXISTING_COUNTS=()
    for file in "${files[@]}"; do
        PLANNING_EXISTING_COUNTS["$file"]=$(planning_existing_count "$file")
    done
    if [ -t 0 ] || [ -e /dev/tty ]; then
        select_planning_files_interactive "${files[@]}"
        return $?
    fi

    echo -e "${RED}No TTY available for planning selection.${NC}" >&2
    return 1
}


resolve_planning_files() {
    local selection_raw=$1
    local plans=()

    if [ -n "$selection_raw" ]; then
        local available_plans=()
        while IFS= read -r plan_file; do
            [ -n "$plan_file" ] && available_plans+=("$plan_file")
        done < <(list_planning_files)

        if [ ${#available_plans[@]} -eq 0 ]; then
            local planning_display
            planning_display=$(planning_dir_display)
            echo -e "${RED}No planning files found in ${planning_display}.${NC}" >&2
            return 1
        fi

        IFS=',' read -r -a plan_tokens <<< "$selection_raw"
        declare -A plan_counts=()
        declare -A seen_plans=()
        local token
        for token in "${plan_tokens[@]}"; do
            token=$(trim "$token")
            [ -z "$token" ] && continue

            local match=""
            local cleaned="$token"
            cleaned=$(planning_normalize_selection_token "$cleaned")
            if [[ "$cleaned" != *.md ]]; then
                cleaned="${cleaned}.md"
            fi

            if [[ "$cleaned" == */* ]]; then
                for plan_file in "${available_plans[@]}"; do
                    if [ "$plan_file" = "$cleaned" ]; then
                        match="$plan_file"
                        break
                    fi
                done
            else
                local basename_match=()
                for plan_file in "${available_plans[@]}"; do
                    if [ "$(basename "$plan_file")" = "$cleaned" ]; then
                        basename_match+=("$plan_file")
                    fi
                done
                if [ ${#basename_match[@]} -eq 1 ]; then
                    match="${basename_match[0]}"
                elif [ ${#basename_match[@]} -gt 1 ]; then
                    echo -e "${RED}Planning file name '${token}' is ambiguous. Use folder/name.${NC}" >&2
                    return 1
                fi
            fi

            if [ -z "$match" ]; then
                echo -e "${RED}Planning file not found: ${token}${NC}" >&2
                return 1
            fi

            plan_counts["$match"]=$(( ${plan_counts["$match"]:-0} + 1 ))
            if [ -z "${seen_plans[$match]:-}" ]; then
                plans+=("$match")
                seen_plans["$match"]=1
            fi
        done
    else
        while IFS= read -r plan_line; do
            [ -n "$plan_line" ] && plans+=("$plan_line")
        done < <(select_planning_files)
    fi

    if [ ${#plans[@]} -eq 0 ]; then
        return 1
    fi

    if [ -n "$selection_raw" ]; then
        local plan_file
        for plan_file in "${plans[@]}"; do
            local count="${plan_counts[$plan_file]:-0}"
            printf '%s|%s\n' "$plan_file" "$count"
        done
        return 0
    fi

    printf '%s\n' "${plans[@]}"
    return 0
}


planning_feature_name() {
    local rel="$1"
    rel="$(planning_normalize_selection_token "$rel")"
    local folder="${rel%%/*}"
    local file="${rel##*/}"
    file="${file%.md}"
    slugify_underscore "${folder}_${file}"
}


planning_existing_count() {
    local rel="$1"
    local feature_name
    feature_name=$(planning_feature_name "$rel")
    local tree_root
    tree_root=$(resolve_tree_root_for_feature "$feature_name") || { echo 0; return 0; }
    find "$tree_root" -maxdepth 1 -type d -name "[0-9]*" | wc -l | tr -d ' '
}

planning_move_to_done() {
    local rel="$1"
    [ -n "$rel" ] || return 1
    local planning_dir
    planning_dir=$(planning_dir_path)
    local src="$planning_dir/$rel"
    if [ ! -f "$src" ]; then
        return 0
    fi
    local rel_dir="${rel%/*}"
    if [ "$rel_dir" = "$rel" ]; then
        rel_dir="_misc"
    fi
    local base_name
    base_name="$(basename "$rel")"
    local done_dir="$planning_dir/Done/${rel_dir}"
    mkdir -p "$done_dir"
    local dest="$done_dir/$base_name"
    if [ -f "$dest" ]; then
        local stamp
        stamp=$(date +%Y%m%d%H%M%S)
        dest="$done_dir/${base_name%.md}-${stamp}.md"
    fi
    mv "$src" "$dest"
    echo -e "${GREEN}Moved ${rel} to Done/${rel_dir}/${base_name}.${NC}"
}
