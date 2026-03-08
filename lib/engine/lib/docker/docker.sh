#!/usr/bin/env bash

# Docker helpers.

DOCKER_PS_CACHE_READY=${DOCKER_PS_CACHE_READY:-false}
DOCKER_PS_NAMES_CACHE=${DOCKER_PS_NAMES_CACHE:-}
DOCKER_PS_ALL_NAMES_CACHE=${DOCKER_PS_ALL_NAMES_CACHE:-}
DOCKER_PS_IDS_CACHE=${DOCKER_PS_IDS_CACHE:-}
DOCKER_LAST_TIMEOUT=${DOCKER_LAST_TIMEOUT:-false}
DOCKER_LAST_RC=${DOCKER_LAST_RC:-0}
DOCKER_LAST_CMD=${DOCKER_LAST_CMD:-}
DOCKER_TIMEOUT_HINT_SHOWN=${DOCKER_TIMEOUT_HINT_SHOWN:-false}

docker_timeout_bin() {
    if [ -n "${TIMEOUT_BIN:-}" ] && command -v "$TIMEOUT_BIN" >/dev/null 2>&1; then
        echo "$TIMEOUT_BIN"
        return 0
    fi
    if command -v timeout >/dev/null 2>&1; then
        echo "timeout"
        return 0
    fi
    if command -v gtimeout >/dev/null 2>&1; then
        echo "gtimeout"
        return 0
    fi
    echo ""
}

docker_socket_path() {
    if [ -n "${DOCKER_HOST:-}" ] && [[ "$DOCKER_HOST" == unix://* ]]; then
        echo "${DOCKER_HOST#unix://}"
        return 0
    fi
    if [ -S "$HOME/.docker/run/docker.sock" ]; then
        echo "$HOME/.docker/run/docker.sock"
        return 0
    fi
    if [ -S "/var/run/docker.sock" ]; then
        echo "/var/run/docker.sock"
        return 0
    fi
    echo ""
}

docker_socket_state() {
    if ! command -v curl >/dev/null 2>&1; then
        echo "unknown"
        return 0
    fi

    local sock=""
    sock=$(docker_socket_path)
    if [ -z "$sock" ] || [ ! -S "$sock" ]; then
        echo "missing"
        return 0
    fi

    local timeout_bin=""
    timeout_bin=$(docker_timeout_bin)
    if [ -n "$timeout_bin" ]; then
        if "$timeout_bin" 3 curl -sS -I --connect-timeout 1 --max-time 2 \
            --unix-socket "$sock" http://localhost/_ping >/dev/null 2>&1; then
            echo "reachable"
            return 0
        fi
        echo "unresponsive"
        return 0
    fi

    if curl -sS -I --connect-timeout 1 --max-time 2 \
        --unix-socket "$sock" http://localhost/_ping >/dev/null 2>&1; then
        echo "reachable"
        return 0
    fi
    echo "unresponsive"
}

docker_print_timeout_hint_once() {
    if [ "$DOCKER_TIMEOUT_HINT_SHOWN" = true ]; then
        return 0
    fi
    DOCKER_TIMEOUT_HINT_SHOWN=true
    echo -e "${YELLOW}Hint: restart Docker and verify with: timeout 5 docker version && timeout 5 docker ps${NC}" >&2
}

docker_run_with_timeout() {
    local timeout_sec=$1
    shift || true

    DOCKER_LAST_TIMEOUT=false
    DOCKER_LAST_RC=0
    local printable=""
    printable=$(printf '%q ' "$@")
    printable=${printable% }
    DOCKER_LAST_CMD="docker ${printable}"

    local timeout_bin=""
    timeout_bin=$(docker_timeout_bin)
    if [[ "${timeout_sec}" =~ ^[0-9]+$ ]] && [ "${timeout_sec}" -gt 0 ] && [ -n "$timeout_bin" ]; then
        "$timeout_bin" "${timeout_sec}" docker "$@"
    else
        docker "$@"
    fi
    local rc=$?
    DOCKER_LAST_RC=$rc
    if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
        DOCKER_LAST_TIMEOUT=true
        local socket_state=""
        socket_state=$(docker_socket_state)
        echo -e "${RED}Docker command timed out: docker ${printable} (socket:${socket_state})${NC}" >&2
        docker_print_timeout_hint_once
    fi
    return $rc
}

docker_cmd() {
    local timeout_sec="${RUN_SH_DOCKER_CMD_TIMEOUT_SEC:-8}"
    docker_run_with_timeout "$timeout_sec" "$@"
}

docker_probe() {
    local timeout_sec="${RUN_SH_DOCKER_PROBE_TIMEOUT_SEC:-3}"
    docker_run_with_timeout "$timeout_sec" "$@"
}

docker_ps_cache_ready() {
    if [ "${RUN_SH_REFRESH_CACHE:-false}" = true ]; then
        return 1
    fi
    [ "$DOCKER_PS_CACHE_READY" = true ]
}

docker_ps_cache_refresh() {
    DOCKER_PS_NAMES_CACHE=$(docker_cmd ps --format '{{.Names}}' 2>/dev/null || true)
    DOCKER_PS_ALL_NAMES_CACHE=$(docker_cmd ps -a --format '{{.Names}}' 2>/dev/null || true)
    DOCKER_PS_IDS_CACHE=$(docker_cmd ps --format '{{.ID}}' 2>/dev/null || true)
    DOCKER_PS_CACHE_READY=true
    if [ -n "${DOCKER_PORT_MAP_READY+x}" ]; then
        DOCKER_PORT_MAP_READY=false
    fi
}

docker_ps_names_cached() {
    if ! docker_ps_cache_ready; then
        docker_ps_cache_refresh
    fi
    printf '%s\n' "$DOCKER_PS_NAMES_CACHE"
}

docker_ps_all_names_cached() {
    if ! docker_ps_cache_ready; then
        docker_ps_cache_refresh
    fi
    printf '%s\n' "$DOCKER_PS_ALL_NAMES_CACHE"
}

docker_ps_ids_cached() {
    if ! docker_ps_cache_ready; then
        docker_ps_cache_refresh
    fi
    printf '%s\n' "$DOCKER_PS_IDS_CACHE"
}

docker_ps_names_contains() {
    local needle=$1
    [ -n "$needle" ] || return 1
    local names
    names=$(docker_ps_names_cached)
    [ -n "$names" ] || return 1
    local line
    while IFS= read -r line; do
        [ "$line" = "$needle" ] && return 0
    done <<< "$names"
    return 1
}

docker_ps_all_names_contains() {
    local needle=$1
    [ -n "$needle" ] || return 1
    local names
    names=$(docker_ps_all_names_cached)
    [ -n "$names" ] || return 1
    local line
    while IFS= read -r line; do
        [ "$line" = "$needle" ] && return 0
    done <<< "$names"
    return 1
}

docker_container_exists() {
    local name=$1
    [ -n "$name" ] || return 1
    docker_cmd inspect -f '{{.State.Status}}' "$name" >/dev/null 2>&1
}

docker_container_running() {
    local name=$1
    [ -n "$name" ] || return 1
    local status=""
    status=$(docker_cmd inspect -f '{{.State.Status}}' "$name" 2>/dev/null || true)
    [ "$status" = "running" ]
}

ensure_docker_credential_helper() {
    local helper="docker-credential-desktop"
    local config="${DOCKER_CONFIG:-$HOME/.docker}/config.json"

    if command -v "$helper" >/dev/null 2>&1; then
        return 0
    fi

    if [[ "$OSTYPE" == "darwin"* ]]; then
        local helper_path="/Applications/Docker.app/Contents/Resources/bin/$helper"
        if [ -x "$helper_path" ]; then
            export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
            return 0
        fi
    fi

    if [ -f "$config" ] && grep -qE '"(credsStore|credHelpers)"[[:space:]]*:[[:space:]]*' "$config"; then
        if grep -q '"credsStore"[[:space:]]*:[[:space:]]*"desktop"' "$config" || \
           grep -q '"credHelpers"[[:space:]]*:[[:space:]]*{[^}]*"desktop"' "$config"; then
            echo -e "${RED}Docker credential helper 'docker-credential-desktop' not found in PATH.${NC}"
            echo "Fix options:"
            echo "  - Start Docker Desktop (it provides the helper), or"
            echo "  - Add /Applications/Docker.app/Contents/Resources/bin to PATH, or"
            echo "  - Remove the desktop credential helper from $config"
            return 1
        fi
    fi

    return 0
}

# Function to check if Docker is running

check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Docker is not installed.${NC}"
        echo "Install hints:"
        echo "  - macOS: https://www.docker.com/products/docker-desktop/"
        echo "  - Ubuntu: sudo apt-get install docker.io"
        exit 1
    fi

    local auto_restart_on_hang="${RUN_SH_DOCKER_AUTO_RESTART_ON_HANG:-false}"
    local auto_restart_max="${RUN_SH_DOCKER_AUTO_RESTART_MAX:-1}"
    if ! [[ "$auto_restart_max" =~ ^[0-9]+$ ]]; then
        auto_restart_max=1
    fi
    local startup_wait_sec="${RUN_SH_DOCKER_STARTUP_WAIT_SEC:-60}"
    if ! [[ "$startup_wait_sec" =~ ^[0-9]+$ ]]; then
        startup_wait_sec=60
    fi
    local restart_grace_sec="${RUN_SH_DOCKER_RESTART_GRACE_SEC:-30}"
    if ! [[ "$restart_grace_sec" =~ ^[0-9]+$ ]]; then
        restart_grace_sec=30
    fi
    if [ "$restart_grace_sec" -gt "$startup_wait_sec" ]; then
        restart_grace_sec="$startup_wait_sec"
    fi
    local restart_consecutive_timeouts="${RUN_SH_DOCKER_RESTART_CONSECUTIVE_TIMEOUTS:-3}"
    if ! [[ "$restart_consecutive_timeouts" =~ ^[0-9]+$ ]]; then
        restart_consecutive_timeouts=3
    fi
    if [ "$restart_consecutive_timeouts" -lt 1 ]; then
        restart_consecutive_timeouts=1
    fi

    if docker_probe info &> /dev/null; then
        if ! ensure_docker_credential_helper; then
            exit 1
        fi
        return 0
    fi

    if [ "$DOCKER_LAST_TIMEOUT" = true ]; then
        local socket_state=""
        socket_state=$(docker_socket_state)
        echo -e "${YELLOW}Docker daemon unresponsive (socket:${socket_state}). Attempting recovery...${NC}"
    else
        echo -e "${YELLOW}Docker is not running. Attempting to start Docker...${NC}"
    fi

    if [[ "$OSTYPE" == "darwin"* ]]; then
        local restart_attempts=0
        local consecutive_timeout_probes=0
        echo -e "${BLUE}Starting Docker Desktop...${NC}"
        open -a Docker >/dev/null 2>&1 || true

        local start_ts=0
        start_ts=$(date +%s 2>/dev/null || echo 0)
        local deadline=$((start_ts + startup_wait_sec))
        local count=0
        while true; do
            local now_ts=0
            now_ts=$(date +%s 2>/dev/null || echo 0)
            if [ "$start_ts" -gt 0 ] && [ "$now_ts" -gt 0 ] && [ "$now_ts" -ge "$deadline" ]; then
                break
            fi
            if docker_probe info &> /dev/null; then
                DOCKER_WAS_STARTED=true
                echo -e "\n${GREEN}✓ Docker started successfully${NC}"
                if ! ensure_docker_credential_helper; then
                    exit 1
                fi
                return 0
            fi
            if [ "$DOCKER_LAST_TIMEOUT" = true ]; then
                consecutive_timeout_probes=$((consecutive_timeout_probes + 1))

                # Fallback to a longer timeout before treating this as a hard hang.
                if docker_cmd info &> /dev/null; then
                    DOCKER_WAS_STARTED=true
                    echo -e "\n${GREEN}✓ Docker started successfully${NC}"
                    if ! ensure_docker_credential_helper; then
                        exit 1
                    fi
                    return 0
                fi
            else
                consecutive_timeout_probes=0
            fi

            local elapsed=0
            if [ "$start_ts" -gt 0 ] && [ "$now_ts" -gt 0 ]; then
                elapsed=$((now_ts - start_ts))
            fi
            if [ "$auto_restart_on_hang" = true ] \
                && [ "$restart_attempts" -lt "$auto_restart_max" ] \
                && [ "$elapsed" -ge "$restart_grace_sec" ] \
                && [ "$consecutive_timeout_probes" -ge "$restart_consecutive_timeouts" ]; then
                local socket_state=""
                socket_state=$(docker_socket_state)
                if [ "$socket_state" = "unresponsive" ]; then
                    restart_attempts=$((restart_attempts + 1))
                    echo -e "\n${YELLOW}Docker still unresponsive; restarting Docker Desktop (${restart_attempts}/${auto_restart_max})...${NC}"
                    osascript -e 'quit app "Docker"' >/dev/null 2>&1 || true
                    sleep 2
                    open -a Docker >/dev/null 2>&1 || true
                    consecutive_timeout_probes=0
                fi
            fi
            sleep 1
            ((count++))
            echo -ne "\r${YELLOW}Waiting for Docker to start... ($count/${startup_wait_sec} seconds)${NC}"
        done
        echo
        echo -e "${RED}Failed to start Docker after ${startup_wait_sec} seconds. Please restart Docker manually.${NC}"
        docker_print_timeout_hint_once
        exit 1
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v systemctl &> /dev/null && systemctl list-unit-files | grep -q '^docker.service'; then
            echo -e "${BLUE}Starting Docker service...${NC}"
            if sudo systemctl start docker >/dev/null 2>&1 && docker_probe info &> /dev/null; then
                DOCKER_WAS_STARTED=true
                echo -e "${GREEN}✓ Docker started successfully${NC}"
                return 0
            fi
            echo -e "${RED}Failed to start Docker service. Please start Docker manually.${NC}"
            docker_print_timeout_hint_once
            exit 1
        fi
        echo -e "${RED}Cannot start Docker automatically. Please start Docker manually.${NC}"
        docker_print_timeout_hint_once
        exit 1
    else
        echo -e "${RED}Unsupported OS. Please start Docker manually.${NC}"
        docker_print_timeout_hint_once
        exit 1
    fi
}

# Docker compose helper

docker_compose() {
    local compose_args=(-p "$DOCKER_PROJECT_NAME" -f "$DOCKER_COMPOSE_FILE")
    if [ ${#DOCKER_COMPOSE_EXTRA_FILES[@]} -gt 0 ]; then
        local file
        for file in "${DOCKER_COMPOSE_EXTRA_FILES[@]}"; do
            if [ -n "$file" ]; then
                compose_args+=(-f "$file")
            fi
        done
    fi
    if [ -n "$DOCKER_COMPOSE_OVERRIDE" ]; then
        compose_args+=(-f "$DOCKER_COMPOSE_OVERRIDE")
    fi
    (cd "$BASE_DIR" && docker compose "${compose_args[@]}" "$@")
}

compose_has_service() {
    local service=$1
    [ -n "$service" ] || return 1
    [ -f "$DOCKER_COMPOSE_FILE" ] || return 1

    if command -v rg >/dev/null 2>&1; then
        rg -q "^[[:space:]]*${service}:" "$DOCKER_COMPOSE_FILE"
        return $?
    fi

    grep -qE "^[[:space:]]*${service}:" "$DOCKER_COMPOSE_FILE"
}


docker_compose_up() {
    local detached=${1:-false}
    local args=(up --build)

    if [ "$detached" = true ]; then
        args+=(-d)
    fi
    if [ "$DOCKER_UP_NO_DEPS" = true ]; then
        args+=(--no-deps)
    fi
    if [ ${#DOCKER_UP_SERVICES[@]} -gt 0 ]; then
        args+=("${DOCKER_UP_SERVICES[@]}")
    fi

    docker_compose "${args[@]}"
}


maybe_stop_docker() {
    local allow_daemon_stop="${RUN_SH_ALLOW_DOCKER_DAEMON_STOP:-false}"
    if [ "$allow_daemon_stop" != true ]; then
        if [ "${DOCKER_TEMP_MODE:-false}" = true ] && [ "${DOCKER_WAS_STARTED:-false}" = true ]; then
            echo -e "${YELLOW}Skipping Docker daemon stop (RUN_SH_ALLOW_DOCKER_DAEMON_STOP=false).${NC}"
        fi
        return 0
    fi

    if [ "$DOCKER_TEMP_MODE" != true ] || [ "$DOCKER_WAS_STARTED" != true ]; then
        return 0
    fi

    echo -e "${YELLOW}Stopping Docker (temporary mode)...${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        osascript -e 'quit app "Docker"' 2>/dev/null || echo -e "${YELLOW}Could not stop Docker Desktop${NC}"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo systemctl stop docker 2>/dev/null || echo -e "${YELLOW}Could not stop Docker service${NC}"
    fi
    echo -e "${GREEN}✓ Docker stopped${NC}"
}


resolve_docker_ports() {
    local db_port="${DB_PORT:-5432}"
    local redis_port="${REDIS_PORT:-6379}"
    local backend_port_base="${BACKEND_PORT:-8000}"
    local frontend_port_base="${FRONTEND_PORT:-8080}"
    local n8n_enabled=false
    local n8n_port="${N8N_PORT:-5678}"
    local supabase_compose=""
    local supabase_env_file=""
    local supabase_public_port="${SUPABASE_PUBLIC_PORT:-54321}"
    local supabase_db_port="${SUPABASE_DB_PORT:-54322}"
    local skip_db=false
    local skip_redis=false

    DOCKER_COMPOSE_EXTRA_FILES=()
    if compose_has_service "n8n"; then
        n8n_enabled=true
    fi

    if tree_uses_supabase "$BASE_DIR"; then
        supabase_compose="${BASE_DIR%/}/supabase/docker-compose.yml"
        if [ -f "$supabase_compose" ]; then
            DOCKER_COMPOSE_EXTRA_FILES+=("$supabase_compose")
            supabase_env_file=$(supabase_env_file_for_tree "$BASE_DIR" 2>/dev/null || true)
            if [ -n "$supabase_env_file" ]; then
                local value=""
                for key in SUPABASE_PUBLIC_URL SUPABASE_PUBLIC_PORT SUPABASE_DB_PORT SUPABASE_DB_PASSWORD \
                           SUPABASE_JWT_SECRET SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY; do
                    if [ -z "${!key:-}" ]; then
                        value=$(read_env_value "$supabase_env_file" "$key")
                        if [ -n "$value" ]; then
                            export "$key=$value"
                        fi
                    fi
                done
            fi
            [ -n "${SUPABASE_PUBLIC_PORT:-}" ] && supabase_public_port="$SUPABASE_PUBLIC_PORT"
            [ -n "${SUPABASE_DB_PORT:-}" ] && supabase_db_port="$SUPABASE_DB_PORT"
        else
            supabase_compose=""
        fi
    fi

    if ! is_port_free "$db_port"; then
        handle_port_conflict "$db_port" "PostgreSQL"
        case $? in
            2)
                skip_db=true
                echo -e "${YELLOW}Skipping PostgreSQL container; backend will use host.docker.internal:$db_port.${NC}"
                ;;
            1)
                return 1
                ;;
        esac
    fi

    if ! is_port_free "$redis_port"; then
        handle_port_conflict "$redis_port" "Redis"
        case $? in
            2)
                skip_redis=true
                echo -e "${YELLOW}Skipping Redis container; backend will use host.docker.internal:$redis_port.${NC}"
                ;;
            1)
                return 1
                ;;
        esac
    fi

    if [ -n "$supabase_compose" ]; then
        local requested_public_port="$supabase_public_port"
        if ! is_port_free "$supabase_public_port"; then
            local new_port
            new_port=$(find_free_port "$supabase_public_port")
            echo -e "${BLUE}Note: supabase public using port $new_port instead of $supabase_public_port${NC}"
            supabase_public_port="$new_port"
        fi
        if ! is_port_free "$supabase_db_port"; then
            local new_port
            new_port=$(find_free_port "$supabase_db_port")
            echo -e "${BLUE}Note: supabase db using port $new_port instead of $supabase_db_port${NC}"
            supabase_db_port="$new_port"
        fi
        export SUPABASE_PUBLIC_PORT="$supabase_public_port"
        export SUPABASE_DB_PORT="$supabase_db_port"

        local requested_url="${SUPABASE_PUBLIC_URL:-}"
        local default_url="http://localhost:${requested_public_port}"
        if [ -z "$requested_url" ] || [ "$requested_url" = "$default_url" ]; then
            export SUPABASE_PUBLIC_URL="http://localhost:${supabase_public_port}"
        fi
        if [ -z "${VITE_SUPABASE_URL:-}" ]; then
            export VITE_SUPABASE_URL="${SUPABASE_PUBLIC_URL}"
        fi
    fi

    if [ "$n8n_enabled" = true ]; then
        local requested_n8n="$n8n_port"
        if ! is_port_free "$n8n_port"; then
            n8n_port=$(find_free_port "$n8n_port")
            echo -e "${BLUE}Note: n8n using port $n8n_port instead of $requested_n8n${NC}"
        fi
        export N8N_PORT="$n8n_port"

        local default_editor="http://localhost:5678"
        local default_webhook="http://localhost:5678/"
        if [ -z "${N8N_EDITOR_BASE_URL:-}" ] || [ "${N8N_EDITOR_BASE_URL}" = "$default_editor" ]; then
            export N8N_EDITOR_BASE_URL="http://localhost:${n8n_port}"
        fi
        if [ -z "${N8N_WEBHOOK_URL:-}" ] || [ "${N8N_WEBHOOK_URL}" = "$default_webhook" ]; then
            export N8N_WEBHOOK_URL="http://localhost:${n8n_port}/"
        fi
    fi

    local backend_port="$backend_port_base"
    if ! is_port_free "$backend_port_base"; then
        backend_port=$(find_free_port "$backend_port_base")
        echo -e "${BLUE}Note: backend using port $backend_port instead of $backend_port_base${NC}"
    fi

    local frontend_target="$frontend_port_base"
    if [ "$backend_port" -ne "$backend_port_base" ]; then
        local diff=$((backend_port - backend_port_base))
        frontend_target=$((frontend_port_base + diff))
        echo -e "${BLUE}Adjusting frontend port to maintain offset: $frontend_target${NC}"
    fi

    local frontend_port="$frontend_target"
    if ! is_port_free "$frontend_target"; then
        frontend_port=$(find_free_port "$frontend_target")
        echo -e "${BLUE}Note: frontend using port $frontend_port instead of $frontend_target${NC}"
    fi

    export DB_PORT="$db_port"
    export REDIS_PORT="$redis_port"
    export BACKEND_PORT="$backend_port"
    export FRONTEND_PORT="$frontend_port"
    export VITE_API_URL="http://localhost:$backend_port/api/v1"

    DOCKER_SKIP_DB="$skip_db"
    DOCKER_SKIP_REDIS="$skip_redis"
    DOCKER_UP_NO_DEPS=false
    DOCKER_UP_SERVICES=()

    if [ "$skip_db" = false ]; then
        DOCKER_UP_SERVICES+=("db")
    else
        DOCKER_UP_NO_DEPS=true
    fi

    if [ "$skip_redis" = false ]; then
        DOCKER_UP_SERVICES+=("redis")
    else
        DOCKER_UP_NO_DEPS=true
    fi

    if [ -n "$supabase_compose" ]; then
        DOCKER_UP_SERVICES+=("supabase-db" "supabase-auth" "supabase-kong")
    fi
    if [ "$n8n_enabled" = true ]; then
        DOCKER_UP_SERVICES+=("n8n")
    fi

    DOCKER_UP_SERVICES+=("backend" "frontend")

    if [ "$skip_db" = true ] || [ "$skip_redis" = true ]; then
        local override_path="$LOGS_DIR/docker-compose.override.yml"
        {
            echo "services:"
            echo "  backend:"
            if [ "$skip_db" = true ] || [ "$skip_redis" = true ]; then
                echo "    environment:"
                if [ "$skip_db" = true ]; then
                    echo "      DATABASE_URL: \"postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@host.docker.internal:${DB_PORT}/${DB_NAME}\""
                fi
                if [ "$skip_redis" = true ]; then
                    echo "      REDIS_URL: \"redis://host.docker.internal:${REDIS_PORT}\""
                fi
            fi
            echo "    extra_hosts:"
            echo "      - \"host.docker.internal:host-gateway\""
        } > "$override_path"
        DOCKER_COMPOSE_OVERRIDE="$override_path"
    fi
}

# Check required local tools and provide install hints

docker_effective_services() {
    if [ ${#DOCKER_UP_SERVICES[@]} -gt 0 ]; then
        printf '%s\n' "${DOCKER_UP_SERVICES[@]}"
    else
        docker_compose config --services 2>/dev/null
    fi
}


docker_init_known_services() {
    if [ ${#DOCKER_KNOWN_SERVICES[@]} -gt 0 ]; then
        return 0
    fi

    local service
    while IFS= read -r service; do
        [ -n "$service" ] && DOCKER_KNOWN_SERVICES+=("$service")
    done < <(docker_effective_services)
}


cleanup_docker_log_followers() {
    if [ -n "$DOCKER_LOG_FOLLOW_PID" ]; then
        if kill -0 "$DOCKER_LOG_FOLLOW_PID" 2>/dev/null; then
            pkill -P "$DOCKER_LOG_FOLLOW_PID" 2>/dev/null || true
            kill -TERM "$DOCKER_LOG_FOLLOW_PID" 2>/dev/null || true
            wait "$DOCKER_LOG_FOLLOW_PID" 2>/dev/null || true
        fi
        DOCKER_LOG_FOLLOW_PID=""
    fi

    if [ -z "${DOCKER_COMPOSE_FILE:-}" ]; then
        return 0
    fi

    local current_tty
    current_tty=$(tty 2>/dev/null | sed 's|/dev/||')
    if [ -n "$current_tty" ] && [ "$current_tty" != "not a tty" ]; then
        local pids
        pids=$(ps -o pid= -o tty= -o command= | awk -v tty="$current_tty" '
            $2 == tty && $0 ~ /docker/ && ($0 ~ /logs/ || $0 ~ /compose[^ ]* up/ || $0 ~ /compose .*up/) {print $1}
        ' | tr '\n' ' ')
        if [ -n "$pids" ]; then
            kill -TERM $pids 2>/dev/null || true
        fi
    fi

    local pids
    pids=$(pgrep -f "docker compose .* -p ${DOCKER_PROJECT_NAME} .* logs (-f|--follow)" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        kill -TERM $pids 2>/dev/null || true
    fi

    pids=$(pgrep -f "docker-compose .* -p ${DOCKER_PROJECT_NAME} .* logs (-f|--follow)" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        kill -TERM $pids 2>/dev/null || true
    fi

    pids=$(pgrep -f "docker compose .* logs" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        kill -TERM $pids 2>/dev/null || true
    fi

    pids=$(pgrep -f "docker-compose .* logs" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        kill -TERM $pids 2>/dev/null || true
    fi
}


collect_tree_entries() {
    DOCKER_TREE_ENTRIES=()
    local roots=()
    local tree_root="$BASE_DIR/$TREES_DIR_NAME"

    scan_tree_root() {
        local scan_root=$1
        local prefix=$2
        local tree_dir

        for tree_dir in "$scan_root"/*/; do
            [ -d "$tree_dir" ] || continue
            local tree_name
            tree_name=$(basename "$tree_dir")
            local label="$tree_name"
            if [ -n "$prefix" ]; then
                label="${prefix}-${tree_name}"
            fi

            if [ ${#TREES_TARGETS[@]} -gt 0 ]; then
                local match=false
                local target
                for target in "${TREES_TARGETS[@]}"; do
                    if [ "$tree_name" = "$target" ]; then
                        match=true
                        break
                    fi
                done
                if [ "$match" = false ]; then
                    ((index++))
                    continue
                fi
            fi

            local backend_dir
            local frontend_dir
            backend_dir=$(find_backend_dir "$tree_dir")
            frontend_dir=$(find_frontend_dir "$tree_dir")

            if [ -z "$backend_dir" ] && [ -z "$frontend_dir" ]; then
                echo -e "${YELLOW}Skipping $label: no backend/frontend found${NC}"
                ((index++))
                continue
            fi

            local env_file="${tree_dir%/}/.env"
            local backend_port
            local frontend_port
            backend_port=$(read_env_value "$env_file" "BACKEND_PORT")
            frontend_port=$(read_env_value "$env_file" "FRONTEND_PORT")

            local backend_default=false
            local frontend_default=false

            if [ -z "$backend_port" ] || [ -z "$frontend_port" ]; then
                local ports_from_cfg
                ports_from_cfg=$(read_ports_from_worktree_config "${tree_dir%/}")
                if [ -n "$ports_from_cfg" ]; then
                    local cfg_backend=""
                    local cfg_frontend=""
                    local cfg_db=""
                    local cfg_redis=""
                    IFS='|' read -r cfg_backend cfg_frontend cfg_db cfg_redis <<< "$ports_from_cfg"
                    [ -z "$backend_port" ] && backend_port="$cfg_backend"
                    [ -z "$frontend_port" ] && frontend_port="$cfg_frontend"
                fi
            fi

            if [ -z "$backend_port" ]; then
                backend_port=$((BACKEND_PORT_BASE + index * PORT_SPACING))
                backend_default=true
            fi
            if [ -z "$frontend_port" ]; then
                frontend_port=$((FRONTEND_PORT_BASE + index * PORT_SPACING))
                frontend_default=true
            fi

            local requested_backend=$backend_port
            backend_port=$(reserve_port "$backend_port")
            if [ "$backend_port" != "$requested_backend" ]; then
                echo -e "${BLUE}Note: $label backend using port $backend_port instead of $requested_backend${NC}"
            fi

            if [ "$backend_default" = true ] && [ "$backend_port" -ne "$requested_backend" ]; then
                local diff=$((backend_port - requested_backend))
                frontend_port=$((frontend_port + diff))
            fi

            local requested_frontend=$frontend_port
            frontend_port=$(reserve_port "$frontend_port")
            if [ "$frontend_port" != "$requested_frontend" ]; then
                echo -e "${BLUE}Note: $label frontend using port $frontend_port instead of $requested_frontend${NC}"
            fi

            local slug
            slug=$(slugify "$label")
            if [ -z "$slug" ]; then
                slug="tree-$index"
            fi

            DOCKER_TREE_ENTRIES+=("$label|${tree_dir%/}|$backend_dir|$frontend_dir|$backend_port|$frontend_port|$slug")
            ((index++))
        done
    }

    if [ -d "$tree_root" ]; then
        roots+=("$tree_root")
    else
        local found=false
        for candidate in "$BASE_DIR"/trees-*; do
            [ -d "$candidate" ] || continue
            roots+=("$candidate")
            found=true
        done
        if [ "$found" = true ]; then
            echo -e "${YELLOW}No $TREES_DIR_NAME directory found; using trees-* worktrees.${NC}"
        else
            echo -e "${RED}No $TREES_DIR_NAME directory found${NC}"
            return 1
        fi
    fi

    local index=0
    local root
    for root in "${roots[@]}"; do
        local root_name
        root_name=$(basename "$root")
        if [[ "$root_name" == trees-* ]]; then
            scan_tree_root "$root" "${root_name#trees-}"
            continue
        fi

        local has_numeric=false
        local candidate
        for candidate in "$root"/*/; do
            [ -d "$candidate" ] || continue
            local base
            base=$(basename "$candidate")
            if [[ "$base" =~ ^[0-9]+$ ]]; then
                has_numeric=true
                break
            fi
        done

        if [ "$has_numeric" = true ]; then
            scan_tree_root "$root" ""
            continue
        fi

        local feature_dir
        for feature_dir in "$root"/*/; do
            [ -d "$feature_dir" ] || continue
            local feature
            feature=$(basename "$feature_dir")
            if [ -n "$TREES_FEATURE_FILTER" ] && [ "$feature" != "$TREES_FEATURE_FILTER" ]; then
                continue
            fi
            scan_tree_root "$feature_dir" "$feature"
        done
    done

    if [ ${#DOCKER_TREE_ENTRIES[@]} -eq 0 ]; then
        echo -e "${RED}No trees found to run${NC}"
        return 1
    fi
}


generate_docker_compose_trees() {
    local compose_path="$LOGS_DIR/docker-compose.trees.yml"
    DOCKER_COMPOSE_FILE="$compose_path"
    DOCKER_COMPOSE_OVERRIDE=""
    DOCKER_COMPOSE_EXTRA_FILES=()
    DOCKER_UP_SERVICES=()
    DOCKER_UP_NO_DEPS=false

    {
        echo "services:"

        if [ "$DOCKER_SKIP_DB" = false ]; then
            echo "  db:"
            echo "    image: postgres:15-alpine"
            echo "    environment:"
            echo "      POSTGRES_USER: ${DB_USER}"
            echo "      POSTGRES_PASSWORD: ${DB_PASSWORD}"
            echo "      POSTGRES_DB: ${DB_NAME}"
            echo "    ports:"
            echo "      - \"${DB_PORT}:5432\""
            echo "    volumes:"
            echo "      - postgres_data:/var/lib/postgresql/data"
            echo "    healthcheck:"
            echo "      test: [\"CMD-SHELL\", \"pg_isready -U ${DB_USER}\"]"
            echo "      interval: 10s"
            echo "      timeout: 5s"
            echo "      retries: 5"
            DOCKER_UP_SERVICES+=("db")
        fi

        if [ "$DOCKER_SKIP_REDIS" = false ]; then
            echo "  redis:"
            echo "    image: redis:7-alpine"
            echo "    ports:"
            echo "      - \"${REDIS_PORT}:6379\""
            echo "    command: redis-server --appendonly yes"
            echo "    volumes:"
            echo "      - redis_data:/data"
            echo "    healthcheck:"
            echo "      test: [\"CMD\", \"redis-cli\", \"ping\"]"
            echo "      interval: 10s"
            echo "      timeout: 5s"
            echo "      retries: 5"
            DOCKER_UP_SERVICES+=("redis")
        fi

        local entry
        for entry in "${DOCKER_TREE_ENTRIES[@]}"; do
            IFS='|' read -r label tree_dir backend_dir frontend_dir backend_port frontend_port slug <<< "$entry"

            local backend_service="${slug}-backend"
            local frontend_service="${slug}-frontend"
            local api_url="http://localhost:${backend_port}/api/v1"

            if [ -n "$backend_dir" ]; then
                echo "  ${backend_service}:"
                echo "    build:"
                echo "      context: ${backend_dir}"
                echo "    ports:"
                echo "      - \"${backend_port}:8000\""
                echo "    environment:"
                if [ "$DOCKER_SKIP_DB" = true ]; then
                    echo "      DATABASE_URL: \"postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@host.docker.internal:${DB_PORT}/${DB_NAME}\""
                else
                    echo "      DATABASE_URL: \"postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}\""
                fi
                if [ "$DOCKER_SKIP_REDIS" = true ]; then
                    echo "      REDIS_URL: \"redis://host.docker.internal:${REDIS_PORT}\""
                else
                    echo "      REDIS_URL: \"redis://redis:6379\""
                fi
                echo "      ENVIRONMENT: development"
                echo "      DEBUG: \"true\""

                if [ "$DOCKER_SKIP_DB" = true ] || [ "$DOCKER_SKIP_REDIS" = true ]; then
                    echo "    extra_hosts:"
                    echo "      - \"host.docker.internal:host-gateway\""
                fi

                if [ "$DOCKER_SKIP_DB" = false ] || [ "$DOCKER_SKIP_REDIS" = false ]; then
                    echo "    depends_on:"
                    if [ "$DOCKER_SKIP_DB" = false ]; then
                        echo "      db:"
                        echo "        condition: service_healthy"
                    fi
                    if [ "$DOCKER_SKIP_REDIS" = false ]; then
                        echo "      redis:"
                        echo "        condition: service_healthy"
                    fi
                fi

                echo "    command: >"
                echo "      sh -c \"alembic upgrade head &&"
                echo "             uvicorn app.main:app --host 0.0.0.0 --port 8000\""
            DOCKER_UP_SERVICES+=("$backend_service")
        fi

        if [ -n "$frontend_dir" ]; then
                echo "  ${frontend_service}:"
                echo "    build:"
                echo "      context: ${frontend_dir}"
                echo "      args:"
                echo "        VITE_API_URL: ${api_url}"
                echo "    ports:"
                echo "      - \"${frontend_port}:80\""
                if [ -n "$backend_dir" ]; then
                    echo "    depends_on:"
                    echo "      - ${backend_service}"
                fi
            DOCKER_UP_SERVICES+=("$frontend_service")
        fi
    done

        if [ "$DOCKER_SKIP_DB" = false ] || [ "$DOCKER_SKIP_REDIS" = false ]; then
            echo "volumes:"
            if [ "$DOCKER_SKIP_DB" = false ]; then
                echo "  postgres_data:"
            fi
            if [ "$DOCKER_SKIP_REDIS" = false ]; then
                echo "  redis_data:"
            fi
        fi
    } > "$compose_path"

    DOCKER_KNOWN_SERVICES=("${DOCKER_UP_SERVICES[@]}")
}


resolve_docker_trees() {
    local db_port="${DB_PORT:-5432}"
    local redis_port="${REDIS_PORT:-6379}"
    local skip_db=false
    local skip_redis=false

    if ! is_port_free "$db_port"; then
        handle_port_conflict "$db_port" "PostgreSQL"
        case $? in
            2)
                skip_db=true
                echo -e "${YELLOW}Skipping PostgreSQL container; backends will use host.docker.internal:${db_port}.${NC}"
                ;;
            1)
                return 1
                ;;
        esac
    fi

    if ! is_port_free "$redis_port"; then
        handle_port_conflict "$redis_port" "Redis"
        case $? in
            2)
                skip_redis=true
                echo -e "${YELLOW}Skipping Redis container; backends will use host.docker.internal:${redis_port}.${NC}"
                ;;
            1)
                return 1
                ;;
        esac
    fi

    export DB_PORT="$db_port"
    export REDIS_PORT="$redis_port"
    DOCKER_SKIP_DB="$skip_db"
    DOCKER_SKIP_REDIS="$skip_redis"

    if [ "$skip_db" = false ]; then
        RUN_RESERVED_PORTS[$db_port]=1
    fi
    if [ "$skip_redis" = false ]; then
        RUN_RESERVED_PORTS[$redis_port]=1
    fi

    if ! collect_tree_entries; then
        return 1
    fi

    generate_docker_compose_trees
}


docker_published_port() {
    local publishers_json=$1
    local ports=$2
    local port=""

    if [ -n "$publishers_json" ] && [ "$publishers_json" != "null" ] && [ "$publishers_json" != "[]" ]; then
        port=$(echo "$publishers_json" | jq -r '.[0].PublishedPort // empty' 2>/dev/null)
    fi

    if [ -z "$port" ] && [ -n "$ports" ]; then
        port=$(echo "$ports" | grep -oE ':[0-9]+->' | head -n1 | tr -d ':->')
    fi

    echo "$port"
}


docker_list_services() {
    docker_init_known_services
    if [ ${#DOCKER_KNOWN_SERVICES[@]} -gt 0 ]; then
        printf '%s\n' "${DOCKER_KNOWN_SERVICES[@]}"
    else
        docker_effective_services
    fi
}


docker_show_status() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}Docker Compose Services:${NC}"
    echo -e "${CYAN}========================================${NC}"
    local services=()
    local service
    while IFS= read -r service; do
        [ -n "$service" ] && services+=("$service")
    done < <(docker_list_services)

    local ps_json
    if [ ${#services[@]} -gt 0 ]; then
        ps_json=$(docker_compose ps --format json "${services[@]}" 2>/dev/null)
    else
        ps_json=$(docker_compose ps --format json 2>/dev/null)
    fi

    if [ ${#services[@]} -eq 0 ]; then
        echo -e "${YELLOW}No Docker services configured${NC}"
        echo
        return 0
    fi

    declare -A docker_state=()
    declare -A docker_status=()
    declare -A docker_health=()
    declare -A docker_ports=()
    declare -A docker_publishers=()

    if [ -n "$ps_json" ]; then
        while IFS= read -r line; do
            [ -z "$line" ] && continue

            local svc
            svc=$(echo "$line" | jq -r '.Service // ""')
            [ -z "$svc" ] && continue

            docker_state["$svc"]=$(echo "$line" | jq -r '.State // ""')
            docker_status["$svc"]=$(echo "$line" | jq -r '.Status // ""')
            docker_health["$svc"]=$(echo "$line" | jq -r '.Health // ""')
            docker_ports["$svc"]=$(echo "$line" | jq -r '.Ports // ""')
            docker_publishers["$svc"]=$(echo "$line" | jq -c '.Publishers // []')
        done <<< "$ps_json"
    fi

    local svc
    for svc in "${services[@]}"; do
        local state="${docker_state[$svc]:-}"
        local status="${docker_status[$svc]:-}"
        local health="${docker_health[$svc]:-}"
        local ports="${docker_ports[$svc]:-}"
        local publishers="${docker_publishers[$svc]:-}"

        if [ -z "$state" ]; then
            echo -e "  ${RED}✗${NC} ${svc}: stopped"
            continue
        fi

        local icon="${GREEN}✓${NC}"
        if [ "$state" != "running" ]; then
            icon="${RED}✗${NC}"
        elif [ "$health" != "" ] && [ "$health" != "healthy" ] && [[ "$status" != *"(healthy)"* ]]; then
            icon="${YELLOW}~${NC}"
        fi

        local host_port
        host_port=$(docker_published_port "$publishers" "$ports")

        local address="internal"
        if [ -n "$host_port" ]; then
            case "$svc" in
                *backend*|*frontend*)
                    address="http://localhost:${host_port}"
                    ;;
                *)
                    address="localhost:${host_port}"
                    ;;
            esac
        fi

        if [ -n "$status" ]; then
            echo -e "  ${icon} ${svc}: ${address} (${status})"
        else
            echo -e "  ${icon} ${svc}: ${address}"
        fi
    done

    echo
}

docker_select_service() (
    local prompt=${1:-"Select service"}
    local include_all=${2:-false}
    local options=()
    local values=()

    if [ "$include_all" = true ]; then
        options+=("All services")
        values+=("__ALL__")
    fi

    local service
    while IFS= read -r service; do
        [ -z "$service" ] && continue
        options+=("$service")
        values+=("$service")
    done < <(docker_list_services)

    select_menu "$prompt" options values
)

docker_select_build_target() (
    local services=()
    local service
    while IFS= read -r service; do
        [ -n "$service" ] && services+=("$service")
    done < <(docker_list_services)

    local backend_services=()
    local frontend_services=()
    for service in "${services[@]}"; do
        if [[ "$service" == *backend* ]]; then
            backend_services+=("$service")
        elif [[ "$service" == *frontend* ]]; then
            frontend_services+=("$service")
        fi
    done

    local options=("All app services")
    if [ ${#backend_services[@]} -gt 1 ]; then
        options+=("All backends")
    fi
    if [ ${#frontend_services[@]} -gt 1 ]; then
        options+=("All frontends")
    fi
    if [ ${#backend_services[@]} -gt 0 ]; then
        options+=("${backend_services[@]}")
    fi
    if [ ${#frontend_services[@]} -gt 0 ]; then
        options+=("${frontend_services[@]}")
    fi

    local values=()
    values+=("__ALL_APP__")
    if [ ${#backend_services[@]} -gt 1 ]; then
        values+=("__ALL_BACKENDS__")
    fi
    if [ ${#frontend_services[@]} -gt 1 ]; then
        values+=("__ALL_FRONTENDS__")
    fi
    if [ ${#backend_services[@]} -gt 0 ]; then
        for service in "${backend_services[@]}"; do
            values+=("$service")
        done
    fi
    if [ ${#frontend_services[@]} -gt 0 ]; then
        for service in "${frontend_services[@]}"; do
            values+=("$service")
        done
    fi

    select_menu "Rebuild" options values
)


docker_restart_service() {
    local target=$1
    if [ "$target" = "__ALL__" ]; then
        local services=()
        local service
        while IFS= read -r service; do
            [ -n "$service" ] && services+=("$service")
        done < <(docker_list_services)

        if [ ${#services[@]} -eq 0 ]; then
            echo -e "${YELLOW}No running services to restart.${NC}"
            return 0
        fi

        docker_compose restart "${services[@]}"
    else
        docker_compose restart "$target"
    fi
}


docker_rebuild_services() {
    local target=$1
    if [ "$target" = "__ALL_APP__" ]; then
        local apps=()
        local service
        while IFS= read -r service; do
            if [[ "$service" == *backend* ]] || [[ "$service" == *frontend* ]]; then
                apps+=("$service")
            fi
        done < <(docker_list_services)
        if [ ${#apps[@]} -gt 0 ]; then
            docker_compose build "${apps[@]}"
        fi
    elif [ "$target" = "__ALL_BACKENDS__" ]; then
        local backends=()
        local service
        while IFS= read -r service; do
            if [[ "$service" == *backend* ]]; then
                backends+=("$service")
            fi
        done < <(docker_list_services)
        if [ ${#backends[@]} -gt 0 ]; then
            docker_compose build "${backends[@]}"
        fi
    elif [ "$target" = "__ALL_FRONTENDS__" ]; then
        local frontends=()
        local service
        while IFS= read -r service; do
            if [[ "$service" == *frontend* ]]; then
                frontends+=("$service")
            fi
        done < <(docker_list_services)
        if [ ${#frontends[@]} -gt 0 ]; then
            docker_compose build "${frontends[@]}"
        fi
    else
        docker_compose build "$target"
    fi
    echo -e "${GREEN}✓ Rebuild complete${NC}"
    echo -e "${BLUE}Note:${NC} Use restart to apply rebuilt images."
}


docker_tail_logs() {
    local target=$1
    cleanup_docker_log_followers
    if [ "$target" = "__ALL__" ]; then
        local services=()
        local service
        while IFS= read -r service; do
            [ -n "$service" ] && services+=("$service")
        done < <(docker_list_services)

        if [ ${#services[@]} -eq 0 ]; then
            echo -e "${YELLOW}No running services to tail.${NC}"
            return 0
        fi

        docker_compose logs -f --tail 200 "${services[@]}" &
    else
        docker_compose logs -f --tail 200 "$target" &
    fi

    local log_pid=$!
    DOCKER_LOG_FOLLOW_PID="$log_pid"
    echo -e "${CYAN}Tailing Docker logs (press Enter or Esc to stop)...${NC}"
    while true; do
        IFS= read -rsn1 key
        if [ "$key" = $'\x1b' ] || [ -z "$key" ]; then
            break
        fi
    done
    pkill -P "$log_pid" 2>/dev/null || true
    kill -TERM "$log_pid" 2>/dev/null || true
    wait "$log_pid" 2>/dev/null || true
    DOCKER_LOG_FOLLOW_PID=""
    echo -e "${CYAN}Stopped tailing logs${NC}"
}


docker_show_errors() {
    local pattern="$LOG_ERROR_PATTERN"
    local errors
    local services=()
    local service
    while IFS= read -r service; do
        [ -n "$service" ] && services+=("$service")
    done < <(docker_list_services)

    if [ ${#services[@]} -gt 0 ]; then
        errors=$(docker_compose logs --no-color --tail 200 "${services[@]}" 2>/dev/null | grep -i -E "$pattern" || true)
    else
        errors=$(docker_compose logs --no-color --tail 200 2>/dev/null | grep -i -E "$pattern" || true)
    fi

    echo -e "\n${CYAN}Recent errors from Docker services:${NC}"
    echo -e "${CYAN}========================================${NC}"

    if [ -z "$errors" ]; then
        echo -e "${GREEN}No recent errors found${NC}"
        echo
        return 0
    fi

    echo "$errors"
    echo
}


docker_check_health() {
    local services=()
    local service
    while IFS= read -r service; do
        [ -n "$service" ] && services+=("$service")
    done < <(docker_list_services)

    local ps_json
    if [ ${#services[@]} -gt 0 ]; then
        ps_json=$(docker_compose ps --format json "${services[@]}" 2>/dev/null)
    else
        ps_json=$(docker_compose ps --format json 2>/dev/null)
    fi

    echo -e "\n${CYAN}Checking health of Docker services...${NC}"

    if [ ${#services[@]} -eq 0 ]; then
        echo -e "${YELLOW}No services configured${NC}"
        echo
        return 0
    fi

    declare -A docker_ports=()
    declare -A docker_publishers=()
    declare -A docker_state=()

    if [ -n "$ps_json" ]; then
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local svc
            svc=$(echo "$line" | jq -r '.Service // ""')
            [ -z "$svc" ] && continue
            docker_ports["$svc"]=$(echo "$line" | jq -r '.Ports // ""')
            docker_publishers["$svc"]=$(echo "$line" | jq -c '.Publishers // []')
            docker_state["$svc"]=$(echo "$line" | jq -r '.State // ""')
        done <<< "$ps_json"
    fi

    local svc
    for svc in "${services[@]}"; do
        if [[ "$svc" != *backend* && "$svc" != *frontend* ]]; then
            continue
        fi

        if [ -z "${docker_state[$svc]:-}" ]; then
            echo -e "  ${RED}✗${NC} $svc: stopped"
            continue
        fi

        local endpoint=""
        if [[ "$svc" == *backend* ]]; then
            endpoint="/api/v1/health"
        else
            endpoint="/healthz"
        fi

        local host_port
        host_port=$(docker_published_port "${docker_publishers[$svc]:-}" "${docker_ports[$svc]:-}")
        if [ -z "$host_port" ]; then
            echo -e "  ${YELLOW}~${NC} $svc: no published port"
            continue
        fi

        echo -n "  Checking $svc... "
        if curl -s -f -m 2 "http://localhost:${host_port}${endpoint}" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Healthy${NC}"
        else
            echo -e "${RED}✗ Not responding${NC}"
        fi
    done
    echo
}


docker_stop_services() {
    local apps=()
    local service
    while IFS= read -r service; do
        if [[ "$service" == *backend* ]] || [[ "$service" == *frontend* ]]; then
            apps+=("$service")
        fi
    done < <(docker_list_services)

    if [ ${#apps[@]} -eq 0 ]; then
        echo -e "${YELLOW}No app services to stop.${NC}"
        return 0
    fi

    if ! docker_compose stop "${apps[@]}" >/dev/null 2>&1; then
        echo -e "${RED}Failed to stop app containers.${NC}"
        return 1
    fi
}


docker_stop_all() {
    local remove_volumes=${1:-false}
    if [ "$remove_volumes" = true ]; then
        docker_compose down -v
    else
        docker_compose down
    fi
    maybe_stop_docker
}

docker_containers_on_port() {
    local port=$1
    docker_cmd ps --format '{{.Names}}' --filter "publish=$port" 2>/dev/null | tr '\n' ' '
}


docker_containers_on_port_details() {
    local port=$1
    docker_cmd ps --format '{{.Names}}\t{{.Ports}}' --filter "publish=$port" 2>/dev/null
}


local_port_listeners() {
    local port=$1
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -n +2
}
