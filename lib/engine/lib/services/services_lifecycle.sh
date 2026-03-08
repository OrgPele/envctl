#!/usr/bin/env bash

# Service lifecycle helpers.

handle_port_conflict() {
    local port=$1
    local service_label=$2

    while ! is_port_free "$port"; do
        echo -e "${YELLOW}Port $port is already in use.${NC}"

        local container_details
        container_details=$(docker_containers_on_port_details "$port")
        if [ -n "$container_details" ]; then
            echo -e "${YELLOW}Docker containers using port $port:${NC}"
            echo "$container_details"
        fi

        local listeners
        listeners=$(local_port_listeners "$port")
        if [ -n "$listeners" ]; then
            echo -e "${YELLOW}Local listeners on port $port:${NC}"
            echo "$listeners"
        fi

        local containers
        containers=$(docker_containers_on_port "$port")

        if [ "$INTERACTIVE_MODE" = true ]; then
            if [ -n "$containers" ]; then
                echo -e "${CYAN}Options:${NC} [s]kip $service_label start, s[t]op container(s), [r]etry, [q]uit"
            else
                echo -e "${CYAN}Options:${NC} [s]kip $service_label start, [r]etry, [q]uit"
            fi
            read -r choice
            case "${choice,,}" in
                s|skip)
                    return 2
                    ;;
                t|stop)
                    if [ -n "$containers" ]; then
                        echo -e "${YELLOW}Stopping container(s): $containers${NC}"
                        local -a _container_arr=()
                        read -r -a _container_arr <<< "$containers"
                        docker stop "${_container_arr[@]}" >/dev/null 2>&1 || true
                    else
                        echo -e "${RED}No Docker containers found on port $port.${NC}"
                    fi
                    ;;
                r|retry)
                    ;;
                q|quit)
                    return 1
                    ;;
                *)
                    echo -e "${RED}Invalid option.${NC}"
                    ;;
            esac
        else
            if [ "$FORCE_PORTS" = true ]; then
                if [ -n "$containers" ]; then
                    echo -e "${YELLOW}Stopping container(s): $containers${NC}"
                    local -a _container_arr=()
                    read -r -a _container_arr <<< "$containers"
                    docker stop "${_container_arr[@]}" >/dev/null 2>&1 || true
                else
                    force_kill_port "$port"
                fi
            else
                return 1
            fi
        fi
    done

    return 0
}

# Function to start PostgreSQL container

is_valid_http_url() {
    local value=$1
    if [ -z "$value" ]; then
        return 1
    fi
    [[ "$value" =~ ^https?://[^[:space:]]+$ ]]
}

file_mtime_epoch() {
    local path=$1
    [ -f "$path" ] || {
        echo 0
        return 0
    }
    local mtime=""
    mtime=$(stat -f %m "$path" 2>/dev/null || true)
    if [[ "$mtime" =~ ^[0-9]+$ ]]; then
        echo "$mtime"
        return 0
    fi
    mtime=$(stat -c %Y "$path" 2>/dev/null || true)
    if [[ "$mtime" =~ ^[0-9]+$ ]]; then
        echo "$mtime"
        return 0
    fi
    echo 0
}

max_mtime_epoch() {
    local max=0
    local path=""
    local mtime=0
    for path in "$@"; do
        mtime=$(file_mtime_epoch "$path")
        if [ "$mtime" -gt "$max" ]; then
            max=$mtime
        fi
    done
    echo "$max"
}

mark_noop_marker() {
    local marker=$1
    [ -n "$marker" ] || return 1
    mkdir -p "$(dirname "$marker")"
    : > "$marker"
}

marker_meta_file_path() {
    local marker=$1
    [ -n "$marker" ] || return 1
    echo "${marker}.meta"
}

marker_meta_read() {
    local marker=$1
    local meta_file
    meta_file=$(marker_meta_file_path "$marker") || return 1
    [ -f "$meta_file" ] || return 1
    cat "$meta_file" 2>/dev/null
}

marker_meta_write() {
    local marker=$1
    local value=${2:-}
    local meta_file
    meta_file=$(marker_meta_file_path "$marker") || return 1
    mkdir -p "$(dirname "$meta_file")"
    printf '%s' "$value" > "$meta_file"
}

hash_text() {
    local value=$1
    if command -v shasum >/dev/null 2>&1; then
        printf '%s' "$value" | shasum -a 256 | awk '{print $1}'
        return 0
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$value" | sha256sum | awk '{print $1}'
        return 0
    fi
    printf '%s' "$value" | cksum | awk '{print $1}'
}

hash_file_or_missing() {
    local path=$1
    if [ ! -f "$path" ]; then
        printf 'missing:%s' "$path"
        return 0
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$path" 2>/dev/null | awk '{print $1}'
        return 0
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$path" 2>/dev/null | awk '{print $1}'
        return 0
    fi
    cksum "$path" 2>/dev/null | awk '{print $1}'
}

reliability_strict_enabled() {
    [ "${RUN_SH_RELIABILITY_STRICT:-false}" = true ]
}

log_backend_dependency_failure() {
    local log_file=$1
    if reliability_strict_enabled; then
        echo "Backend dependency install failed; strict reliability mode enabled, aborting backend startup." >> "$log_file"
    else
        echo "Backend dependency install failed; continuing with startup attempt..." >> "$log_file"
    fi
}

classify_migration_failure() {
    local log_file=$1
    [ -f "$log_file" ] || {
        echo "generic"
        return 0
    }

    if grep -Eiq 'DuplicateTableError|relation "[^"]+" already exists' "$log_file"; then
        echo "duplicate_table"
        return 0
    fi

    if grep -Eiq 'DuplicateColumnError|column "[^"]+" already exists|duplicate column' "$log_file"; then
        echo "duplicate_column"
        return 0
    fi

    echo "generic"
}

log_backend_migration_failure() {
    local log_file=$1
    local failure_kind="generic"
    failure_kind=$(classify_migration_failure "$log_file")

    case "$failure_kind" in
        duplicate_table)
            echo "Detected migration conflict: duplicate table exists in target database." >> "$log_file"
            echo "Hint: the database schema appears ahead of Alembic revision tracking for this tree." >> "$log_file"
            echo "Hint: use an isolated tree database volume or reconcile Alembic revision state before rerunning." >> "$log_file"
            ;;
        duplicate_column)
            echo "Detected migration conflict: duplicate column exists in target database." >> "$log_file"
            echo "Hint: reconcile Alembic revision state before rerunning migrations." >> "$log_file"
            ;;
        *)
            echo "Migration failed; inspect the traceback above for root cause details." >> "$log_file"
            ;;
    esac

    if reliability_strict_enabled; then
        echo "Migration failed; strict reliability mode enabled, aborting backend startup." >> "$log_file"
    else
        echo "Migration failed; continuing because RUN_SH_RELIABILITY_STRICT=false." >> "$log_file"
    fi
}

runtime_python_version() {
    local version=""
    if [ -n "${PYTHON_BIN:-}" ] && command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        version=$($PYTHON_BIN -V 2>&1 || true)
    elif command -v python3 >/dev/null 2>&1; then
        version=$(python3 -V 2>&1 || true)
    elif command -v python >/dev/null 2>&1; then
        version=$(python -V 2>&1 || true)
    fi
    printf '%s' "$version"
}

runtime_poetry_version() {
    if command -v poetry >/dev/null 2>&1; then
        poetry --version 2>/dev/null || true
    fi
}

runtime_pip_version() {
    if command -v pip >/dev/null 2>&1; then
        pip --version 2>/dev/null || true
    fi
}

runtime_node_version() {
    if command -v node >/dev/null 2>&1; then
        node -v 2>/dev/null || true
    fi
}

runtime_npm_version() {
    if command -v npm >/dev/null 2>&1; then
        npm -v 2>/dev/null || true
    fi
}

build_dep_fingerprint() {
    local mode=$1
    shift
    local payload="mode=${mode}"
    payload+="|python=$(runtime_python_version)"
    payload+="|poetry=$(runtime_poetry_version)"
    payload+="|pip=$(runtime_pip_version)"
    payload+="|node=$(runtime_node_version)"
    payload+="|npm=$(runtime_npm_version)"
    local path=""
    for path in "$@"; do
        payload+="|${path}=$(hash_file_or_missing "$path")"
    done
    hash_text "$payload"
}

resolve_db_identity() {
    local requested_db_port=${1:-}
    local db_port="${requested_db_port:-${DB_PORT:-}}"
    local identity="db_port=${db_port}|db_name=${DB_NAME:-}|db_user=${DB_USER:-}"
    if command -v docker >/dev/null 2>&1 && [ -n "$db_port" ]; then
        local container_id=""
        container_id=$(docker ps --format '{{.ID}}|{{.Ports}}' 2>/dev/null | awk -F'|' -v p=":${db_port}->5432/tcp" 'index($2,p){print $1; exit}')
        if [ -n "$container_id" ]; then
            identity+="|container=${container_id}"
            local volume_name=""
            volume_name=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' "$container_id" 2>/dev/null || true)
            if [ -n "$volume_name" ]; then
                identity+="|volume=${volume_name}"
            fi
        fi
    fi
    hash_text "$identity"
}

maybe_release_reserved_port() {
    local port=$1
    [[ "$port" =~ ^[0-9]+$ ]] || return 0
    if [ "$(type -t port_is_reserved)" = "function" ] && [ "$(type -t port_release)" = "function" ]; then
        if port_is_reserved "$port"; then
            port_release "$port" || true
        fi
    fi
}

service_process_tree_pids() {
    local root_pid=$1
    [[ "$root_pid" =~ ^[0-9]+$ ]] || return 1

    local -a queue=("$root_pid")
    local -a seen=()
    local idx=0
    local parent=""
    local child=""
    local known=false

    while [ "$idx" -lt "${#queue[@]}" ]; do
        parent="${queue[$idx]}"
        idx=$((idx + 1))
        [ -n "$parent" ] || continue

        known=false
        for child in "${seen[@]}"; do
            if [ "$child" = "$parent" ]; then
                known=true
                break
            fi
        done
        if [ "$known" = true ]; then
            continue
        fi
        seen+=("$parent")

        if ! command -v pgrep >/dev/null 2>&1; then
            continue
        fi
        while IFS= read -r child; do
            [ -n "$child" ] || continue
            queue+=("$child")
        done < <(pgrep -P "$parent" 2>/dev/null || true)
    done

    printf '%s\n' "${seen[@]}"
}

service_listener_ports_for_pid() {
    local pid=$1
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    command -v lsof >/dev/null 2>&1 || return 1
    lsof -nP -a -p "$pid" -iTCP -sTCP:LISTEN 2>/dev/null \
        | awk 'NR>1 {print $9}' \
        | sed -E 's/.*:([0-9]+).*/\1/' \
        | grep -E '^[0-9]+$' \
        | sort -n -u
}

service_listener_ports_for_tree() {
    local root_pid=$1
    [[ "$root_pid" =~ ^[0-9]+$ ]] || return 1

    local -a tree_pids=()
    local pid=""
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        tree_pids+=("$pid")
    done < <(service_process_tree_pids "$root_pid" 2>/dev/null || true)

    if [ ${#tree_pids[@]} -eq 0 ]; then
        return 1
    fi

    local -a ports=()
    local candidate=""
    local existing=""
    local exists=false
    for pid in "${tree_pids[@]}"; do
        while IFS= read -r candidate; do
            [ -n "$candidate" ] || continue
            exists=false
            for existing in "${ports[@]}"; do
                if [ "$existing" = "$candidate" ]; then
                    exists=true
                    break
                fi
            done
            if [ "$exists" = false ]; then
                ports+=("$candidate")
            fi
        done < <(service_listener_ports_for_pid "$pid" 2>/dev/null || true)
    done

    if [ ${#ports[@]} -eq 0 ]; then
        return 1
    fi

    printf '%s\n' "${ports[@]}" | sort -n -u
}

service_select_listener_port() {
    local requested_port=$1
    shift || true
    [[ "$requested_port" =~ ^[0-9]+$ ]] || return 1

    local best_port=""
    local best_delta=""
    local candidate=""
    for candidate in "$@"; do
        [[ "$candidate" =~ ^[0-9]+$ ]] || continue
        if [ "$candidate" -eq "$requested_port" ]; then
            echo "$candidate"
            return 0
        fi
        local delta=$((candidate - requested_port))
        if [ "$delta" -lt 0 ]; then
            delta=$(( -delta ))
        fi
        if [ -z "$best_port" ] || [ "$delta" -lt "$best_delta" ]; then
            best_port="$candidate"
            best_delta="$delta"
        fi
    done

    [ -n "$best_port" ] || return 1
    echo "$best_port"
}

service_wait_for_bound_port() {
    local pid=$1
    local requested_port=$2
    local timeout=${3:-30}
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    [[ "$requested_port" =~ ^[0-9]+$ ]] || return 1
    if ! [[ "$timeout" =~ ^[0-9]+$ ]] || [ "$timeout" -lt 1 ]; then
        timeout=30
    fi

    if ! command -v lsof >/dev/null 2>&1; then
        if wait_for_port "$requested_port" "$timeout"; then
            echo "$requested_port"
            return 0
        fi
        return 1
    fi

    local start_ts
    start_ts=$(date +%s)

    while true; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi

        local -a listener_ports=()
        local listener_port=""
        while IFS= read -r listener_port; do
            [ -n "$listener_port" ] || continue
            listener_ports+=("$listener_port")
        done < <(service_listener_ports_for_tree "$pid" 2>/dev/null || true)

        if [ ${#listener_ports[@]} -gt 0 ]; then
            local selected_port=""
            selected_port=$(service_select_listener_port "$requested_port" "${listener_ports[@]}" 2>/dev/null || true)
            if [[ "$selected_port" =~ ^[0-9]+$ ]]; then
                echo "$selected_port"
                return 0
            fi
        fi

        local now_ts
        now_ts=$(date +%s)
        if [ $((now_ts - start_ts)) -ge "$timeout" ]; then
            break
        fi
        sleep 1
    done

    return 1
}

should_skip_noop_dep_install() {
    local marker=$1
    local expected_fingerprint=${2:-}
    shift
    [ $# -gt 0 ] && shift
    if [ "${RUN_SH_OPT_SKIP_NOOP_DEP_INSTALL:-false}" != true ]; then
        return 1
    fi
    if [ "${FRESH_INSTALL:-false}" = true ]; then
        return 1
    fi
    [ -f "$marker" ] || return 1
    if [ -n "$expected_fingerprint" ]; then
        local marker_fingerprint=""
        marker_fingerprint=$(marker_meta_read "$marker" 2>/dev/null || true)
        [ -n "$marker_fingerprint" ] || return 1
        [ "$marker_fingerprint" = "$expected_fingerprint" ] || return 1
    fi
    local marker_mtime
    marker_mtime=$(file_mtime_epoch "$marker")
    local latest_input
    latest_input=$(max_mtime_epoch "$@")
    [ "$marker_mtime" -ge "$latest_input" ]
}

latest_migration_mtime_epoch() {
    local max=0
    local path=""
    local mtime=0
    local prev_nullglob
    prev_nullglob=$(shopt -p nullglob)
    shopt -s nullglob

    local -a candidates=(
        "alembic.ini"
        "alembic/versions"/*.py
        "migrations/versions"/*.py
    )
    for path in "${candidates[@]}"; do
        [ -f "$path" ] || continue
        mtime=$(file_mtime_epoch "$path")
        if [ "$mtime" -gt "$max" ]; then
            max=$mtime
        fi
    done
    eval "$prev_nullglob"
    echo "$max"
}

should_skip_noop_migrations() {
    local marker=$1
    local expected_db_identity=${2:-}
    if [ "${RUN_SH_OPT_SKIP_NOOP_MIGRATIONS:-false}" != true ]; then
        return 1
    fi
    [ -f "$marker" ] || return 1
    if [ -n "$expected_db_identity" ]; then
        local marker_db_identity=""
        marker_db_identity=$(marker_meta_read "$marker" 2>/dev/null || true)
        [ -n "$marker_db_identity" ] || return 1
        [ "$marker_db_identity" = "$expected_db_identity" ] || return 1
    fi
    local marker_mtime
    marker_mtime=$(file_mtime_epoch "$marker")
    local latest_migration
    latest_migration=$(latest_migration_mtime_epoch)
    [ "$marker_mtime" -ge "$latest_migration" ]
}

service_log_dir_for_attempt() {
    local base=$1
    local type=$2
    local port=$3
    printf '%s_%s_p%s' "$base" "$type" "$port"
}

ensure_actual_ports_assoc() {
    local decl=""
    decl=$(declare -p actual_ports 2>/dev/null || true)
    if [[ "$decl" != "declare -A"* ]]; then
        unset actual_ports 2>/dev/null || true
        declare -gA actual_ports=()
    fi
}

service_record_actual_port() {
    local name=$1
    local type=$2
    local port=$3
    local service_name="$name"
    if [ "$type" = "backend" ]; then
        service_name="$name Backend"
    elif [ "$type" = "frontend" ]; then
        service_name="$name Frontend"
    fi
    ensure_actual_ports_assoc
    actual_ports["$service_name"]=$port
}

service_next_retry_port() {
    local port=$1
    local step=${2:-10}
    printf '%s' $((port + step))
}

service_matches_root() {
    local dir=$1
    local root=$2
    [ -n "$dir" ] && [ "$(dirname "$dir")" = "$root" ]
}

service_collect_for_root() {
    local root=$1
    local -n out=$2
    out=()
    local service name url docs
    for service in "${services[@]}"; do
        if ! parse_service_entry "$service" name url docs; then
            continue
        fi
        local pid="" port="" log="" type="" dir=""
        service_info_fields "$name" pid port log type dir || continue
        if service_matches_root "$dir" "$root"; then
            out+=("$name")
        fi
    done
}

service_remove_by_name() {
    local target=$1
    local new_services=()
    local removed=false
    local service name url docs
    for service in "${services[@]}"; do
        if ! parse_service_entry "$service" name url docs; then
            new_services+=("$service")
            continue
        fi
        if [ "$name" = "$target" ]; then
            removed=true
            continue
        fi
        new_services+=("$service")
    done

    services=("${new_services[@]}")
    if [ "$removed" = true ]; then
        local pid="" port="" log="" type="" dir=""
        service_info_fields "$target" pid port log type dir || true
        if [ -n "$port" ]; then
            unset service_ports["$port"]
        fi
        unset service_info["$target"]
        unset actual_ports["$target"]
        if [ -n "$pid" ] && [ ${#pids[@]} -gt 0 ]; then
            local -a remaining_pids=()
            local existing_pid
            for existing_pid in "${pids[@]}"; do
                [ "$existing_pid" = "$pid" ] && continue
                remaining_pids+=("$existing_pid")
            done
            pids=("${remaining_pids[@]}")
        fi
        return 0
    fi
    return 1
}

# Function to force kill processes on a port

force_kill_port() {
    local port=$1
    local port_pids
    port_pids=$(get_pids_for_port "$port") || true

    if [ -n "$port_pids" ]; then
        local -a kill_pids=()
        local pid=""
        while IFS= read -r pid; do
            [ -n "$pid" ] || continue
            local proc_cmd=""
            proc_cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
            # Never kill Docker daemon/runtime processes during port cleanup.
            if [ -n "$proc_cmd" ] && echo "$proc_cmd" | grep -Eiq '(com\.docker|Docker Desktop|docker-proxy|dockerd|containerd|vpnkit)'; then
                continue
            fi
            kill_pids+=("$pid")
        done <<< "$port_pids"

        if [ ${#kill_pids[@]} -eq 0 ]; then
            return 0
        fi

        echo -e "${YELLOW}Killing processes on port $port: ${kill_pids[*]}${NC}"
        local target_pid
        for target_pid in "${kill_pids[@]}"; do
            kill -TERM "$target_pid" 2>/dev/null || true
        done
        sleep 1
        # Force kill any remaining
        for target_pid in "${kill_pids[@]}"; do
            kill -9 "$target_pid" 2>/dev/null || true
        done
        sleep 0.5  # Give time for port to be released
    fi
}

# Function to wait for port to be in use

is_port_binding_error() {
    local log_file=$1
    local port=$2
    if [ -f "$log_file" ]; then
        # More specific check including the port number
        grep -E "(Address already in use|bind.*:$port|EADDRINUSE.*:$port|address already in use.*:$port)" "$log_file" >/dev/null 2>&1
    else
        return 1
    fi
}

service_emit_start_failure() {
    local service_name=$1
    local log_file=$2
    if [ "${RUN_SH_SUPPRESS_START_FAILURES:-false}" = true ]; then
        return 0
    fi
    echo -e "${RED}✗ ${service_name} failed to start (check ${log_file})${NC}"
    failed_services+=("${service_name}|${log_file}")
}

# Function to check service health

start_service() {
    local name=$1
    local dir=$2
    local type=$3
    local port=$4
    local backend_port=${5:-}
    local log_dir_override=${6:-}
    local db_port=${7:-${DB_PORT:-5432}}
    local redis_port=${8:-${REDIS_PORT:-6379}}
    local db_user="${DB_USER:-postgres}"
    local auth_user="${AUTH_USER:-supabase_auth_admin}"
    local db_password="${DB_PASSWORD:-postgres}"
    local db_name="${DB_NAME:-postgres}"

    echo -e "${BLUE}Starting $name $type on port $port...${NC}"

    if [ ! -d "$dir" ]; then
        echo -e "${YELLOW}Directory not found: $dir${NC}"
        return 1
    fi

    # Work in absolute paths
    dir="$(cd "$dir" && pwd)"

    # Use the provided log directory or create a default one
    local log_dir="${log_dir_override:-${LOGS_DIR:-/tmp}/${name// /_}}"
    local log_file="$log_dir/${type}.log"
    > "$log_file"

    if [ "$type" = "backend" ]; then
        local backend_env_file=""
        local backend_env_is_default=false
        if [ -n "${BACKEND_ENV_FILE_OVERRIDE:-}" ] && [ -f "${BACKEND_ENV_FILE_OVERRIDE:-}" ]; then
            backend_env_file="${BACKEND_ENV_FILE_OVERRIDE}"
        elif [ -f "$dir/.env" ]; then
            backend_env_file="$dir/.env"
            backend_env_is_default=true
        fi
        if [ -n "$backend_env_file" ]; then
            backend_env_file="$(cd "$(dirname "$backend_env_file")" && pwd)/$(basename "$backend_env_file")"
        fi
        local skip_local_db_env="${SKIP_LOCAL_DB_ENV:-false}"
        if [ "$backend_env_is_default" = false ] && [ -n "$backend_env_file" ]; then
            skip_local_db_env=true
        fi

        # Start backend
        local pid=""
        pid=$(cd "$dir" && {
            if ! ensure_python_bin; then
                echo "Python 3.12 is required. Install python3.12 or set PYTHON_BIN." >> "$log_file"
                exit 1
            fi

            # Load environment file (dotenv-safe)
            if [ -n "$backend_env_file" ]; then
                export APP_ENV_FILE="$backend_env_file"
                echo "Using backend env file: $backend_env_file" >> "$log_file"
                load_env_file_safe "$backend_env_file" >> "$log_file" 2>&1 || {
                    echo "Failed to parse $backend_env_file" >> "$log_file"
                }
            else
                unset APP_ENV_FILE
            fi

            # Set up database URL and other environment variables
            if [ "$skip_local_db_env" != true ]; then
                export DATABASE_URL="postgresql+asyncpg://$db_user:$db_password@localhost:$db_port/$db_name"
            fi
            if [ -z "${REDIS_URL:-}" ]; then
                export REDIS_URL="redis://localhost:$redis_port"
            fi
            if [ -n "${BACKEND_LOG_PROFILE_OVERRIDE:-}" ]; then
                export LOG_PROFILE="$BACKEND_LOG_PROFILE_OVERRIDE"
                echo "Applied backend log profile override: $LOG_PROFILE" >> "$log_file"
            fi
            if [ -n "${BACKEND_LOG_LEVEL_OVERRIDE:-}" ]; then
                export LOG_LEVEL="$BACKEND_LOG_LEVEL_OVERRIDE"
                echo "Applied backend log level override: $LOG_LEVEL" >> "$log_file"
            fi

            # Update .env file with database URL if it exists
            if [ "$skip_local_db_env" != true ] && [ "$backend_env_is_default" = true ]; then
                # Update DATABASE_URL and REDIS_URL safely
                upsert_env_value "$backend_env_file" "DATABASE_URL" "$DATABASE_URL"
                upsert_env_value "$backend_env_file" "REDIS_URL" "$REDIS_URL"
            fi

                # Fix common .env format issues
                # Fix EXPORT_ALLOWED_FORMATS to be JSON array
                if grep -q "^EXPORT_ALLOWED_FORMATS=" "$backend_env_file"; then
                    current_value=$(grep "^EXPORT_ALLOWED_FORMATS=" "$backend_env_file" | cut -d= -f2-)
                    # Check if it's not already a proper JSON array
                    if ! echo "$current_value" | "$PYTHON_BIN" -m json.tool >/dev/null 2>&1; then
                        echo "Fixing EXPORT_ALLOWED_FORMATS format..." >> "$log_file"
                        upsert_env_value "$backend_env_file" "EXPORT_ALLOWED_FORMATS" '["json","csv","xml"]'
                        echo "Fixed EXPORT_ALLOWED_FORMATS format" >> "$log_file"
                    fi
                fi

            if [ -f "pyproject.toml" ] && command -v poetry >/dev/null 2>&1; then
                local dep_marker=".run-sh/backend_deps_poetry.stamp"
                local migration_marker=".run-sh/backend_migrations.stamp"
                local dep_fingerprint=""
                dep_fingerprint=$(build_dep_fingerprint "poetry" "pyproject.toml" "poetry.lock")
                local db_identity=""
                db_identity=$(resolve_db_identity "$db_port")
                # Force fresh install if requested
                if [ "$FRESH_INSTALL" = true ]; then
                    echo "Forcing fresh install (removing .venv)..." >> "$log_file"
                    rm -rf .venv
                fi
                if should_skip_noop_dep_install "$dep_marker" "$dep_fingerprint" "pyproject.toml" "poetry.lock"; then
                    echo "Skipping backend dependency install (no lock/config changes detected)." >> "$log_file"
                else
                    echo "Installing backend dependencies..." >> "$log_file"
                    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
                        debug_trace_suppress_begin
                    fi
                    if poetry install >> "$log_file" 2>&1; then
                        mark_noop_marker "$dep_marker"
                        marker_meta_write "$dep_marker" "$dep_fingerprint"
                    else
                        log_backend_dependency_failure "$log_file"
                        if reliability_strict_enabled; then
                            return 1
                        fi
                    fi
                    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
                        debug_trace_suppress_end
                    fi
                fi

                # Run migrations
                if should_skip_noop_migrations "$migration_marker" "$db_identity"; then
                    echo "Skipping database migrations (no migration changes detected)." >> "$log_file"
                else
                    echo "Running database migrations..." >> "$log_file"
                    if poetry run alembic upgrade head >> "$log_file" 2>&1; then
                        mark_noop_marker "$migration_marker"
                        marker_meta_write "$migration_marker" "$db_identity"
                    else
                        log_backend_migration_failure "$log_file"
                        if reliability_strict_enabled; then
                            return 1
                        fi
                    fi
                fi

                echo "Starting backend on port $port..." >> "$log_file"
                spawn_detached "$log_file" poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port "$port"
            elif [ -f "requirements.txt" ]; then
                local dep_marker=".run-sh/backend_deps_pip.stamp"
                local migration_marker=".run-sh/backend_migrations.stamp"
                local dep_fingerprint=""
                dep_fingerprint=$(build_dep_fingerprint "pip" "requirements.txt")
                local db_identity=""
                db_identity=$(resolve_db_identity "$db_port")
                # Force fresh install if requested
                if [ "$FRESH_INSTALL" = true ] && [ -d "venv" ]; then
                    echo "Forcing fresh install (removing venv)..." >> "$log_file"
                    rm -rf venv
                elif [ -d "venv" ]; then
                    if [ -z "${PYTHON_CMD:-}" ] && ! python_is_312 venv/bin/python; then
                        echo "Existing venv uses unsupported Python; recreating..." >> "$log_file"
                        rm -rf venv
                    fi
                fi
                if [ ! -d "venv" ]; then
                    echo "Creating venv with $PYTHON_BIN..." >> "$log_file"
                    "$PYTHON_BIN" -m venv venv >> "$log_file" 2>&1
                fi
                source venv/bin/activate
                if should_skip_noop_dep_install "$dep_marker" "$dep_fingerprint" "requirements.txt"; then
                    echo "Skipping backend dependency install (no requirements changes detected)." >> "$log_file"
                else
                    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
                        debug_trace_suppress_begin
                    fi
                    if pip install -r requirements.txt >> "$log_file" 2>&1; then
                        mark_noop_marker "$dep_marker"
                        marker_meta_write "$dep_marker" "$dep_fingerprint"
                    else
                        log_backend_dependency_failure "$log_file"
                        if reliability_strict_enabled; then
                            return 1
                        fi
                    fi
                    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
                        debug_trace_suppress_end
                    fi
                fi

                # Run migrations
                if should_skip_noop_migrations "$migration_marker" "$db_identity"; then
                    echo "Skipping database migrations (no migration changes detected)." >> "$log_file"
                else
                    echo "Running database migrations..." >> "$log_file"
                    if alembic upgrade head >> "$log_file" 2>&1; then
                        mark_noop_marker "$migration_marker"
                        marker_meta_write "$migration_marker" "$db_identity"
                    else
                        log_backend_migration_failure "$log_file"
                        if reliability_strict_enabled; then
                            return 1
                        fi
                    fi
                fi

                spawn_detached "$log_file" uvicorn app.main:app --reload --host 0.0.0.0 --port "$port"
            else
                echo "No Python package manager found" >> "$log_file"
                exit 1
            fi
        } 2>> "$log_file")
        pid=$(printf '%s\n' "$pid" | tail -n 1)
        if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
            pid=""
        fi
        if [ -z "$pid" ]; then
            service_emit_start_failure "$name Backend" "$log_file"
            return 1
        fi
        pids+=("$pid")

        echo -e "${YELLOW}Waiting for backend to start on port $port...${NC}"
        local resolved_port=""
        resolved_port=$(service_wait_for_bound_port "$pid" "$port" "${RUN_SH_SERVICE_START_TIMEOUT_SEC:-30}" 2>/dev/null || true)
        if [[ "$resolved_port" =~ ^[0-9]+$ ]]; then
            if [ "$resolved_port" -ne "$port" ]; then
                echo -e "${YELLOW}⚠ $name Backend requested port $port but bound to $resolved_port${NC}"
            fi
            echo -e "${GREEN}✓ $name Backend started at http://localhost:$resolved_port/docs${NC}"
            services+=("$name Backend|http://localhost:$resolved_port|http://localhost:$resolved_port/docs")
            service_info["$name Backend"]="$pid|$resolved_port|$log_file|backend|$dir"
            service_ports[$resolved_port]="$name Backend"
            if [ "$(type -t port_state_record)" = "function" ]; then
                port_state_record "$resolved_port" "$name Backend" "listening"
            fi
            service_record_actual_port "$name" "backend" "$resolved_port"
            return 0
        else
            service_emit_start_failure "$name Backend" "$log_file"
            kill "$pid" 2>/dev/null || true
            return 1
        fi

    else
        # Start frontend
        local pid=""
        pid=$(cd "$dir" && {
            local env_file=".env.local"
            local frontend_env_file_override=""
            local frontend_env_loaded=false
            if [ -n "${FRONTEND_ENV_FILE_OVERRIDE:-}" ] && [ -f "${FRONTEND_ENV_FILE_OVERRIDE:-}" ]; then
                frontend_env_file_override="${FRONTEND_ENV_FILE_OVERRIDE}"
                if ensure_python_bin; then
                    load_env_file_safe "$frontend_env_file_override" >> "$log_file" 2>&1 || {
                        echo "Failed to parse $frontend_env_file_override" >> "$log_file"
                    }
                    echo "Loaded frontend env override: $frontend_env_file_override" >> "$log_file"
                    frontend_env_loaded=true
                else
                    echo "Python 3.12 required to load $frontend_env_file_override; skipping frontend override." >> "$log_file"
                fi
            fi

            # Create/update .env.local with backend URL if provided
            if [ -n "$backend_port" ]; then
                local new_url="http://localhost:$backend_port/api/v1"
                local new_line="VITE_API_URL=$new_url"

                echo "Configuring frontend API URL to: $new_url" >> "$log_file"

                # Check if .env.local exists and needs updating
                if [ -f "$env_file" ]; then
                    local current_value=$(grep "^VITE_API_URL=" "$env_file" 2>/dev/null | cut -d= -f2-)
                    if [ "$current_value" != "$new_url" ]; then
                        echo "Updating existing .env.local (was: $current_value)" >> "$log_file"
                        sed_inplace "s|^VITE_API_URL=.*|$new_line|" "$env_file" || echo "$new_line" > "$env_file"
                    else
                        echo ".env.local already has correct API URL" >> "$log_file"
                    fi
                else
                    echo "Creating new .env.local" >> "$log_file"
                    echo "$new_line" > "$env_file"
                fi

                # Warn if .env might override
                if [ -f ".env" ] && grep -q "^VITE_API_URL=" ".env"; then
                    echo "WARNING: .env contains VITE_API_URL which might override .env.local!" >> "$log_file"
                fi
            fi

            if [ -n "$frontend_env_file_override" ]; then
                if [ "$frontend_env_loaded" = true ] && [ -n "${VITE_SUPABASE_URL:-}" ] && [ -n "${VITE_SUPABASE_ANON_KEY:-}" ] && is_valid_http_url "$VITE_SUPABASE_URL"; then
                    upsert_env_value "$env_file" "VITE_SUPABASE_URL" "$VITE_SUPABASE_URL"
                    upsert_env_value "$env_file" "VITE_SUPABASE_ANON_KEY" "$VITE_SUPABASE_ANON_KEY"
                else
                    echo "Supabase frontend override missing/invalid; skipping VITE_SUPABASE_* update." >> "$log_file"
                fi
            fi
            if [ -n "${FRONTEND_LOG_PROFILE_OVERRIDE:-}" ]; then
                export VITE_LOG_PROFILE="$FRONTEND_LOG_PROFILE_OVERRIDE"
                echo "Applied frontend log profile override: $VITE_LOG_PROFILE" >> "$log_file"
            fi
            if [ -n "${FRONTEND_LOG_LEVEL_OVERRIDE:-}" ]; then
                export VITE_LOG_LEVEL="$FRONTEND_LOG_LEVEL_OVERRIDE"
                echo "Applied frontend log level override: $VITE_LOG_LEVEL" >> "$log_file"
            fi

            # Determine package manager and start
            if [ -f "package.json" ]; then
                safe_remove_node_modules() {
                    if [ ! -e "node_modules" ]; then
                        return 0
                    fi
                    if rm -rf node_modules 2>/dev/null; then
                        return 0
                    fi

                    # node_modules may be a mountpoint/volume; clear contents.
                    local prev_nullglob prev_dotglob
                    prev_nullglob=$(shopt -p nullglob)
                    prev_dotglob=$(shopt -p dotglob)
                    shopt -s nullglob dotglob
                    rm -rf node_modules/* 2>/dev/null || true
                    eval "$prev_nullglob"
                    eval "$prev_dotglob"
                    return 0
                }

                # Force fresh install if requested
                if [ "$FRESH_INSTALL" = true ] && [ -d "node_modules" ]; then
                    echo "Forcing fresh install (removing node_modules)..." >> "$log_file"
                    safe_remove_node_modules
                fi

                # Check if node_modules exists and is valid
                if [ ! -d "node_modules" ] || [ ! -f "node_modules/.package-lock.json" ]; then
                    echo "Installing frontend dependencies..." >> "$log_file"
                    NODE_ENV=development npm ci --include=dev --prefer-offline --no-audit >> "$log_file" 2>&1 || \
                        NODE_ENV=development npm install --include=dev >> "$log_file" 2>&1
                fi

                # Verify vite is properly installed before starting
                if [ ! -f "node_modules/.bin/vite" ]; then
                    echo "Vite not found, reinstalling dependencies..." >> "$log_file"
                    safe_remove_node_modules
                    NODE_ENV=development npm ci --include=dev --prefer-offline --no-audit >> "$log_file" 2>&1 || \
                        NODE_ENV=development npm install --include=dev >> "$log_file" 2>&1
                fi

                # Additional check for vite chunks (common corruption issue)
                if [ -d "node_modules/vite" ]; then
                    # Check for the specific chunk file that's commonly missing
                    if ! ls node_modules/vite/dist/node/chunks/dep-*.js >/dev/null 2>&1; then
                        echo "Vite installation appears corrupted, reinstalling..." >> "$log_file"
                        safe_remove_node_modules
                        NODE_ENV=development npm ci --include=dev --prefer-offline --no-audit >> "$log_file" 2>&1 || \
                            NODE_ENV=development npm install --include=dev >> "$log_file" 2>&1
                    fi
                fi

                if ! node -e "require('rollup/dist/native.js')" >> "$log_file" 2>&1; then
                    echo "Rollup native module check failed, reinstalling dependencies..." >> "$log_file"
                    safe_remove_node_modules
                    NODE_ENV=development npm ci --include=dev --prefer-offline --no-audit >> "$log_file" 2>&1 || \
                        NODE_ENV=development npm install --include=dev >> "$log_file" 2>&1
                fi

                if [ -z "${VITE_DEV_PORT:-}" ]; then
                    export VITE_DEV_PORT="$port"
                    echo "Applied VITE_DEV_PORT=$port" >> "$log_file"
                fi
                if [ -z "${VITE_HMR_PORT:-}" ]; then
                    export VITE_HMR_PORT="$port"
                    echo "Applied VITE_HMR_PORT=$port" >> "$log_file"
                fi
                if [ -z "${VITE_HMR_CLIENT_PORT:-}" ]; then
                    export VITE_HMR_CLIENT_PORT="$port"
                    echo "Applied VITE_HMR_CLIENT_PORT=$port" >> "$log_file"
                fi

                echo "Starting frontend on port $port..." >> "$log_file"
                spawn_detached "$log_file" env NODE_ENV=development npm run dev -- --port "$port" --host
            else
                echo "No package.json found" >> "$log_file"
                exit 1
            fi
        } 2>> "$log_file")
        pid=$(printf '%s\n' "$pid" | tail -n 1)
        if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
            pid=""
        fi
        if [ -z "$pid" ]; then
            service_emit_start_failure "$name Frontend" "$log_file"
            return 1
        fi
        pids+=("$pid")

        echo -e "${YELLOW}Waiting for frontend to start on port $port...${NC}"
        local resolved_port=""
        resolved_port=$(service_wait_for_bound_port "$pid" "$port" "${RUN_SH_SERVICE_START_TIMEOUT_SEC:-30}" 2>/dev/null || true)
        if [[ "$resolved_port" =~ ^[0-9]+$ ]]; then
            if [ "$resolved_port" -ne "$port" ]; then
                echo -e "${YELLOW}⚠ $name Frontend requested port $port but bound to $resolved_port${NC}"
            fi
            echo -e "${GREEN}✓ $name Frontend started at http://localhost:$resolved_port${NC}"
            services+=("$name Frontend|http://localhost:$resolved_port")
            service_info["$name Frontend"]="$pid|$resolved_port|$log_file|frontend|$dir"
            service_ports[$resolved_port]="$name Frontend"
            if [ "$(type -t port_state_record)" = "function" ]; then
                port_state_record "$resolved_port" "$name Frontend" "listening"
            fi
            service_record_actual_port "$name" "frontend" "$resolved_port"
            return 0
        else
            # Check if it's a Vite chunk error and try to fix it
            if grep -q "ERR_MODULE_NOT_FOUND.*vite.*chunks/dep-" "$log_file" 2>/dev/null; then
                echo -e "${YELLOW}Detected Vite corruption, attempting fix...${NC}"
                kill "$pid" 2>/dev/null || true

                # Try to fix and restart
                pid=$(cd "$dir" && {
                    safe_remove_node_modules
                    NODE_ENV=development npm ci --include=dev --prefer-offline --no-audit >> "$log_file" 2>&1 || \
                        NODE_ENV=development npm install --include=dev >> "$log_file" 2>&1
                    echo "Retrying frontend start after fix..." >> "$log_file"
                    spawn_detached "$log_file" env NODE_ENV=development npm run dev -- --port "$port" --host
                } 2>> "$log_file")
                pid=$(printf '%s\n' "$pid" | tail -n 1)
                if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
                    pid=""
                fi
                if [ -z "$pid" ]; then
                    service_emit_start_failure "$name Frontend" "$log_file"
                    return 1
                fi
                pids+=("$pid")

                # Wait again for the fixed version
                resolved_port=$(service_wait_for_bound_port "$pid" "$port" "${RUN_SH_SERVICE_START_TIMEOUT_SEC:-30}" 2>/dev/null || true)
                if [[ "$resolved_port" =~ ^[0-9]+$ ]]; then
                    if [ "$resolved_port" -ne "$port" ]; then
                        echo -e "${YELLOW}⚠ $name Frontend requested port $port but bound to $resolved_port${NC}"
                    fi
                    echo -e "${GREEN}✓ $name Frontend started at http://localhost:$resolved_port (after fix)${NC}"
                    services+=("$name Frontend|http://localhost:$resolved_port")
                    service_info["$name Frontend"]="$pid|$resolved_port|$log_file|frontend|$dir"
                    service_ports[$resolved_port]="$name Frontend"
                    service_record_actual_port "$name" "frontend" "$resolved_port"
                    return 0
                fi
            fi

            service_emit_start_failure "$name Frontend" "$log_file"
            kill "$pid" 2>/dev/null || true
            return 1
        fi
    fi
}

# Remove stale/previous failures for a service before a retry attempt.
service_clear_failed_entries() {
    local service_name=$1
    [ -n "$service_name" ] || return 0
    if ! declare -p failed_services >/dev/null 2>&1; then
        return 0
    fi
    local -a kept=()
    local failed=""
    for failed in "${failed_services[@]}"; do
        case "$failed" in
            "$service_name|"*) ;;
            *) kept+=("$failed") ;;
        esac
    done
    failed_services=("${kept[@]}")
}

# Function to start service with retry mechanism

start_service_with_retry() {
    local name=$1
    local dir=$2
    local type=$3
    local initial_port=$4
    local backend_port=${5:-}
    local log_dir_base=${6:-${LOGS_DIR:-/tmp}/${name// /_}}
    local db_port=${7:-}
    local redis_port=${8:-}
    if [ "$(type -t debug_log_line)" = "function" ]; then
        debug_log_line "INFO" "service.start name=${name} type=${type} dir=${dir} port=${initial_port} backend_port=${backend_port} db_port=${db_port} redis_port=${redis_port}"
    fi

    # If force mode is enabled, don't retry - just use the given port
    if [ "$FORCE_PORTS" = true ]; then
        local log_dir
        log_dir=$(service_log_dir_for_attempt "$log_dir_base" "$type" "$initial_port")
        mkdir -p "$log_dir"
        if start_service "$name" "$dir" "$type" "$initial_port" "$backend_port" "$log_dir" "$db_port" "$redis_port"; then
            local service_name="$name"
            if [ "$type" = "backend" ]; then
                service_name="$name Backend"
            elif [ "$type" = "frontend" ]; then
                service_name="$name Frontend"
            fi
            local started_port="${actual_ports[$service_name]:-$initial_port}"
            maybe_release_reserved_port "$initial_port"
            # Success - update tracking with actual port used
            service_record_actual_port "$name" "$type" "$started_port"
            return 0
        else
            maybe_release_reserved_port "$initial_port"
            return 1
        fi
    fi

    local service_name="$name"
    if [ "$type" = "backend" ]; then
        service_name="$name Backend"
    elif [ "$type" = "frontend" ]; then
        service_name="$name Frontend"
    fi

    local max_retries=3
    local retry_count=0
    local port=$initial_port
    local backoff=1

    while [ $retry_count -lt $max_retries ]; do
        service_clear_failed_entries "$service_name"
        # Update log directory with actual port being tried
        local log_dir
        log_dir=$(service_log_dir_for_attempt "$log_dir_base" "$type" "$port")
        mkdir -p "$log_dir"

        # Try to start service
        local previous_suppress_failures="${RUN_SH_SUPPRESS_START_FAILURES:-false}"
        RUN_SH_SUPPRESS_START_FAILURES=true
        local start_rc=0
        if start_service "$name" "$dir" "$type" "$port" "$backend_port" "$log_dir" "$db_port" "$redis_port"; then
            start_rc=0
        else
            start_rc=$?
        fi
        RUN_SH_SUPPRESS_START_FAILURES="$previous_suppress_failures"
        if [ "$start_rc" -eq 0 ]; then
            local started_port="${actual_ports[$service_name]:-$port}"
            maybe_release_reserved_port "$port"
            # Success - update tracking with actual port used
            service_record_actual_port "$name" "$type" "$started_port"
            if [ "$started_port" -ne "$initial_port" ]; then
                echo -e "${BLUE}Note: $name $type using port $started_port instead of $initial_port${NC}"
            fi
            return 0
        fi

        # Check if it's specifically a port binding error
        local log_file="$log_dir/${type}.log"
        if is_port_binding_error "$log_file" "$port"; then
            maybe_release_reserved_port "$port"
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt $max_retries ]; then
                if [ "${RUN_SH_PORT_SNAPSHOT:-false}" = true ] && [ "$(type -t port_snapshot_refresh)" = "function" ]; then
                    port_snapshot_refresh
                fi
                # Find next available port starting from current + 10
                local next_port
                next_port=$(service_next_retry_port "$port")
                port=$(reserve_port "$next_port")

                echo -e "${YELLOW}⚠ Port binding failed, retrying with port $port... (attempt $((retry_count + 1))/$max_retries)${NC}"
                sleep $backoff
                backoff=$((backoff * 2))
            else
                echo -e "${RED}✗ Failed to start $name $type after $max_retries attempts${NC}"
                failed_services+=("$service_name|$log_file")
                maybe_release_reserved_port "$port"
                return 1
            fi
        else
            # Not a port binding error, don't retry
            echo -e "${RED}✗ Failed to start $name $type (non-port error)${NC}"
            failed_services+=("$service_name|$log_file")
            maybe_release_reserved_port "$port"
            return 1
        fi
    done

    return 1
}

# Function to start a project

start_project() {
    local name=$1
    local dir=$2
    local backend_port_base=$3
    local frontend_port_base=$4

    echo -e "\n${CYAN}=== Setting up $name ===${NC}"

    # Find available ports or force use of base ports
    local backend_port=$backend_port_base
    local frontend_port=$frontend_port_base

    if [ "$FORCE_PORTS" = true ]; then
        # Force kill processes on tfile_mtime_epochhe desired ports
        if ! is_port_free "$backend_port"; then
            force_kill_port "$backend_port"
        fi
        if ! is_port_free "$frontend_port"; then
            force_kill_port "$frontend_port"
        fi
    else
        # Find next available ports
        backend_port=$(reserve_port "$backend_port_base")
        frontend_port=$(reserve_port "$frontend_port_base")
    fi
    if [ "$(type -t debug_log_line)" = "function" ]; then
        debug_log_line "INFO" "project.start name=${name} dir=${dir} backend_port=${backend_port} frontend_port=${frontend_port}"
    fi

    # Create project log directory with ports
    local project_log_dir="$LOGS_DIR/${name// /_}_b${backend_port}_f${frontend_port}"
    mkdir -p "$project_log_dir"

    local project_has_services=false
    local all_services_started=true
    local backend_started=false

    # Find backend directory
    local backend_dir=$(find_backend_dir "$dir")
    if [ -n "$backend_dir" ]; then
        project_has_services=true
        if [ "$(type -t debug_log_line)" = "function" ] && [ "${RUN_SH_DEBUG_VERBOSE:-false}" = true ]; then
            debug_log_line "TRACE" "project.backend_dir name=${name} dir=${backend_dir}"
        fi

        # Log if using auto-detected directory
        if [ "$backend_dir" != "$dir/$BACKEND_DIR_NAME" ]; then
            echo -e "${BLUE}Found backend directory: $(basename "$backend_dir")${NC}"
        fi

        if [ "$(type -t profile_start)" = "function" ]; then
            profile_start "backend_start:${name}"
        fi
        if start_service_with_retry "$name" "$backend_dir" "backend" "$backend_port" "" "$project_log_dir"; then
            backend_started=true
            # Update backend_port with actual port used (in case of retry)
            backend_port=${actual_ports["$name Backend"]:-$backend_port}

            # If backend port changed, adjust frontend port to maintain the same offset
            if [ "$backend_port" -ne "$backend_port_base" ]; then
                local port_diff=$((backend_port - backend_port_base))
                frontend_port=$((frontend_port_base + port_diff))
                echo -e "${BLUE}Adjusting frontend port to maintain offset: $frontend_port${NC}"
            fi
        else
            all_services_started=false
            echo -e "${YELLOW}⚠ Skipping frontend due to backend failure${NC}"
        fi
        if [ "$(type -t profile_end)" = "function" ]; then
            profile_end "backend_start:${name}"
        fi
    else
        echo -e "${YELLOW}No backend directory found in $dir${NC}"
        echo -e "${YELLOW}Looked for: $BACKEND_DIR_NAME or patterns: $BACKEND_PATTERNS${NC}"
    fi

    # Find frontend directory
    local frontend_dir=$(find_frontend_dir "$dir")
    if [ -n "$frontend_dir" ]; then
        project_has_services=true
        if [ "$(type -t debug_log_line)" = "function" ] && [ "${RUN_SH_DEBUG_VERBOSE:-false}" = true ]; then
            debug_log_line "TRACE" "project.frontend_dir name=${name} dir=${frontend_dir}"
        fi

        # Log if using auto-detected directory
        if [ "$frontend_dir" != "$dir/$FRONTEND_DIR_NAME" ]; then
            echo -e "${BLUE}Found frontend directory: $(basename "$frontend_dir")${NC}"
        fi

        if [ -z "$backend_dir" ] || [ "$backend_started" = true ]; then
            if [ "$(type -t profile_start)" = "function" ]; then
                profile_start "frontend_start:${name}"
            fi
            if ! start_service_with_retry "$name" "$frontend_dir" "frontend" "$frontend_port" "$backend_port" "$project_log_dir"; then
                all_services_started=false
            fi
            if [ "$(type -t profile_end)" = "function" ]; then
                profile_end "frontend_start:${name}"
            fi
        else
            # Backend exists but failed, skip frontend
            all_services_started=false
            failed_services+=("$name Frontend|Skipped due to backend failure")
        fi
    else
        echo -e "${YELLOW}No frontend directory found in $dir${NC}"
        echo -e "${YELLOW}Looked for: $FRONTEND_DIR_NAME or patterns: $FRONTEND_PATTERNS${NC}"
    fi

    if [ "$project_has_services" = true ]; then
        if [ "$all_services_started" = true ]; then
            if [ "${RUN_SH_PARALLEL_WORKER:-false}" != true ] && [ "$(type -t profile_mark_kpi)" = "function" ]; then
                profile_mark_kpi "ttftr_ms" "project=${name}"
            fi
            echo -e "${GREEN}✓ Completed $name setup${NC}\n"
            return 0
        else
            echo -e "${YELLOW}⚠ Partially completed $name setup (check logs)${NC}\n"
            return 1
        fi
    else
        echo -e "${YELLOW}⚠ No services found for $name${NC}\n"
        return 1
    fi
}

# Function to show service status

restart_service() {
    local search_name=$1

    # Try exact match first
    local service_name=""
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if [ "$name" = "$search_name" ]; then
            service_name="$name"
            break
        fi
    done

    # Fall back to partial matching
    if [ -z "$service_name" ]; then
        service_name=$(find_service_by_name "$search_name")
    fi

    if [ -z "$service_name" ]; then
        echo -e "${RED}No service found matching '$search_name'${NC}"
        echo "Available services:"
        get_service_names | sed 's/^/  - /'
        return 1
    fi

    # Find the service
    local found=false
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if [ "$name" = "$service_name" ] && service_info_fields "$name" pid port log type dir; then
            found=true

            echo -e "${YELLOW}Restarting $name...${NC}"

            if ! resolve_service_pid "$name"; then
                echo -e "${YELLOW}Service PID for $name not found; attempting restart anyway.${NC}"
            fi
            service_info_fields "$name" pid port log type dir || continue

            # Stop the service
            if [ -n "$pid" ]; then
                kill -TERM "$pid" 2>/dev/null || true
                sleep 2
                kill -9 "$pid" 2>/dev/null || true
            fi

            service_remove_by_name "$name" || true

            # Restart based on type
            if [ "$type" = "backend" ]; then
                # Extract project name
                local project_name
                project_name=$(project_name_from_service_name "$name")
                local db_port=""
                local redis_port=""
                if per_tree_requirements_enabled; then
                    local tree_root
                    tree_root=$(dirname "$dir")
                    tree_requirement_ports_for_dir "$tree_root" "$port" db_port redis_port
                    local n8n_port=""
                    local tree_root_real=""
                    tree_root_real=$(cd "$tree_root" && pwd -P 2>/dev/null || true)
                    if [ -n "$tree_root_real" ]; then
                        n8n_port="${N8N_TREE_PORTS[$tree_root_real]:-}"
                    fi
                    if [ -z "$n8n_port" ]; then
                        tree_n8n_port_for_dir "$tree_root" "$port" n8n_port
                    fi
                    if [ -n "$db_port" ] && [ -n "$redis_port" ]; then
                        if ! ensure_tree_requirements "$tree_root" "$db_port" "$redis_port" "$n8n_port"; then
                            echo -e "${RED}Failed to start requirements for ${project_name}${NC}"
                            return 1
                        fi
                        if [ "$(type -t restart_tree_n8n)" = "function" ] && [ "$(type -t tree_uses_n8n)" = "function" ]; then
                            if tree_uses_n8n "$tree_root"; then
                                if ! restart_tree_n8n "$tree_root" "$n8n_port"; then
                                    echo -e "${RED}Failed to restart n8n for ${project_name}${NC}"
                                    return 1
                                fi
                            fi
                        fi
                    fi
                fi
                with_tree_db_overrides "$(dirname "$dir")" start_service_with_retry "$project_name" "$dir" "backend" "$port" "" "" "$db_port" "$redis_port"
            else
                # For frontend, need to find the backend port
                local project_name
                local backend_port=""
                project_name=$(project_name_from_service_name "$name")
                backend_port=$(backend_port_for_project "$project_name")

                start_service_with_retry "$project_name" "$dir" "frontend" "$port" "$backend_port"
            fi

            break
        fi
    done

    if [ "$found" = false ]; then
        echo -e "${RED}Service '$service_name' not found${NC}"
    fi
}

# Function to tail logs for multiple services (names from args)

spawn_detached() {
    local log_file=$1
    shift

    if command -v python3 >/dev/null 2>&1; then
        python3 - "$log_file" "$@" <<'PY'
import os
import signal
import subprocess
import sys

log_file = sys.argv[1]
cmd = sys.argv[2:]

def preexec():
    os.setsid()
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

try:
    with open(log_file, "ab") as f:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.STDOUT,
            preexec_fn=preexec,
        )
except Exception as exc:
    sys.stderr.write(f"spawn_detached failed: {exc}\n")
    sys.exit(1)

print(proc.pid)
PY
        return $?
    fi

    if command -v python >/dev/null 2>&1; then
        python - "$log_file" "$@" <<'PY'
import os
import signal
import subprocess
import sys

log_file = sys.argv[1]
cmd = sys.argv[2:]

def preexec():
    os.setsid()
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

try:
    with open(log_file, "ab") as f:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.STDOUT,
            preexec_fn=preexec,
        )
except Exception as exc:
    sys.stderr.write("spawn_detached failed: %s\n" % exc)
    sys.exit(1)

print(proc.pid)
PY
        return $?
    fi

    (
        trap '' INT HUP
        "$@" < /dev/null >> "$log_file" 2>&1
    ) &
    echo $!
}

# Read a single keypress and normalize escape sequences.

restart_project() {
    local project_name=$1
    local backend_name=""
    local frontend_name=""

    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if [ "$name" = "$project_name Backend" ]; then
            backend_name="$name"
        elif [ "$name" = "$project_name Frontend" ]; then
            frontend_name="$name"
        fi
    done

    if [ -z "$backend_name" ] && [ -z "$frontend_name" ]; then
        echo -e "${RED}No services found for project '$project_name'${NC}"
        echo "Available projects:"
        get_project_names | sed 's/^/  - /'
        return 1
    fi

    if [ -n "$backend_name" ]; then
        echo -e "\n${CYAN}Restarting $backend_name...${NC}"
        restart_service "$backend_name"
    fi
    if [ -n "$frontend_name" ]; then
        echo -e "\n${CYAN}Restarting $frontend_name...${NC}"
        restart_service "$frontend_name"
    fi
}

# Attach to an already-running service from saved state

attach_running_service() {
    local name=$1
    local dir=$2
    local type=$3

    if [ -n "${service_info[$name]:-}" ]; then
        return 1
    fi

    local entry="${ATTACH_SERVICE_INFO[$name]:-}"
    if [ -z "$entry" ]; then
        return 1
    fi

    local pid port log saved_type saved_dir
    parse_service_info "$entry" pid port log saved_type saved_dir || return 1

    if [ -n "$saved_dir" ] && [ "$saved_dir" != "$dir" ]; then
        return 1
    fi
    if [ -n "$saved_type" ] && [ "$saved_type" != "$type" ]; then
        return 1
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        return 1
    fi

    local url="http://localhost:$port"
    if [ "$type" = "backend" ]; then
        services+=("$name|$url|$url/docs")
    else
        services+=("$name|$url")
    fi
    service_info["$name"]="$pid|$port|$log|$type|$dir"
    service_ports[$port]="$name"
    ensure_actual_ports_assoc
    actual_ports["$name"]=$port
    local pid_known=false
    for existing_pid in "${pids[@]}"; do
        if [ "$existing_pid" = "$pid" ]; then
            pid_known=true
            break
        fi
    done
    if [ "$pid_known" = false ]; then
        pids+=("$pid")
    fi

    ATTACHED_PORT="$port"
    return 0
}

lookup_saved_port() {
    local name=$1
    local dir=$2
    local type=$3

    local entry="${ATTACH_SERVICE_INFO[$name]:-}"
    if [ -z "$entry" ]; then
        return 1
    fi

    local pid port log saved_type saved_dir
    parse_service_info "$entry" pid port log saved_type saved_dir || return 1
    if [ -n "$saved_dir" ] && [ "$saved_dir" != "$dir" ]; then
        return 1
    fi
    if [ -n "$saved_type" ] && [ "$saved_type" != "$type" ]; then
        return 1
    fi
    if [ -z "$port" ]; then
        return 1
    fi
    echo "$port"
    return 0
}

start_project_with_attach() {
    local name=$1
    local dir=$2
    local backend_port=$3
    local frontend_port=$4
    local port_offset=${5:-0}

    echo -e "\n${CYAN}=== Setting up $name ===${NC}"
    if [ "$(type -t debug_log_line)" = "function" ]; then
        debug_log_line "INFO" "project.attach.start name=${name} dir=${dir} backend_port=${backend_port} frontend_port=${frontend_port} port_offset=${port_offset}"
    fi

    local backend_port_initial="$backend_port"
    local frontend_port_initial="$frontend_port"
    local backend_port_requested="$backend_port"
    local frontend_port_requested="$frontend_port"

    local project_has_services=false
    local all_services_started=true
    local backend_started=false
    local frontend_started=false
    local backend_attached=false
    local frontend_attached=false
    local requirements_ready=true
    local requirements_assigned=false
    local db_port=""
    local redis_port=""
    local backend_dir=""
    local frontend_dir=""
    local saved_backend_port=""
    local saved_frontend_port=""

    backend_dir=$(find_backend_dir "$dir" 2>/dev/null) || backend_dir=""
    frontend_dir=$(find_frontend_dir "$dir" 2>/dev/null) || frontend_dir=""

    if [ -n "$backend_dir" ] || [ -n "$frontend_dir" ]; then
        project_has_services=true
    fi

    if [ "$ATTACH_STATE_ENABLED" = true ]; then
        ATTACHED_PORT=""
        if [ -n "$backend_dir" ]; then
            if attach_running_service "$name Backend" "$backend_dir" "backend"; then
                backend_attached=true
                backend_started=true
                backend_port="$ATTACHED_PORT"
                echo -e "${GREEN}✓ $name Backend already running on port $backend_port${NC}"
            fi
        fi
        ATTACHED_PORT=""
        if [ -n "$frontend_dir" ]; then
            if attach_running_service "$name Frontend" "$frontend_dir" "frontend"; then
                frontend_attached=true
                frontend_started=true
                frontend_port="$ATTACHED_PORT"
                echo -e "${GREEN}✓ $name Frontend already running on port $frontend_port${NC}"
            fi
        fi

        if [ "$backend_attached" = false ] && [ -n "$backend_dir" ]; then
            saved_backend_port=$(lookup_saved_port "$name Backend" "$backend_dir" "backend" 2>/dev/null || true)
        fi
        if [ "$frontend_attached" = false ] && [ -n "$frontend_dir" ]; then
            saved_frontend_port=$(lookup_saved_port "$name Frontend" "$frontend_dir" "frontend" 2>/dev/null || true)
        fi
    fi

    if [ "$backend_attached" = false ]; then
        if [ -n "$saved_backend_port" ]; then
            backend_port="$saved_backend_port"
            echo -e "${BLUE}Using saved backend port $backend_port${NC}"
        fi
        if [ -n "${RUN_RESERVED_PORTS[$backend_port]:-}" ] || ! is_port_free "$backend_port"; then
            backend_port=$(reserve_port "$backend_port")
        fi
    fi

    if [ "$frontend_attached" = false ] && [ -z "$saved_frontend_port" ] && [ "$backend_port" -ne "$backend_port_initial" ]; then
        local port_diff=$((backend_port - backend_port_initial))
        frontend_port=$((frontend_port + port_diff))
    fi

    if [ "$frontend_attached" = false ]; then
        if [ -n "$saved_frontend_port" ]; then
            frontend_port="$saved_frontend_port"
            echo -e "${BLUE}Using saved frontend port $frontend_port${NC}"
        fi
        if [ -n "${RUN_RESERVED_PORTS[$frontend_port]:-}" ] || ! is_port_free "$frontend_port"; then
            frontend_port=$(reserve_port "$frontend_port")
        fi
    fi

    backend_port_requested="$backend_port"
    frontend_port_requested="$frontend_port"

    if [ "$backend_port" -ne "$backend_port_initial" ] || [ "$frontend_port" -ne "$frontend_port_initial" ]; then
        echo -e "${YELLOW}⚠ Port override for $name: backend $backend_port (was $backend_port_initial), frontend $frontend_port (was $frontend_port_initial)${NC}"
    fi

    local project_log_dir="$LOGS_DIR/${name// /_}_b${backend_port}_f${frontend_port}"
    mkdir -p "$project_log_dir"

    if [ -n "$backend_dir" ] && per_tree_requirements_enabled; then
        resolve_tree_requirement_ports "$dir" "$backend_port_initial" "$backend_port" "$frontend_port" "$port_offset" db_port redis_port
        local n8n_port=""
        local tree_dir_real=""
        tree_dir_real=$(cd "$dir" && pwd -P 2>/dev/null || true)
        if [ -n "$tree_dir_real" ]; then
            n8n_port="${N8N_TREE_PORTS[$tree_dir_real]:-}"
        fi
        if [ -z "$n8n_port" ]; then
            tree_n8n_port_for_dir "$dir" "$backend_port" n8n_port
        fi
        requirements_assigned=true
        if ! ensure_tree_requirements "$dir" "$db_port" "$redis_port" "$n8n_port"; then
            if [ "$backend_attached" = false ]; then
                requirements_ready=false
                all_services_started=false
                echo -e "${YELLOW}⚠ Requirements unavailable; skipping backend start for $name${NC}"
            else
                echo -e "${YELLOW}⚠ Requirements unavailable for attached backend ${name}${NC}"
            fi
        fi
    fi

    if [ "$backend_attached" = false ]; then
        if [ -n "$backend_dir" ]; then
            if [ "$backend_dir" != "$dir/$BACKEND_DIR_NAME" ]; then
                echo -e "${BLUE}Found backend directory: $(basename "$backend_dir")${NC}"
            fi
            if [ "$(type -t profile_start)" = "function" ]; then
                profile_start "backend_start:${name}"
            fi
            if [ "$requirements_ready" = true ] && with_tree_db_overrides "$dir" start_service_with_retry "$name" "$backend_dir" "backend" "$backend_port" "" "$project_log_dir" "$db_port" "$redis_port"; then
                backend_started=true
                backend_port=${actual_ports["$name Backend"]:-$backend_port}
                if [ "$frontend_attached" = false ] && [ -z "$saved_frontend_port" ] && [ "$backend_port" -ne "$backend_port_requested" ]; then
                    local port_diff=$((backend_port - backend_port_requested))
                    frontend_port=$((frontend_port + port_diff))
                    frontend_port=$(reserve_port "$frontend_port")
                    frontend_port_requested="$frontend_port"
                    echo -e "${BLUE}Adjusting frontend port to maintain offset: $frontend_port${NC}"
                fi
                if [ "$frontend_attached" = false ] && [ -n "$saved_frontend_port" ]; then
                    if [ -n "${RUN_RESERVED_PORTS[$frontend_port]:-}" ] || ! is_port_free "$frontend_port"; then
                        frontend_port=$(reserve_port "$frontend_port")
                        frontend_port_requested="$frontend_port"
                        echo -e "${YELLOW}⚠ Saved frontend port in use; using $frontend_port${NC}"
                    fi
                fi
            else
                all_services_started=false
            fi
            if [ "$(type -t profile_end)" = "function" ]; then
                profile_end "backend_start:${name}"
            fi
        else
            echo -e "${YELLOW}No backend directory found in $dir${NC}"
            echo -e "${YELLOW}Looked for: $BACKEND_DIR_NAME or patterns: $BACKEND_PATTERNS${NC}"
        fi
    fi

    if [ "$frontend_attached" = false ]; then
        if [ -n "$frontend_dir" ]; then
            if [ "$frontend_dir" != "$dir/$FRONTEND_DIR_NAME" ]; then
                echo -e "${BLUE}Found frontend directory: $(basename "$frontend_dir")${NC}"
            fi
            if [ "$backend_attached" = true ] || [ "$backend_dir" = "" ] || [ "$backend_started" = true ]; then
                if [ "$(type -t profile_start)" = "function" ]; then
                    profile_start "frontend_start:${name}"
                fi
                if ! start_service_with_retry "$name" "$frontend_dir" "frontend" "$frontend_port" "$backend_port" "$project_log_dir"; then
                    all_services_started=false
                else
                    frontend_started=true
                    frontend_port=${actual_ports["$name Frontend"]:-$frontend_port}
                fi
                if [ "$(type -t profile_end)" = "function" ]; then
                    profile_end "frontend_start:${name}"
                fi
            else
                all_services_started=false
                failed_services+=("$name Frontend|Skipped due to backend failure")
            fi
        else
            echo -e "${YELLOW}No frontend directory found in $dir${NC}"
            echo -e "${YELLOW}Looked for: $FRONTEND_DIR_NAME or patterns: $FRONTEND_PATTERNS${NC}"
        fi
    fi

    if [ "$backend_started" = true ] || [ "$frontend_started" = true ] || [ "$requirements_assigned" = true ]; then
        if ! update_worktree_port_config "$dir" "$backend_port" "$frontend_port" "$db_port" "$redis_port"; then
            all_services_started=false
            failed_services+=("$name Runtime|Failed to persist worktree ports for $dir")
            echo -e "${RED}✗ Failed to persist port config for $name${NC}"
        fi
    fi

    if [ "$project_has_services" = true ]; then
        if [ "$all_services_started" = true ]; then
            if [ "${RUN_SH_PARALLEL_WORKER:-false}" != true ] && [ "$(type -t profile_mark_kpi)" = "function" ]; then
                profile_mark_kpi "ttftr_ms" "project=${name}"
            fi
            echo -e "${GREEN}✓ Completed $name setup${NC}\n"
            return 0
        else
            echo -e "${YELLOW}⚠ Partially completed $name setup (check logs)${NC}\n"
            return 1
        fi
    else
        echo -e "${YELLOW}⚠ No services found for $name${NC}\n"
        return 1
    fi
}

# Docker helpers for interactive mode

stop_services_for_root() {
    local root=$1
    local stopped=false
    local -a root_services=()
    local name
    service_collect_for_root "$root" root_services
    for name in "${root_services[@]}"; do
        local pid="" port="" log="" type="" dir=""
        service_info_fields "$name" pid port log type dir || continue
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            stopped=true
        fi
    done
    if [ "$stopped" = true ]; then
        echo -e "${YELLOW}Stopped running services for ${root#$BASE_DIR/}.${NC}"
    fi
}

drop_services_for_root() {
    local root=$1
    local -a root_services=()
    local name
    service_collect_for_root "$root" root_services
    for name in "${root_services[@]}"; do
        service_remove_by_name "$name" || true
    done
}

delete_worktree_dir() {
    local root=$1
    root=$(cd "$root" && pwd -P 2>/dev/null) || {
        echo -e "${YELLOW}Worktree path not found: $root${NC}"
        return 1
    }
    if [ "$root" = "$BASE_DIR" ]; then
        echo -e "${YELLOW}Skipping main project root: $root${NC}"
        return 1
    fi

    local branch=""
    if ! branch=$(worktree_branch_for_path "$root" 2>/dev/null); then
        branch=""
        echo -e "${YELLOW}Not a git worktree: $root${NC}"
        stop_services_for_root "$root"
        stop_tree_requirements_for_root "$root" false
        drop_services_for_root "$root"
        remove_worktree_port_config "$root"
        if [ -d "$root" ]; then
            rm -rf "$root" >/dev/null 2>&1 || true
        fi
        git -C "$BASE_DIR" worktree prune --expire now >/dev/null 2>&1 || true
        if [ -d "$root" ]; then
            echo -e "${YELLOW}Failed to remove directory: ${root#$BASE_DIR/}${NC}"
            return 1
        fi
        echo -e "${GREEN}✓ Deleted worktree: ${root#$BASE_DIR/}${NC}"
        return 0
    fi

    stop_services_for_root "$root"
    stop_tree_requirements_for_root "$root" false
    drop_services_for_root "$root"
    remove_worktree_port_config "$root"

    local remove_err=""
    if remove_err=$(git -C "$BASE_DIR" worktree remove --force "$root" 2>&1); then
        git -C "$BASE_DIR" worktree prune --expire now >/dev/null 2>&1 || true
    else
        if echo "$remove_err" | grep -qi "locked"; then
            git -C "$BASE_DIR" worktree unlock "$root" >/dev/null 2>&1 || true
        fi
        if remove_err=$(git -C "$BASE_DIR" worktree remove -f -f "$root" 2>&1); then
            git -C "$BASE_DIR" worktree prune --expire now >/dev/null 2>&1 || true
        else
            local alt_path=""
            if [ -n "$branch" ]; then
                alt_path=$(worktree_path_for_branch "$branch" 2>/dev/null || true)
            fi
            if [ -n "$alt_path" ] && [ "$alt_path" != "$root" ]; then
                if git -C "$BASE_DIR" worktree remove --force "$alt_path" >/dev/null 2>&1; then
                    git -C "$BASE_DIR" worktree prune --expire now >/dev/null 2>&1 || true
                    remove_err=""
                fi
            fi
            if [ -n "$remove_err" ]; then
                rm -rf "$root" >/dev/null 2>&1 || true
                git -C "$BASE_DIR" worktree prune --expire now >/dev/null 2>&1 || true
                if [ -n "$branch" ] && worktree_path_for_branch "$branch" >/dev/null 2>&1; then
                    echo -e "${YELLOW}Failed to remove worktree via git: ${root#$BASE_DIR/}${NC}"
                    echo -e "${YELLOW}Git error: ${remove_err}${NC}"
                    return 1
                fi
                echo -e "${YELLOW}Git remove failed; cleaned ${root#$BASE_DIR/} manually.${NC}"
            fi
        fi
    fi

    if [ -n "$branch" ]; then
        if git -C "$BASE_DIR" show-ref --verify --quiet "refs/heads/$branch"; then
            git -C "$BASE_DIR" branch -D "$branch" >/dev/null 2>&1 || true
        fi
    fi

    echo -e "${GREEN}✓ Deleted worktree: ${root#$BASE_DIR/}${NC}"
    return 0
}

delete_worktrees_for_paths() {
    local label=$1
    shift
    local paths=("$@")
    if [ ${#paths[@]} -eq 0 ]; then
        echo -e "${YELLOW}No worktree paths selected to delete.${NC}"
        return 1
    fi

    echo -e "${YELLOW}Worktrees selected for deletion (${label}):${NC}"
    local path
    for path in "${paths[@]}"; do
        echo "  - ${path#$BASE_DIR/}"
    done
    if ! prompt_yes_no "Delete these worktrees locally? (y/N): "; then
        echo -e "${YELLOW}Deletion cancelled.${NC}"
        return 1
    fi

    local all_ok=true
    for path in "${paths[@]}"; do
        if ! delete_worktree_dir "$path"; then
            all_ok=false
        fi
    done
    if [ "$all_ok" = true ]; then
        return 0
    fi
    return 1
}
