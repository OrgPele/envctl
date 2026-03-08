#!/usr/bin/env bash

# Requirement helpers (core database/redis plumbing).

if [ -z "${DOCKER_PORT_MAP_CACHE+x}" ]; then
    declare -A DOCKER_PORT_MAP_CACHE=()
fi
DOCKER_PORT_MAP_READY=${DOCKER_PORT_MAP_READY:-false}

requirements_docker_cmd() {
    if [ "$(type -t docker_cmd)" = "function" ]; then
        docker_cmd "$@"
        return $?
    fi
    docker "$@"
}

requirements_docker_probe() {
    if [ "$(type -t docker_probe)" = "function" ]; then
        docker_probe "$@"
        return $?
    fi
    requirements_docker_cmd "$@"
}

docker_ps_names() {
    if [ "$(type -t docker_ps_names_cached)" = "function" ]; then
        docker_ps_names_cached
    else
        requirements_docker_cmd ps --format '{{.Names}}' 2>/dev/null || true
    fi
}

docker_ps_all_names() {
    if [ "$(type -t docker_ps_all_names_cached)" = "function" ]; then
        docker_ps_all_names_cached
    else
        requirements_docker_cmd ps -a --format '{{.Names}}' 2>/dev/null || true
    fi
}

if [ "$(type -t docker_ps_names_contains)" != "function" ]; then
    docker_ps_names_contains() {
        local needle=$1
        [ -n "$needle" ] || return 1
        local line
        while IFS= read -r line; do
            [ "$line" = "$needle" ] && return 0
        done <<< "$(docker_ps_names)"
        return 1
    }
fi

if [ "$(type -t docker_ps_all_names_contains)" != "function" ]; then
    docker_ps_all_names_contains() {
        local needle=$1
        [ -n "$needle" ] || return 1
        local line
        while IFS= read -r line; do
            [ "$line" = "$needle" ] && return 0
        done <<< "$(docker_ps_all_names)"
        return 1
    }
fi

docker_ps_ids() {
    if [ "$(type -t docker_ps_ids_cached)" = "function" ]; then
        docker_ps_ids_cached
    else
        requirements_docker_cmd ps --format '{{.ID}}' 2>/dev/null || true
    fi
}

docker_port_map_refresh() {
    DOCKER_PORT_MAP_CACHE=()
    local id=""
    while IFS= read -r id; do
        [ -n "$id" ] || continue
        requirements_docker_cmd inspect -f '{{.Name}}|{{range $p, $conf := .NetworkSettings.Ports}}{{if $conf}}{{range $conf}}{{printf "%s|%s\n" $p .HostPort}}{{end}}{{end}}{{end}}' "$id" 2>/dev/null \
            | while IFS='|' read -r name port_proto host_port; do
                [ -n "$name" ] || continue
                [ -n "$port_proto" ] || continue
                [ -n "$host_port" ] || continue
                name="${name#/}"
                local internal_port="${port_proto%%/*}"
                if [ -n "$internal_port" ] && [ -n "$host_port" ]; then
                    DOCKER_PORT_MAP_CACHE["${host_port}|${internal_port}"]="$name"
                fi
            done
    done < <(docker_ps_ids)
    DOCKER_PORT_MAP_READY=true
}

docker_port_map_container_for() {
    local host_port=$1
    local internal_port=${2:-5432}
    if [ "${RUN_SH_REFRESH_CACHE:-false}" = true ]; then
        DOCKER_PORT_MAP_READY=false
    fi
    if [ "$DOCKER_PORT_MAP_READY" != true ]; then
        docker_port_map_refresh
    fi
    local key="${host_port}|${internal_port}"
    echo "${DOCKER_PORT_MAP_CACHE[$key]:-}"
}

if [ "$(type -t docker_container_label_value)" != "function" ]; then
    docker_container_label_value() {
        local container=$1
        local label=$2
        [ -n "$container" ] || return 1
        [ -n "$label" ] || return 1
        requirements_docker_cmd inspect -f "{{index .Config.Labels \"${label}\"}}" "$container" 2>/dev/null || true
    }
fi

requirements_fast_enabled() {
    [ "${RUN_SH_FAST_REQUIREMENTS:-false}" = true ]
}

requirements_cache_ttl() {
    local ttl="${RUN_SH_REQUIREMENTS_TTL:-300}"
    if [[ "$ttl" =~ ^[0-9]+$ ]] && [ "$ttl" -gt 0 ]; then
        echo "$ttl"
        return 0
    fi
    echo 0
}

requirements_cache_healthy() {
    local label=$1
    local ttl
    ttl=$(requirements_cache_ttl)
    [ "$ttl" -gt 0 ] || return 1
    if [ "$(type -t run_cache_load)" = "function" ]; then
        run_cache_load
    fi
    if [ "$(type -t run_cache_requirements_fresh)" = "function" ]; then
        run_cache_requirements_fresh "$label" "$ttl"
        return $?
    fi
    return 1
}

requirements_cache_record() {
    local label=$1
    local status=$2
    if [ "$(type -t run_cache_set_requirements)" = "function" ]; then
        run_cache_set_requirements "$label" "$status"
    fi
}

start_postgres() {
    if [ "${ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE:-false}" = "true" ]; then
        echo -e "${YELLOW}Skipping PostgreSQL container start (ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE is set)${NC}"
        return 0
    fi
    if [ "${POSTGRES_MAIN_ENABLE:-true}" != "true" ]; then
        echo -e "${YELLOW}Skipping PostgreSQL container start (POSTGRES_MAIN_ENABLE=false)${NC}"
        return 0
    fi
    echo -e "${BLUE}Checking PostgreSQL...${NC}"

    # Check if container exists
    if docker_ps_all_names_contains "$DB_CONTAINER_NAME"; then
        # Container exists, check if running
        if ! docker_ps_names_contains "$DB_CONTAINER_NAME"; then
            if ! is_port_free "$DB_PORT"; then
                handle_port_conflict "$DB_PORT" "PostgreSQL"
                case $? in
                    0) ;;
                    2)
                        echo -e "${YELLOW}Skipping PostgreSQL container start; using existing service on port $DB_PORT.${NC}"
                        return 0
                        ;;
                    *)
                        echo -e "${RED}PostgreSQL startup aborted due to port conflict.${NC}"
                        return 1
                        ;;
                esac
            fi
            echo "Starting existing PostgreSQL container..."
            requirements_docker_cmd start "$DB_CONTAINER_NAME"
            if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
                docker_ps_cache_refresh
            fi
        else
            echo "PostgreSQL container already running"
        fi
    else
        if ! is_port_free "$DB_PORT"; then
            handle_port_conflict "$DB_PORT" "PostgreSQL"
            case $? in
                0) ;;
                2)
                    echo -e "${YELLOW}Skipping PostgreSQL container start; using existing service on port $DB_PORT.${NC}"
                    return 0
                    ;;
                *)
                    echo -e "${RED}PostgreSQL startup aborted due to port conflict.${NC}"
                    return 1
                    ;;
            esac
        fi
        # Create new container
        echo "Creating new PostgreSQL container..."
        requirements_docker_cmd run -d \
            --name "$DB_CONTAINER_NAME" \
            -e POSTGRES_USER="$DB_USER" \
            -e POSTGRES_PASSWORD="$DB_PASSWORD" \
            -e POSTGRES_DB="$DB_NAME" \
            -p "$DB_PORT:5432" \
            postgres:15-alpine
        if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
            docker_ps_cache_refresh
        fi
    fi

    # Wait for PostgreSQL to be ready
    echo -e "${YELLOW}Waiting for PostgreSQL to be ready...${NC}"
    if requirements_fast_enabled && docker_ps_names_contains "$DB_CONTAINER_NAME"; then
        if requirements_cache_healthy "postgres:${DB_CONTAINER_NAME}"; then
            echo -e "${GREEN}✓ PostgreSQL is ready (cached)${NC}"
            return 0
        fi
        if requirements_docker_probe exec "$DB_CONTAINER_NAME" pg_isready -U "$DB_USER" &> /dev/null; then
            echo -e "${GREEN}✓ PostgreSQL is ready${NC}"
            requirements_cache_record "postgres:${DB_CONTAINER_NAME}" "healthy"
            return 0
        fi
    fi
    local probe_timeout_streak=0
    local probe_timeout_limit="${RUN_SH_DOCKER_PROBE_TIMEOUT_STREAK_LIMIT:-3}"
    if ! [[ "$probe_timeout_limit" =~ ^[0-9]+$ ]] || [ "$probe_timeout_limit" -lt 1 ]; then
        probe_timeout_limit=3
    fi
    for i in {1..30}; do
        if requirements_docker_probe exec "$DB_CONTAINER_NAME" pg_isready -U "$DB_USER" &> /dev/null; then
            echo -e "${GREEN}✓ PostgreSQL is ready${NC}"
            requirements_cache_record "postgres:${DB_CONTAINER_NAME}" "healthy"
            return 0
        fi
        if [ "${DOCKER_LAST_TIMEOUT:-false}" = true ]; then
            probe_timeout_streak=$((probe_timeout_streak + 1))
            if [ "$probe_timeout_streak" -ge "$probe_timeout_limit" ]; then
                echo -e "${RED}✗ PostgreSQL readiness checks timed out repeatedly (${probe_timeout_streak}/${probe_timeout_limit})${NC}"
                if [ "$(type -t docker_print_timeout_hint_once)" = "function" ]; then
                    docker_print_timeout_hint_once
                fi
                return 1
            fi
        else
            probe_timeout_streak=0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo -e "${YELLOW}Still waiting for PostgreSQL... (${i}/30)${NC}"
        fi
        sleep 1
    done

    echo -e "${RED}✗ PostgreSQL failed to start${NC}"
    return 1
}

# Function to start Redis container

start_redis() {
    if [ "${ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE:-false}" = "true" ]; then
        echo -e "${YELLOW}Skipping Redis container start (ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE is set)${NC}"
        return 0
    fi
    if [ "${REDIS_ENABLE:-true}" != "true" ]; then
        echo -e "${YELLOW}Skipping Redis container start (REDIS_ENABLE=false)${NC}"
        return 0
    fi
    if [ "${REDIS_MAIN_ENABLE:-true}" != "true" ]; then
        echo -e "${YELLOW}Skipping Redis container start (REDIS_MAIN_ENABLE=false)${NC}"
        return 0
    fi
    echo -e "${BLUE}Checking Redis...${NC}"

    # Check if container exists
    if docker_ps_all_names_contains "$REDIS_CONTAINER_NAME"; then
        # Container exists, check if running
        if ! docker_ps_names_contains "$REDIS_CONTAINER_NAME"; then
            if ! is_port_free "$REDIS_PORT"; then
                handle_port_conflict "$REDIS_PORT" "Redis"
                case $? in
                    0) ;;
                    2)
                        echo -e "${YELLOW}Skipping Redis container start; using existing service on port $REDIS_PORT.${NC}"
                        return 0
                        ;;
                    *)
                        echo -e "${RED}Redis startup aborted due to port conflict.${NC}"
                        return 1
                        ;;
                esac
            fi
            echo "Starting existing Redis container..."
            requirements_docker_cmd start "$REDIS_CONTAINER_NAME"
            if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
                docker_ps_cache_refresh
            fi
        else
            echo "Redis container already running"
        fi
    else
        if ! is_port_free "$REDIS_PORT"; then
            handle_port_conflict "$REDIS_PORT" "Redis"
            case $? in
                0) ;;
                2)
                    echo -e "${YELLOW}Skipping Redis container start; using existing service on port $REDIS_PORT.${NC}"
                    return 0
                    ;;
                *)
                    echo -e "${RED}Redis startup aborted due to port conflict.${NC}"
                    return 1
                    ;;
            esac
        fi
        # Create new container
        echo "Creating new Redis container..."
        requirements_docker_cmd run -d \
            --name "$REDIS_CONTAINER_NAME" \
            -p "$REDIS_PORT:6379" \
            redis:7-alpine
        if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
            docker_ps_cache_refresh
        fi
    fi

    # Wait for Redis to be ready
    echo -e "${YELLOW}Waiting for Redis to be ready...${NC}"
    if requirements_fast_enabled && docker_ps_names_contains "$REDIS_CONTAINER_NAME"; then
        if requirements_cache_healthy "redis:${REDIS_CONTAINER_NAME}"; then
            echo -e "${GREEN}✓ Redis is ready (cached)${NC}"
            return 0
        fi
        if requirements_docker_probe exec "$REDIS_CONTAINER_NAME" redis-cli ping &> /dev/null; then
            echo -e "${GREEN}✓ Redis is ready${NC}"
            requirements_cache_record "redis:${REDIS_CONTAINER_NAME}" "healthy"
            return 0
        fi
    fi
    local probe_timeout_streak=0
    local probe_timeout_limit="${RUN_SH_DOCKER_PROBE_TIMEOUT_STREAK_LIMIT:-3}"
    if ! [[ "$probe_timeout_limit" =~ ^[0-9]+$ ]] || [ "$probe_timeout_limit" -lt 1 ]; then
        probe_timeout_limit=3
    fi
    for i in {1..30}; do
        if requirements_docker_probe exec "$REDIS_CONTAINER_NAME" redis-cli ping &> /dev/null; then
            echo -e "${GREEN}✓ Redis is ready${NC}"
            requirements_cache_record "redis:${REDIS_CONTAINER_NAME}" "healthy"
            return 0
        fi
        if [ "${DOCKER_LAST_TIMEOUT:-false}" = true ]; then
            probe_timeout_streak=$((probe_timeout_streak + 1))
            if [ "$probe_timeout_streak" -ge "$probe_timeout_limit" ]; then
                echo -e "${RED}✗ Redis readiness checks timed out repeatedly (${probe_timeout_streak}/${probe_timeout_limit})${NC}"
                if [ "$(type -t docker_print_timeout_hint_once)" = "function" ]; then
                    docker_print_timeout_hint_once
                fi
                return 1
            fi
        else
            probe_timeout_streak=0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo -e "${YELLOW}Still waiting for Redis... (${i}/30)${NC}"
        fi
        sleep 1
    done

    echo -e "${RED}✗ Redis failed to start${NC}"
    return 1
}

select_redis_port_for_main() {
    if [ "${ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE:-false}" = "true" ]; then
        return 0
    fi
    if [ "${REDIS_ENABLE:-true}" != "true" ]; then
        return 0
    fi
    if [ "${REDIS_MAIN_ENABLE:-true}" != "true" ]; then
        return 0
    fi
    local desired="${REDIS_PORT:-$REDIS_PORT_BASE}"
    local actual=""

    if docker_ps_names_contains "$REDIS_CONTAINER_NAME"; then
        actual=$(container_host_port "$REDIS_CONTAINER_NAME" "6379")
        if [ -n "$actual" ]; then
            if [ "$actual" != "$desired" ]; then
                echo -e "${YELLOW}Redis container already running on port ${actual}; using it for Main.${NC}"
            fi
            REDIS_PORT="$actual"
            export REDIS_PORT
            return 0
        fi
    fi

    if ! is_port_free "$desired"; then
        local reserved=""
        reserved=$(reserve_requirement_port "$desired" "" "" "redis")
        if [ "$reserved" != "$desired" ]; then
            echo -e "${YELLOW}Redis port ${desired} is in use; using ${reserved} for Main.${NC}"
        fi
        REDIS_PORT="$reserved"
        export REDIS_PORT
    fi
    return 0
}

# Function to check if port is available

if [ "$(type -t tree_uses_supabase)" != "function" ]; then
    tree_uses_supabase() {
        return 1
    }
fi

if [ "$(type -t tree_uses_n8n)" != "function" ]; then
    tree_uses_n8n() {
        return 1
    }
fi

if [ "$(type -t tree_uses_redis)" != "function" ]; then
    tree_uses_redis() {
        local tree_dir=${1:-}
        [ -n "$tree_dir" ] || return 1
        tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1

        if [ "${REDIS_ENABLE:-true}" != "true" ]; then
            return 1
        fi

        local base_dir=""
        if [ -n "${BASE_DIR:-}" ]; then
            base_dir=$(cd "$BASE_DIR" && pwd -P 2>/dev/null) || base_dir="$BASE_DIR"
        fi

        if [ -n "$base_dir" ] && [ "$tree_dir" = "$base_dir" ]; then
            [ "${REDIS_MAIN_ENABLE:-true}" = "true" ]
            return $?
        fi

        if [ "${REDIS_ALL_TREES:-true}" = "true" ]; then
            return 0
        fi

        local filter="${REDIS_TREE_FILTER:-}"
        [ -n "$filter" ] || return 1

        local feature_name=""
        if [ "$(type -t worktree_identity_from_dir)" = "function" ]; then
            local identity=""
            identity=$(worktree_identity_from_dir "$tree_dir" 2>/dev/null || true)
            if [ -n "$identity" ]; then
                feature_name="${identity%%|*}"
            fi
        fi
        if [ -z "$feature_name" ]; then
            feature_name=$(basename "$tree_dir")
        fi

        local entry=""
        IFS=',' read -r -a filter_entries <<< "$filter"
        for entry in "${filter_entries[@]}"; do
            entry="${entry#"${entry%%[![:space:]]*}"}"
            entry="${entry%"${entry##*[![:space:]]}"}"
            [ -z "$entry" ] && continue
            if [ "$entry" = "$feature_name" ]; then
                return 0
            fi
        done
        return 1
    }
fi

per_tree_requirements_enabled() {
    if [ "${PER_TREE_REQUIREMENTS:-false}" = true ] && [ "${TREES_MODE:-false}" = true ] && [ "${DOCKER_MODE:-false}" != true ]; then
        return 0
    fi
    return 1
}

docker_host_gateway_args() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "--add-host" "host.docker.internal:host-gateway"
    fi
}

requirement_container_name() {
    local base_name=$1
    local tree_dir=$2
    local identity
    identity=$(worktree_identity_from_dir "$tree_dir") || return 1
    local feature="${identity%%|*}"
    local iter="${identity#*|}"
    local suffix
    suffix=$(slugify_underscore "${feature}_${iter}")
    echo "${base_name}-${suffix}"
}

requirement_volume_name() {
    local base_name=$1
    local tree_dir=$2
    local identity
    identity=$(worktree_identity_from_dir "$tree_dir") || return 1
    local feature="${identity%%|*}"
    local iter="${identity#*|}"
    local suffix
    suffix=$(slugify_underscore "${feature}_${iter}")
    echo "${base_name}-${suffix}-data"
}

find_container_by_port() {
    local host_port=$1
    local internal_port=${2:-5432}
    local name=""
    name=$(docker_port_map_container_for "$host_port" "$internal_port")
    if [ -n "$name" ]; then
        echo "$name"
        return 0
    fi
    return 1
}

container_volume_for_path() {
    local container=$1
    local mount_path=$2
    requirements_docker_cmd inspect -f "{{range .Mounts}}{{if eq .Destination \"${mount_path}\"}}{{.Name}}{{end}}{{end}}" "$container" 2>/dev/null || true
}

container_host_port() {
    local container=$1
    local internal_port=$2
    requirements_docker_cmd inspect -f "{{(index (index .NetworkSettings.Ports \"${internal_port}/tcp\") 0).HostPort}}" "$container" 2>/dev/null || true
}

container_running_on_host_port() {
    local container=$1
    local host_port=$2
    local internal_port=${3:-5432}
    [ -n "$container" ] || return 1
    [ -n "$host_port" ] || return 1
    local status=""
    status=$(requirements_docker_cmd inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)
    if [ "$status" != "running" ]; then
        return 1
    fi
    local mapped_port=""
    mapped_port=$(container_host_port "$container" "$internal_port")
    [ -n "$mapped_port" ] && [ "$mapped_port" = "$host_port" ]
}

lock_requirement_port_from_container() {
    local container=$1
    local internal_port=$2
    local label=$3
    [ -n "$container" ] || return 1
    local host_port=""
    host_port=$(container_host_port "$container" "$internal_port")
    if [ -n "$host_port" ]; then
        service_ports[$host_port]="$label"
        if [ "$(type -t port_state_record)" = "function" ]; then
            port_state_record "$host_port" "$label" "reserved"
        fi
        echo "$host_port"
        return 0
    fi
    return 1
}

lock_requirement_port_from_map() {
    local host_port=$1
    local internal_port=$2
    local expected_container=$3
    local label=$4
    local expected_project=${5:-}
    local expected_service=${6:-}
    [ -n "$host_port" ] || return 1
    [ -n "$expected_container" ] || return 1
    local mapped=""
    mapped=$(docker_port_map_container_for "$host_port" "$internal_port")
    if [ -z "$mapped" ]; then
        if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
            debug_log_line "TRACE" "port.lock.map.miss host_port=${host_port} internal_port=${internal_port} label=${label}"
        fi
        return 1
    fi
    if [ -n "$expected_project" ] || [ -n "$expected_service" ]; then
        local mapped_project=""
        local mapped_service=""
        mapped_project=$(docker_container_label_value "$mapped" "com.docker.compose.project")
        mapped_service=$(docker_container_label_value "$mapped" "com.docker.compose.service")
        if [ -n "$expected_project" ] && [ "$mapped_project" != "$expected_project" ]; then
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "port.lock.map.mismatch host_port=${host_port} internal_port=${internal_port} expected_project=${expected_project} actual_project=${mapped_project:-} expected_service=${expected_service:-} actual_service=${mapped_service:-}"
            fi
            return 1
        fi
        if [ -n "$expected_service" ] && [ "$mapped_service" != "$expected_service" ]; then
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "port.lock.map.mismatch host_port=${host_port} internal_port=${internal_port} expected_project=${expected_project:-} actual_project=${mapped_project:-} expected_service=${expected_service} actual_service=${mapped_service:-}"
            fi
            return 1
        fi
    fi
    if [ "$mapped" = "$expected_container" ]; then
        service_ports[$host_port]="$label"
        if [ "$(type -t port_state_record)" = "function" ]; then
            port_state_record "$host_port" "$label" "reserved"
        fi
        if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
            debug_log_line "TRACE" "port.lock.map.success host_port=${host_port} internal_port=${internal_port} label=${label} container=${mapped}"
        fi
        echo "$host_port"
        return 0
    fi
    if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
        debug_log_line "TRACE" "port.lock.map.container_mismatch host_port=${host_port} internal_port=${internal_port} label=${label} expected=${expected_container} actual=${mapped}"
    fi
    return 1
}

reserve_requirement_port() {
    local port=$1
    local avoid_a=${2:-}
    local avoid_b=${3:-}
    local label=${4:-requirements}
    local max_port=${5:-65000}

    while true; do
        if [ "$port" -gt "$max_port" ]; then
            echo "ERROR: No free requirement port found up to $max_port for $label" >&2
            return 1
        fi
        if [ -n "$avoid_a" ] && [ "$port" -eq "$avoid_a" ]; then
            ((port++))
            continue
        fi
        if [ -n "$avoid_b" ] && [ "$port" -eq "$avoid_b" ]; then
            ((port++))
            continue
        fi
        if [ -n "${service_ports[$port]:-}" ] && [ "${service_ports[$port]}" = "$label" ]; then
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "port.reserve.skip port=${port} label=${label} reason=already_reserved"
            fi
            echo "$port"
            return 0
        fi
        if is_port_free "$port"; then
            local reserved=true
            if [ "${RUN_SH_OPT_PARALLEL_TREES:-false}" = true ] && [ "${RUN_SH_PARALLEL_WORKER:-false}" = true ] && [ "$(type -t port_reserve)" = "function" ]; then
                if ! port_reserve "$port"; then
                    reserved=false
                fi
            fi
            if [ "$reserved" = true ]; then
                service_ports[$port]="$label"
                if [ "$(type -t port_state_record)" = "function" ]; then
                    port_state_record "$port" "$label" "reserved"
                fi
                echo "$port"
                return 0
            fi
        fi
        ((port++))
    done
}

normalize_requirement_port_from_cfg() {
    local port=$1
    local base=$2
    local offset=$3
    if [ -z "$port" ]; then
        echo ""
        return 0
    fi
    if ! [[ "$port" =~ ^[0-9]+$ ]] || ! [[ "$base" =~ ^[0-9]+$ ]] || ! [[ "$offset" =~ ^-?[0-9]+$ ]]; then
        echo "$port"
        return 0
    fi
    if [ "$offset" -ne 0 ] && [ "$port" -eq "$base" ]; then
        echo ""
        return 0
    fi
    echo "$port"
}

resolve_tree_requirement_ports() {
    local tree_dir=$1
    local backend_port_initial=$2
    local backend_port_final=$3
    local frontend_port_final=$4
    local port_offset=$5
    local out_db_var=${6:-}
    local out_redis_var=${7:-}

    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    local env_file="${tree_dir%/}/.env"
    local resolved_db_port=""
    local resolved_redis_port=""
    local resolved_n8n_port=""
    local db_locked=false
    local redis_locked=false
    local n8n_locked=false

    local uses_supabase=false
    if tree_uses_supabase "$tree_dir"; then
        uses_supabase=true
    fi
    local uses_redis=false
    if tree_uses_redis "$tree_dir"; then
        uses_redis=true
    fi
    local project_name=""
    if [ "$uses_supabase" = true ]; then
        project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
        if [ -z "$project_name" ]; then
            project_name=$(supabase_compose_project_name "$tree_dir" 2>/dev/null || true)
        fi
    fi

    local db_container=""
    local db_container_id=""
    if [ "$uses_supabase" = true ]; then
        db_container_id=$(supabase_service_container_id "$tree_dir" "supabase-db" 2>/dev/null || true)
        db_container=$(supabase_container_name "$tree_dir" "supabase-db" 2>/dev/null || true)
    else
        db_container=$(requirement_container_name "$DB_CONTAINER_NAME" "$tree_dir" 2>/dev/null || true)
        db_container_id="$db_container"
    fi
    if [ -z "$db_container_id" ] && [ -n "$db_container" ]; then
        db_container_id="$db_container"
    fi
    if [ -n "$db_container_id" ]; then
        local existing_db_port=""
        existing_db_port=$(lock_requirement_port_from_container "$db_container_id" "5432" "${tree_dir}:db")
        if [ -n "$existing_db_port" ]; then
            resolved_db_port="$existing_db_port"
            db_locked=true
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "requirements.port.lock tree=${tree_dir} service=db source=container container=${db_container_id} port=${existing_db_port}"
            fi
        fi
    fi

    local redis_container=""
    if [ "$uses_redis" = true ]; then
        redis_container=$(requirement_container_name "$REDIS_CONTAINER_NAME" "$tree_dir" 2>/dev/null || true)
        if [ -n "$redis_container" ]; then
            local existing_redis_port=""
            existing_redis_port=$(lock_requirement_port_from_container "$redis_container" "6379" "${tree_dir}:redis")
            if [ -n "$existing_redis_port" ]; then
                resolved_redis_port="$existing_redis_port"
                redis_locked=true
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock tree=${tree_dir} service=redis source=container container=${redis_container} port=${existing_redis_port}"
                fi
            fi
        fi
    fi

    local n8n_container=""
    local n8n_container_id=""
    if tree_uses_n8n "$tree_dir"; then
        n8n_container_id=$(supabase_service_container_id "$tree_dir" "n8n" 2>/dev/null || true)
        n8n_container=$(supabase_container_name "$tree_dir" "n8n" 2>/dev/null || true)
        if [ -z "$n8n_container_id" ] && [ -n "$n8n_container" ]; then
            n8n_container_id="$n8n_container"
        fi
        if [ -n "$n8n_container_id" ]; then
            local existing_n8n_port=""
            existing_n8n_port=$(lock_requirement_port_from_container "$n8n_container_id" "5678" "${tree_dir}:n8n")
            if [ -n "$existing_n8n_port" ]; then
                resolved_n8n_port="$existing_n8n_port"
                n8n_locked=true
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock tree=${tree_dir} service=n8n source=container container=${n8n_container_id} port=${existing_n8n_port}"
                fi
            fi
        fi
    fi

    if [ "$db_locked" = false ]; then
        resolved_db_port=$(read_env_value "$env_file" "DB_PORT")
    fi
    if [ "$uses_redis" = true ] && [ "$redis_locked" = false ]; then
        resolved_redis_port=$(read_env_value "$env_file" "REDIS_PORT")
    fi
    if [ "$n8n_locked" = false ] && tree_uses_n8n "$tree_dir"; then
        resolved_n8n_port=$(read_env_value "$env_file" "N8N_HOST_PORT")
        if [ -z "$resolved_n8n_port" ]; then
            resolved_n8n_port=$(read_env_value "$env_file" "N8N_PORT")
        fi
    fi

    if per_tree_requirements_enabled; then
        local ports_from_cfg=""
        ports_from_cfg=$(read_ports_from_worktree_config "${tree_dir%/}")
        if [ -n "$ports_from_cfg" ]; then
            local cfg_backend=""
            local cfg_frontend=""
            local cfg_db=""
            local cfg_redis=""
            IFS='|' read -r cfg_backend cfg_frontend cfg_db cfg_redis <<< "$ports_from_cfg"
            if [ "$db_locked" = false ] && [ -n "$cfg_db" ]; then
                resolved_db_port="$cfg_db"
            fi
            if [ "$uses_redis" = true ] && [ "$redis_locked" = false ] && [ -n "$cfg_redis" ]; then
                resolved_redis_port="$cfg_redis"
            fi
        fi
    fi

    if [ "$db_locked" = false ] && [ -z "$resolved_db_port" ] || { [ "$uses_redis" = true ] && [ "$redis_locked" = false ] && [ -z "$resolved_redis_port" ]; }; then
        local ports_from_cfg
        ports_from_cfg=$(read_ports_from_worktree_config "${tree_dir%/}")
        if [ -n "$ports_from_cfg" ]; then
            local cfg_backend=""
            local cfg_frontend=""
            local cfg_db=""
            local cfg_redis=""
            IFS='|' read -r cfg_backend cfg_frontend cfg_db cfg_redis <<< "$ports_from_cfg"
            if [ "$db_locked" = false ] && [ -z "$resolved_db_port" ]; then
                resolved_db_port="$cfg_db"
            fi
            if [ "$uses_redis" = true ] && [ "$redis_locked" = false ] && [ -z "$resolved_redis_port" ]; then
                resolved_redis_port="$cfg_redis"
            fi
        fi
    fi

    local base_offset=0
    if [[ "$backend_port_initial" =~ ^[0-9]+$ ]] && [[ "$BACKEND_PORT_BASE" =~ ^[0-9]+$ ]]; then
        base_offset=$((backend_port_initial - BACKEND_PORT_BASE))
        if [ "$base_offset" -lt 0 ]; then
            base_offset="$port_offset"
        fi
    else
        base_offset="$port_offset"
    fi
    local db_port_base="$DB_PORT_BASE"
    if [ "$uses_supabase" = true ]; then
        db_port_base="${SUPABASE_DB_PORT_BASE:-54322}"
    fi
    resolved_db_port=$(normalize_requirement_port_from_cfg "$resolved_db_port" "$db_port_base" "$base_offset")
    if [ "$uses_redis" = true ]; then
        resolved_redis_port=$(normalize_requirement_port_from_cfg "$resolved_redis_port" "$REDIS_PORT_BASE" "$base_offset")
    else
        resolved_redis_port=""
    fi

    local db_default=false
    local redis_default=false
    local n8n_default=false
    local n8n_base="${N8N_PORT_BASE:-5678}"

    if [ -z "$resolved_db_port" ]; then
        resolved_db_port=$((db_port_base + base_offset))
        db_default=true
    fi
    if [ "$uses_redis" = true ] && [ -z "$resolved_redis_port" ]; then
        resolved_redis_port=$((REDIS_PORT_BASE + base_offset))
        redis_default=true
    fi
    if tree_uses_n8n "$tree_dir" && [ -z "$resolved_n8n_port" ]; then
        resolved_n8n_port=$((n8n_base + base_offset))
        n8n_default=true
    fi

    if [ "$db_default" = true ] && [ "$backend_port_final" -ne "$backend_port_initial" ]; then
        local diff=$((backend_port_final - backend_port_initial))
        resolved_db_port=$((resolved_db_port + diff))
        if [ "$uses_redis" = true ] && [ "$redis_default" = true ]; then
            resolved_redis_port=$((resolved_redis_port + diff))
        fi
        if [ "$n8n_default" = true ]; then
            resolved_n8n_port=$((resolved_n8n_port + diff))
        fi
    fi

    if [ "$db_locked" = false ] && [ -n "$resolved_db_port" ] && [ -n "$db_container" ]; then
        if [ "$uses_supabase" = true ]; then
            if lock_requirement_port_from_map "$resolved_db_port" "5432" "$db_container" "${tree_dir}:db" "$project_name" "supabase-db" >/dev/null 2>&1; then
                db_locked=true
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock tree=${tree_dir} service=db source=map port=${resolved_db_port}"
                fi
            fi
        else
            if lock_requirement_port_from_map "$resolved_db_port" "5432" "$db_container" "${tree_dir}:db" >/dev/null 2>&1; then
                db_locked=true
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock tree=${tree_dir} service=db source=map port=${resolved_db_port}"
                fi
            fi
        fi
    fi

    if [ "$uses_redis" = true ] && [ "$redis_locked" = false ] && [ -n "$resolved_redis_port" ] && [ -n "$redis_container" ]; then
        if lock_requirement_port_from_map "$resolved_redis_port" "6379" "$redis_container" "${tree_dir}:redis" >/dev/null 2>&1; then
            redis_locked=true
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "requirements.port.lock tree=${tree_dir} service=redis source=map port=${resolved_redis_port}"
            fi
        fi
    fi

    if tree_uses_n8n "$tree_dir" && [ "$n8n_locked" = false ] && [ -n "$resolved_n8n_port" ] && [ -n "$n8n_container" ]; then
        if lock_requirement_port_from_map "$resolved_n8n_port" "5678" "$n8n_container" "${tree_dir}:n8n" "$project_name" "n8n" >/dev/null 2>&1; then
            n8n_locked=true
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "requirements.port.lock tree=${tree_dir} service=n8n source=map port=${resolved_n8n_port}"
            fi
        fi
    fi

    local requested_db="$resolved_db_port"
    if [ "$db_locked" = false ]; then
        resolved_db_port=$(reserve_requirement_port "$resolved_db_port" "$backend_port_final" "$frontend_port_final" "${tree_dir}:db")
        if [ "$uses_redis" = true ] && [ "$db_default" = true ] && [ "$redis_default" = true ]; then
            local db_diff=$((resolved_db_port - requested_db))
            if [ "$db_diff" -ne 0 ]; then
                resolved_redis_port=$((resolved_redis_port + db_diff))
            fi
        fi
    fi

    if [ "$uses_redis" = true ] && [ "$redis_locked" = false ]; then
        resolved_redis_port=$(reserve_requirement_port "$resolved_redis_port" "$backend_port_final" "$frontend_port_final" "${tree_dir}:redis")
    fi

    if tree_uses_n8n "$tree_dir"; then
        if [ "$n8n_locked" = false ]; then
            resolved_n8n_port=$(reserve_requirement_port "$resolved_n8n_port" "$backend_port_final" "$frontend_port_final" "${tree_dir}:n8n")
        fi
        if [ -n "$resolved_n8n_port" ]; then
            N8N_TREE_PORTS["$tree_dir"]="$resolved_n8n_port"
        fi
    fi

    if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
        debug_log_line "INFO" "requirements.ports tree=${tree_dir} resolved_db_port=${resolved_db_port} db_locked=${db_locked} resolved_redis_port=${resolved_redis_port} redis_locked=${redis_locked} resolved_n8n_port=${resolved_n8n_port:-} n8n_locked=${n8n_locked}"
    fi

    if [ -n "$out_db_var" ] || [ -n "$out_redis_var" ]; then
        [ -n "$out_db_var" ] && printf -v "$out_db_var" '%s' "$resolved_db_port"
        [ -n "$out_redis_var" ] && printf -v "$out_redis_var" '%s' "$resolved_redis_port"
        return 0
    fi

    echo "${resolved_db_port}|${resolved_redis_port}"
}

tree_requirement_ports_for_dir() {
    local tree_dir=$1
    local backend_port=$2
    local out_db_var=${3:-}
    local out_redis_var=${4:-}

    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0
    local env_file="${tree_dir%/}/.env"
    local resolved_db_port=""
    local resolved_redis_port=""
    local db_locked=false
    local redis_locked=false

    local uses_supabase=false
    if tree_uses_supabase "$tree_dir"; then
        uses_supabase=true
    fi
    local uses_redis=false
    if tree_uses_redis "$tree_dir"; then
        uses_redis=true
    fi
    local project_name=""
    if [ "$uses_supabase" = true ]; then
        project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
        if [ -z "$project_name" ]; then
            project_name=$(supabase_compose_project_name "$tree_dir" 2>/dev/null || true)
        fi
    fi

    local db_container=""
    local db_container_id=""
    if [ "$uses_supabase" = true ]; then
        db_container_id=$(supabase_service_container_id "$tree_dir" "supabase-db" 2>/dev/null || true)
        db_container=$(supabase_container_name "$tree_dir" "supabase-db" 2>/dev/null || true)
    else
        db_container=$(requirement_container_name "$DB_CONTAINER_NAME" "$tree_dir" 2>/dev/null || true)
        db_container_id="$db_container"
    fi

    if [ -z "$db_container_id" ] && [ -n "$db_container" ]; then
        db_container_id="$db_container"
    fi
    if [ -n "$db_container_id" ]; then
        local existing_db_port=""
        existing_db_port=$(lock_requirement_port_from_container "$db_container_id" "5432" "${tree_dir}:db")
        if [ -n "$existing_db_port" ]; then
            resolved_db_port="$existing_db_port"
            db_locked=true
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "requirements.port.lock.runtime tree=${tree_dir} service=db source=container container=${db_container_id} port=${existing_db_port}"
            fi
        fi
    fi

    local redis_container=""
    if [ "$uses_redis" = true ]; then
        redis_container=$(requirement_container_name "$REDIS_CONTAINER_NAME" "$tree_dir" 2>/dev/null || true)
        if [ -n "$redis_container" ]; then
            local existing_redis_port=""
            existing_redis_port=$(lock_requirement_port_from_container "$redis_container" "6379" "${tree_dir}:redis")
            if [ -n "$existing_redis_port" ]; then
                resolved_redis_port="$existing_redis_port"
                redis_locked=true
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock.runtime tree=${tree_dir} service=redis source=container container=${redis_container} port=${existing_redis_port}"
                fi
            fi
        fi
    fi

    if [ "$db_locked" = false ]; then
        resolved_db_port=$(read_env_value "$env_file" "DB_PORT")
    fi
    if [ "$uses_redis" = true ] && [ "$redis_locked" = false ]; then
        resolved_redis_port=$(read_env_value "$env_file" "REDIS_PORT")
    fi

    local base_offset=0
    if [[ "$backend_port" =~ ^[0-9]+$ ]] && [[ "$BACKEND_PORT_BASE" =~ ^[0-9]+$ ]]; then
        base_offset=$((backend_port - BACKEND_PORT_BASE))
        if [ "$base_offset" -lt 0 ]; then
            base_offset=0
        fi
    fi

    if per_tree_requirements_enabled; then
        local ports_from_cfg=""
        ports_from_cfg=$(read_ports_from_worktree_config "${tree_dir%/}")
        if [ -n "$ports_from_cfg" ]; then
            local cfg_backend=""
            local cfg_frontend=""
            local cfg_db=""
            local cfg_redis=""
            IFS='|' read -r cfg_backend cfg_frontend cfg_db cfg_redis <<< "$ports_from_cfg"
            if [ "$db_locked" = false ] && [ -n "$cfg_db" ]; then
                resolved_db_port="$cfg_db"
            fi
            if [ "$uses_redis" = true ] && [ "$redis_locked" = false ] && [ -n "$cfg_redis" ]; then
                resolved_redis_port="$cfg_redis"
            fi
        fi
    fi

    if [ -z "$resolved_db_port" ] || { [ "$uses_redis" = true ] && [ -z "$resolved_redis_port" ]; }; then
        local ports_from_cfg
        ports_from_cfg=$(read_ports_from_worktree_config "${tree_dir%/}")
        if [ -n "$ports_from_cfg" ]; then
            local cfg_backend=""
            local cfg_frontend=""
            local cfg_db=""
            local cfg_redis=""
            IFS='|' read -r cfg_backend cfg_frontend cfg_db cfg_redis <<< "$ports_from_cfg"
            if [ "$db_locked" = false ] && [ -z "$resolved_db_port" ]; then
                resolved_db_port="$cfg_db"
            fi
            if [ "$uses_redis" = true ] && [ "$redis_locked" = false ] && [ -z "$resolved_redis_port" ]; then
                resolved_redis_port="$cfg_redis"
            fi
        fi
    fi

    local db_port_base="$DB_PORT_BASE"
    if [ "$uses_supabase" = true ]; then
        db_port_base="${SUPABASE_DB_PORT_BASE:-54322}"
    fi
    resolved_db_port=$(normalize_requirement_port_from_cfg "$resolved_db_port" "$db_port_base" "$base_offset")
    if [ "$uses_redis" = true ]; then
        resolved_redis_port=$(normalize_requirement_port_from_cfg "$resolved_redis_port" "$REDIS_PORT_BASE" "$base_offset")
    else
        resolved_redis_port=""
    fi

    if [ "$db_locked" = false ] && [ -n "$resolved_db_port" ] && [ -n "$db_container" ]; then
        if [ "$uses_supabase" = true ]; then
            if lock_requirement_port_from_map "$resolved_db_port" "5432" "$db_container" "${tree_dir}:db" "$project_name" "supabase-db" >/dev/null 2>&1; then
                db_locked=true
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock.runtime tree=${tree_dir} service=db source=map port=${resolved_db_port}"
                fi
            fi
        else
            if lock_requirement_port_from_map "$resolved_db_port" "5432" "$db_container" "${tree_dir}:db" >/dev/null 2>&1; then
                db_locked=true
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock.runtime tree=${tree_dir} service=db source=map port=${resolved_db_port}"
                fi
            fi
        fi
    fi
    if [ "$uses_redis" = true ] && [ "$redis_locked" = false ] && [ -n "$resolved_redis_port" ] && [ -n "$redis_container" ]; then
        if lock_requirement_port_from_map "$resolved_redis_port" "6379" "$redis_container" "${tree_dir}:redis" >/dev/null 2>&1; then
            redis_locked=true
            if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                debug_log_line "TRACE" "requirements.port.lock.runtime tree=${tree_dir} service=redis source=map port=${resolved_redis_port}"
            fi
        fi
    fi

    if [ -z "$resolved_db_port" ] || { [ "$uses_redis" = true ] && [ -z "$resolved_redis_port" ]; }; then
        [ -z "$resolved_db_port" ] && resolved_db_port=$((db_port_base + base_offset))
        if [ "$uses_redis" = true ] && [ -z "$resolved_redis_port" ]; then
            resolved_redis_port=$((REDIS_PORT_BASE + base_offset))
        fi
    fi

    if tree_uses_n8n "$tree_dir" && [ -z "${N8N_TREE_PORTS[$tree_dir]:-}" ]; then
        local base_offset=$((backend_port - BACKEND_PORT_BASE))
        if [ "$base_offset" -lt 0 ]; then
            base_offset=0
        fi
        local n8n_base="${N8N_PORT_BASE:-5678}"
        local resolved_n8n_port=""
        local n8n_container=""
        local n8n_container_id=""
        n8n_container_id=$(supabase_service_container_id "$tree_dir" "n8n" 2>/dev/null || true)
        n8n_container=$(supabase_container_name "$tree_dir" "n8n" 2>/dev/null || true)
        if [ -z "$n8n_container_id" ] && [ -n "$n8n_container" ]; then
            n8n_container_id="$n8n_container"
        fi
        if [ -n "$n8n_container_id" ]; then
            local existing_n8n_port=""
            existing_n8n_port=$(lock_requirement_port_from_container "$n8n_container_id" "5678" "${tree_dir}:n8n")
            if [ -n "$existing_n8n_port" ]; then
                N8N_TREE_PORTS["$tree_dir"]="$existing_n8n_port"
                if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                    debug_log_line "TRACE" "requirements.port.lock.runtime tree=${tree_dir} service=n8n source=container container=${n8n_container_id} port=${existing_n8n_port}"
                fi
            fi
        fi
        if [ -z "${N8N_TREE_PORTS[$tree_dir]:-}" ]; then
            resolved_n8n_port=$(read_env_value "$env_file" "N8N_HOST_PORT")
            if [ -z "$resolved_n8n_port" ]; then
                resolved_n8n_port=$(read_env_value "$env_file" "N8N_PORT")
            fi
            if [ -z "$resolved_n8n_port" ]; then
                resolved_n8n_port=$((n8n_base + base_offset))
            fi
            if [ -n "$n8n_container" ]; then
                if lock_requirement_port_from_map "$resolved_n8n_port" "5678" "$n8n_container" "${tree_dir}:n8n" "$project_name" "n8n" >/dev/null 2>&1; then
                    N8N_TREE_PORTS["$tree_dir"]="$resolved_n8n_port"
                    if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
                        debug_log_line "TRACE" "requirements.port.lock.runtime tree=${tree_dir} service=n8n source=map port=${resolved_n8n_port}"
                    fi
                fi
            fi
        fi
        if [ -z "${N8N_TREE_PORTS[$tree_dir]:-}" ]; then
            resolved_n8n_port=$(reserve_requirement_port "$resolved_n8n_port" "$backend_port" "" "${tree_dir}:n8n")
            N8N_TREE_PORTS["$tree_dir"]="$resolved_n8n_port"
        fi
    fi

    if [ "$(type -t debug_log_line)" = "function" ] && [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
        debug_log_line "INFO" "requirements.ports.runtime tree=${tree_dir} resolved_db_port=${resolved_db_port} db_locked=${db_locked} resolved_redis_port=${resolved_redis_port} redis_locked=${redis_locked}"
    fi

    if [ -n "$out_db_var" ] || [ -n "$out_redis_var" ]; then
        [ -n "$out_db_var" ] && printf -v "$out_db_var" '%s' "$resolved_db_port"
        [ -n "$out_redis_var" ] && printf -v "$out_redis_var" '%s' "$resolved_redis_port"
        return 0
    fi

    echo "${resolved_db_port}|${resolved_redis_port}"
}

start_tree_postgres() {
    local tree_dir=$1
    local db_port=$2
    local container_name
    container_name=$(requirement_container_name "$DB_CONTAINER_NAME" "$tree_dir") || return 1
    local volume_name=""
    volume_name=$(requirement_volume_name "$DB_CONTAINER_NAME" "$tree_dir" 2>/dev/null || true)

    local current_port=""
    local created=false
    if docker_ps_all_names_contains "$container_name"; then
        current_port=$(container_host_port "$container_name" "5432")
        if [ -n "$current_port" ] && [ "$current_port" != "$db_port" ]; then
            requirements_docker_cmd rm -f "$container_name" >/dev/null 2>&1 || true
        fi
    fi

    if docker_ps_names_contains "$container_name"; then
        echo "PostgreSQL container already running (${container_name})"
    elif docker_ps_all_names_contains "$container_name"; then
        local should_start_existing=true
        if ! is_port_free "$db_port"; then
            if container_running_on_host_port "$container_name" "$db_port" "5432"; then
                echo "PostgreSQL container already running (${container_name})"
                should_start_existing=false
            else
                echo -e "${RED}PostgreSQL port ${db_port} is already in use for ${container_name}${NC}"
                return 1
            fi
        fi
        if [ "$should_start_existing" = true ]; then
            echo "Starting existing PostgreSQL container (${container_name})..."
            requirements_docker_cmd start "$container_name" >/dev/null
            if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
                docker_ps_cache_refresh
            fi
        fi
    else
        local already_running=false
        if ! is_port_free "$db_port"; then
            if container_running_on_host_port "$container_name" "$db_port" "5432"; then
                echo "PostgreSQL container already running (${container_name})"
                already_running=true
            else
                echo -e "${RED}PostgreSQL port ${db_port} is already in use for ${container_name}${NC}"
                return 1
            fi
        fi
        if [ "$already_running" != true ]; then
            echo "Creating PostgreSQL container (${container_name})..."
            local volume_args=()
            if [ -n "$volume_name" ]; then
                requirements_docker_cmd volume create "$volume_name" >/dev/null 2>&1 || true
                if [ "$SEED_REQUIREMENTS_ACTIVE" = true ] && [ "$SEED_REQUIREMENTS_MODE" = "volume" ]; then
                    seed_tree_postgres_volume "$volume_name" || true
                fi
                volume_args=(-v "${volume_name}:/var/lib/postgresql/data")
            fi
            requirements_docker_cmd run -d \
                --name "$container_name" \
                -e POSTGRES_USER="$DB_USER" \
                -e POSTGRES_PASSWORD="$DB_PASSWORD" \
                -e POSTGRES_DB="$DB_NAME" \
                "${volume_args[@]}" \
                -p "$db_port:5432" \
                postgres:15-alpine >/dev/null
            created=true
            if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
                docker_ps_cache_refresh
            fi
        fi
    fi

    echo -e "${YELLOW}Waiting for PostgreSQL (${container_name}) to be ready...${NC}"
    if requirements_fast_enabled && docker_ps_names_contains "$container_name"; then
        if requirements_cache_healthy "postgres:${container_name}"; then
            echo -e "${GREEN}✓ PostgreSQL ready (${container_name}) (cached)${NC}"
            return 0
        fi
        if requirements_docker_probe exec "$container_name" pg_isready -U "$DB_USER" &> /dev/null; then
            echo -e "${GREEN}✓ PostgreSQL ready (${container_name})${NC}"
            requirements_cache_record "postgres:${container_name}" "healthy"
            if [ "$created" = true ] && [ "$SEED_REQUIREMENTS_ACTIVE" = true ] && [ "$SEED_REQUIREMENTS_MODE" != "volume" ]; then
                seed_tree_postgres_from_base "$container_name" || true
            fi
            return 0
        fi
    fi
    local probe_timeout_streak=0
    local probe_timeout_limit="${RUN_SH_DOCKER_PROBE_TIMEOUT_STREAK_LIMIT:-3}"
    if ! [[ "$probe_timeout_limit" =~ ^[0-9]+$ ]] || [ "$probe_timeout_limit" -lt 1 ]; then
        probe_timeout_limit=3
    fi
    for i in {1..30}; do
        if requirements_docker_probe exec "$container_name" pg_isready -U "$DB_USER" &> /dev/null; then
            echo -e "${GREEN}✓ PostgreSQL ready (${container_name})${NC}"
            requirements_cache_record "postgres:${container_name}" "healthy"
            if [ "$created" = true ] && [ "$SEED_REQUIREMENTS_ACTIVE" = true ] && [ "$SEED_REQUIREMENTS_MODE" != "volume" ]; then
                seed_tree_postgres_from_base "$container_name" || true
            fi
            return 0
        fi
        if [ "${DOCKER_LAST_TIMEOUT:-false}" = true ]; then
            probe_timeout_streak=$((probe_timeout_streak + 1))
            if [ "$probe_timeout_streak" -ge "$probe_timeout_limit" ]; then
                echo -e "${RED}✗ PostgreSQL readiness checks timed out repeatedly for ${container_name} (${probe_timeout_streak}/${probe_timeout_limit})${NC}"
                if [ "$(type -t docker_print_timeout_hint_once)" = "function" ]; then
                    docker_print_timeout_hint_once
                fi
                return 1
            fi
        else
            probe_timeout_streak=0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo -e "${YELLOW}Still waiting for PostgreSQL (${container_name})... (${i}/30)${NC}"
        fi
        sleep 1
    done
    echo -e "${RED}✗ PostgreSQL failed to start (${container_name})${NC}"
    return 1
}

start_tree_redis() {
    local tree_dir=$1
    local redis_port=$2
    if ! tree_uses_redis "$tree_dir"; then
        echo -e "${YELLOW}Skipping Redis for ${tree_dir} (disabled by Redis configuration).${NC}"
        return 0
    fi
    local container_name
    container_name=$(requirement_container_name "$REDIS_CONTAINER_NAME" "$tree_dir") || return 1
    local volume_name=""
    volume_name=$(requirement_volume_name "$REDIS_CONTAINER_NAME" "$tree_dir" 2>/dev/null || true)

    local current_port=""
    local created=false
    if docker_ps_all_names_contains "$container_name"; then
        current_port=$(container_host_port "$container_name" "6379")
        if [ -n "$current_port" ] && [ "$current_port" != "$redis_port" ]; then
            requirements_docker_cmd rm -f "$container_name" >/dev/null 2>&1 || true
        fi
    fi

    if docker_ps_names_contains "$container_name"; then
        echo "Redis container already running (${container_name})"
    elif docker_ps_all_names_contains "$container_name"; then
        local should_start_existing=true
        if ! is_port_free "$redis_port"; then
            if container_running_on_host_port "$container_name" "$redis_port" "6379"; then
                echo "Redis container already running (${container_name})"
                should_start_existing=false
            else
                echo -e "${RED}Redis port ${redis_port} is already in use for ${container_name}${NC}"
                return 1
            fi
        fi
        if [ "$should_start_existing" = true ]; then
            echo "Starting existing Redis container (${container_name})..."
            requirements_docker_cmd start "$container_name" >/dev/null
            if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
                docker_ps_cache_refresh
            fi
        fi
    else
        local already_running=false
        if ! is_port_free "$redis_port"; then
            if container_running_on_host_port "$container_name" "$redis_port" "6379"; then
                echo "Redis container already running (${container_name})"
                already_running=true
            else
                echo -e "${RED}Redis port ${redis_port} is already in use for ${container_name}${NC}"
                return 1
            fi
        fi
        if [ "$already_running" != true ]; then
            echo "Creating Redis container (${container_name})..."
            local volume_args=()
            if [ -n "$volume_name" ]; then
                requirements_docker_cmd volume create "$volume_name" >/dev/null 2>&1 || true
                if [ "$SEED_REQUIREMENTS_ACTIVE" = true ] && [ "$SEED_REQUIREMENTS_MODE" = "volume" ]; then
                    seed_tree_redis_volume "$volume_name" || true
                fi
                volume_args=(-v "${volume_name}:/data")
            fi
            if requirements_docker_cmd run -d \
                --name "$container_name" \
                "${volume_args[@]}" \
                -p "$redis_port:6379" \
                redis:7-alpine >/dev/null 2>&1; then
                created=true
                if [ "$SEED_REQUIREMENTS_ACTIVE" = true ] && [ "$SEED_REQUIREMENTS_MODE" != "volume" ]; then
                    seed_tree_redis_from_base "$container_name" || true
                fi
            else
                if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
                    docker_ps_cache_refresh
                fi
                if docker_ps_all_names_contains "$container_name"; then
                    local existing_port=""
                    existing_port=$(container_host_port "$container_name" "6379")
                    if [ -n "$existing_port" ] && [ "$existing_port" != "$redis_port" ]; then
                        requirements_docker_cmd rm -f "$container_name" >/dev/null 2>&1 || true
                        if requirements_docker_cmd run -d \
                            --name "$container_name" \
                            "${volume_args[@]}" \
                            -p "$redis_port:6379" \
                            redis:7-alpine >/dev/null 2>&1; then
                            created=true
                            if [ "$SEED_REQUIREMENTS_ACTIVE" = true ] && [ "$SEED_REQUIREMENTS_MODE" != "volume" ]; then
                                seed_tree_redis_from_base "$container_name" || true
                            fi
                        else
                            echo -e "${RED}✗ Failed to recreate Redis container (${container_name})${NC}"
                            return 1
                        fi
                    else
                        echo "Redis container already exists (${container_name}); starting..."
                        requirements_docker_cmd start "$container_name" >/dev/null 2>&1 || true
                    fi
                else
                    echo -e "${RED}✗ Failed to create Redis container (${container_name})${NC}"
                    return 1
                fi
            fi
            if [ "$(type -t docker_ps_cache_refresh)" = "function" ]; then
                docker_ps_cache_refresh
            fi
        fi
    fi

    echo -e "${YELLOW}Waiting for Redis (${container_name}) to be ready...${NC}"
    if requirements_fast_enabled && docker_ps_names_contains "$container_name"; then
        if requirements_cache_healthy "redis:${container_name}"; then
            echo -e "${GREEN}✓ Redis ready (${container_name}) (cached)${NC}"
            return 0
        fi
        if requirements_docker_probe exec "$container_name" redis-cli ping &> /dev/null; then
            echo -e "${GREEN}✓ Redis ready (${container_name})${NC}"
            requirements_cache_record "redis:${container_name}" "healthy"
            return 0
        fi
    fi
    local probe_timeout_streak=0
    local probe_timeout_limit="${RUN_SH_DOCKER_PROBE_TIMEOUT_STREAK_LIMIT:-3}"
    if ! [[ "$probe_timeout_limit" =~ ^[0-9]+$ ]] || [ "$probe_timeout_limit" -lt 1 ]; then
        probe_timeout_limit=3
    fi
    for i in {1..30}; do
        if requirements_docker_probe exec "$container_name" redis-cli ping &> /dev/null; then
            echo -e "${GREEN}✓ Redis ready (${container_name})${NC}"
            requirements_cache_record "redis:${container_name}" "healthy"
            return 0
        fi
        if [ "${DOCKER_LAST_TIMEOUT:-false}" = true ]; then
            probe_timeout_streak=$((probe_timeout_streak + 1))
            if [ "$probe_timeout_streak" -ge "$probe_timeout_limit" ]; then
                echo -e "${RED}✗ Redis readiness checks timed out repeatedly for ${container_name} (${probe_timeout_streak}/${probe_timeout_limit})${NC}"
                if [ "$(type -t docker_print_timeout_hint_once)" = "function" ]; then
                    docker_print_timeout_hint_once
                fi
                return 1
            fi
        else
            probe_timeout_streak=0
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo -e "${YELLOW}Still waiting for Redis (${container_name})... (${i}/30)${NC}"
        fi
        sleep 1
    done
    echo -e "${RED}✗ Redis failed to start (${container_name})${NC}"
    return 1
}

ensure_tree_requirements() {
    local tree_dir=$1
    local db_port=$2
    local redis_port=$3
    local n8n_port=${4:-}
    local uses_redis=false
    if tree_uses_redis "$tree_dir"; then
        uses_redis=true
    fi

    local redis_label="$redis_port"
    if [ "$uses_redis" != true ]; then
        redis_label="disabled"
    fi
    echo -e "${CYAN}Starting requirements for ${tree_dir} (db:${db_port}, redis:${redis_label})...${NC}"
    if tree_uses_supabase "$tree_dir"; then
        register_supabase_tree_config "$tree_dir" "$db_port"
        if ! start_tree_supabase "$tree_dir" "$db_port"; then
            return 1
        fi
        if [ "$uses_redis" = true ]; then
            apply_supabase_env_for_tree "$tree_dir" "$db_port" "$redis_port"
        else
            apply_supabase_env_for_tree "$tree_dir" "$db_port" ""
        fi
        if tree_uses_n8n "$tree_dir"; then
            if [ -z "$n8n_port" ]; then
                tree_n8n_port_for_dir "$tree_dir" "" n8n_port
            fi
            apply_n8n_env_for_tree "$tree_dir" "$n8n_port"
            if ! start_tree_n8n "$tree_dir" "$n8n_port"; then
                return 1
            fi
        fi
    else
        if ! start_tree_postgres "$tree_dir" "$db_port"; then
            return 1
        fi
    fi
    if [ "$uses_redis" = true ]; then
        if ! start_tree_redis "$tree_dir" "$redis_port"; then
            return 1
        fi
    fi
    return 0
}

collect_tree_roots_from_services() {
    declare -A seen=()
    local roots=()
    local name
    for name in "${!service_info[@]}"; do
        service_info_fields "$name" pid port log type dir || continue
        [ -z "$dir" ] && continue
        local root
        root=$(dirname "$dir")
        if ! worktree_identity_from_dir "$root" >/dev/null 2>&1; then
            continue
        fi
        if [ -z "${seen[$root]:-}" ]; then
            roots+=("$root")
            seen["$root"]=1
        fi
    done
    printf '%s\n' "${roots[@]}"
}

cleanup_tree_requirements() {
    local remove_volumes=${1:-false}
    local roots=()
    while IFS= read -r root; do
        [ -n "$root" ] && roots+=("$root")
    done < <(collect_tree_roots_from_services)

    # Fallback: if service_info didn't yield any roots but Docker has supportopia containers,
    # sweep by naming convention to catch orphaned infra that started before apps registered.
    if [ ${#roots[@]} -eq 0 ]; then
        local orphan_names=""
        orphan_names=$(requirements_docker_cmd ps -a --format '{{.Names}}' 2>/dev/null | grep -E "^${ENVCTL_PROJECT_PREFIX:-supportopia}-(supabase|redis)-" || true)
        if [ -n "$orphan_names" ]; then
            echo "Sweeping orphaned infrastructure containers by naming convention..."
            local cname=""
            while IFS= read -r cname; do
                [ -n "$cname" ] || continue
                echo "  Stopping orphaned container: $cname"
                if [ "$remove_volumes" = true ]; then
                    requirements_docker_cmd rm -f -v "$cname" >/dev/null 2>&1 || true
                else
                    requirements_docker_cmd stop "$cname" >/dev/null 2>&1 || true
                fi
            done <<< "$orphan_names"
        else
            echo "No tree requirements to stop"
        fi
        return 0
    fi

    local root
    for root in "${roots[@]}"; do
        local db_container=""
        local redis_container=""
        local db_volume=""
        local redis_volume=""
        redis_container=$(requirement_container_name "$REDIS_CONTAINER_NAME" "$root" 2>/dev/null || true)
        redis_volume=$(requirement_volume_name "$REDIS_CONTAINER_NAME" "$root" 2>/dev/null || true)

        if tree_uses_supabase "$root"; then
            stop_tree_supabase "$root" "$remove_volumes"
        else
            db_container=$(requirement_container_name "$DB_CONTAINER_NAME" "$root" 2>/dev/null || true)
            db_volume=$(requirement_volume_name "$DB_CONTAINER_NAME" "$root" 2>/dev/null || true)
            if [ "$remove_volumes" = true ]; then
                [ -n "$db_container" ] && requirements_docker_cmd rm -f -v "$db_container" >/dev/null 2>&1 || true
                [ -n "$db_volume" ] && requirements_docker_cmd volume rm "$db_volume" >/dev/null 2>&1 || true
            else
                [ -n "$db_container" ] && requirements_docker_cmd stop "$db_container" >/dev/null 2>&1 || true
            fi
        fi

        if [ "$remove_volumes" = true ]; then
            [ -n "$redis_container" ] && requirements_docker_cmd rm -f -v "$redis_container" >/dev/null 2>&1 || true
            [ -n "$redis_volume" ] && requirements_docker_cmd volume rm "$redis_volume" >/dev/null 2>&1 || true
        else
            [ -n "$redis_container" ] && requirements_docker_cmd stop "$redis_container" >/dev/null 2>&1 || true
        fi
    done

    if [ "$remove_volumes" = true ]; then
        [ -n "$SEED_REQUIREMENTS_DB_VOLUME" ] && requirements_docker_cmd volume rm "$SEED_REQUIREMENTS_DB_VOLUME" >/dev/null 2>&1 || true
        [ -n "$SEED_REQUIREMENTS_REDIS_VOLUME" ] && requirements_docker_cmd volume rm "$SEED_REQUIREMENTS_REDIS_VOLUME" >/dev/null 2>&1 || true
    fi
}

collect_service_roots_from_services() {
    declare -A seen=()
    local roots=()
    local name
    for name in "${!service_info[@]}"; do
        service_info_fields "$name" pid port log type dir || continue
        [ -z "$dir" ] && continue
        local root
        root=$(dirname "$dir")
        [ -n "$root" ] || continue
        if [ -z "${seen[$root]:-}" ]; then
            roots+=("$root")
            seen["$root"]=1
        fi
    done
    printf '%s\n' "${roots[@]}"
}

stop_tree_requirements_for_root() {
    local root=$1
    local remove_volumes=${2:-false}
    root=$(cd "$root" && pwd -P 2>/dev/null) || return 0

    local is_worktree=false
    if worktree_identity_from_dir "$root" >/dev/null 2>&1; then
        is_worktree=true
    fi

    local redis_container=""
    local redis_volume=""
    if [ "$is_worktree" = true ]; then
        redis_container=$(requirement_container_name "$REDIS_CONTAINER_NAME" "$root" 2>/dev/null || true)
        redis_volume=$(requirement_volume_name "$REDIS_CONTAINER_NAME" "$root" 2>/dev/null || true)
    else
        redis_container="${REDIS_CONTAINER_NAME:-}"
    fi

    if tree_uses_supabase "$root"; then
        stop_tree_supabase "$root" "$remove_volumes"
    else
        local db_container=""
        local db_volume=""
        if [ "$is_worktree" = true ]; then
            db_container=$(requirement_container_name "$DB_CONTAINER_NAME" "$root" 2>/dev/null || true)
            db_volume=$(requirement_volume_name "$DB_CONTAINER_NAME" "$root" 2>/dev/null || true)
        else
            db_container="${DB_CONTAINER_NAME:-}"
        fi
        if [ "$remove_volumes" = true ]; then
            [ -n "$db_container" ] && requirements_docker_cmd rm -f -v "$db_container" >/dev/null 2>&1 || true
            [ -n "$db_volume" ] && requirements_docker_cmd volume rm "$db_volume" >/dev/null 2>&1 || true
        else
            [ -n "$db_container" ] && requirements_docker_cmd rm -f "$db_container" >/dev/null 2>&1 || true
        fi
    fi

    if [ "$remove_volumes" = true ]; then
        [ -n "$redis_container" ] && requirements_docker_cmd rm -f -v "$redis_container" >/dev/null 2>&1 || true
        [ -n "$redis_volume" ] && requirements_docker_cmd volume rm "$redis_volume" >/dev/null 2>&1 || true
    else
        [ -n "$redis_container" ] && requirements_docker_cmd rm -f "$redis_container" >/dev/null 2>&1 || true
    fi
}

cleanup_state_requirements() {
    local remove_volumes=${1:-false}
    local roots=()
    while IFS= read -r root; do
        [ -n "$root" ] && roots+=("$root")
    done < <(collect_service_roots_from_services)

    if [ ${#roots[@]} -eq 0 ]; then
        echo "No state-scoped requirements to stop"
        return 0
    fi

    local root
    for root in "${roots[@]}"; do
        stop_tree_requirements_for_root "$root" "$remove_volumes"
    done

    if [ "$remove_volumes" = true ]; then
        [ -n "$SEED_REQUIREMENTS_DB_VOLUME" ] && requirements_docker_cmd volume rm "$SEED_REQUIREMENTS_DB_VOLUME" >/dev/null 2>&1 || true
        [ -n "$SEED_REQUIREMENTS_REDIS_VOLUME" ] && requirements_docker_cmd volume rm "$SEED_REQUIREMENTS_REDIS_VOLUME" >/dev/null 2>&1 || true
    fi
}
