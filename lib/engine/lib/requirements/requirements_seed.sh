#!/usr/bin/env bash

# Requirement seeding helpers.

enable_requirements_seed_from_base() {
    SEED_REQUIREMENTS_ACTIVE=false
    if [ "$SEED_REQUIREMENTS_FROM_BASE" != true ]; then
        return 0
    fi
    if ! per_tree_requirements_enabled; then
        return 0
    fi
    if is_port_free "$DB_PORT_BASE"; then
        echo -e "${YELLOW}Base DB port ${DB_PORT_BASE} is free; skipping seed.${NC}"
        return 0
    fi

    echo -e "${CYAN}Base DB port ${DB_PORT_BASE} in use; checking credentials...${NC}"
    local args=()
    args=($(docker_host_gateway_args))
    if docker run --rm "${args[@]}" -e PGPASSWORD="$DB_PASSWORD" postgres:15-alpine \
        psql -h "$SEED_REQUIREMENTS_HOST" -p "$DB_PORT_BASE" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" >/dev/null 2>&1; then
        SEED_REQUIREMENTS_ACTIVE=true
        echo -e "${GREEN}✓ Base DB auth succeeded; per-tree DBs will be seeded.${NC}"
        if [ "$SEED_REQUIREMENTS_MODE" = "volume" ]; then
            if ! prepare_postgres_seed_volume; then
                echo -e "${YELLOW}⚠ Postgres seed volume unavailable; DB seed will be skipped.${NC}"
            fi
            if ! prepare_redis_seed_volume; then
                echo -e "${YELLOW}⚠ Redis seed volume unavailable; Redis seed will be skipped.${NC}"
            fi
        fi
        return 0
    fi

    echo -e "${YELLOW}Could not authenticate to base DB; skipping seed.${NC}"
    return 0
}

prepare_postgres_seed_volume() {
    if [ "$SEED_REQUIREMENTS_DB_READY" = true ]; then
        return 0
    fi

    local base_container
    base_container=$(find_container_by_port "$DB_PORT_BASE" "5432" 2>/dev/null || true)
    if [ -z "$base_container" ]; then
        echo -e "${YELLOW}Base DB container not found on port ${DB_PORT_BASE}.${NC}"
        return 1
    fi

    local base_volume
    base_volume=$(container_volume_for_path "$base_container" "/var/lib/postgresql/data")
    if [ -z "$base_volume" ]; then
        echo -e "${YELLOW}Base DB container has no named volume; cannot seed by volume.${NC}"
        return 1
    fi

    local seed_volume="${base_container}-seed-${TIMESTAMP}"
    echo -e "${CYAN}Creating seed volume from ${base_container}...${NC}"
    if ! docker stop "$base_container" >/dev/null 2>&1; then
        echo -e "${YELLOW}Could not stop ${base_container}; skipping volume seed.${NC}"
        return 1
    fi

    docker volume create "$seed_volume" >/dev/null 2>&1 || true
    if ! docker run --rm -v "${base_volume}:/from" -v "${seed_volume}:/to" alpine \
        sh -c "cp -a /from/. /to/" >/dev/null 2>&1; then
        echo -e "${YELLOW}Failed to copy base volume; skipping volume seed.${NC}"
        docker start "$base_container" >/dev/null 2>&1 || true
        return 1
    fi

    docker start "$base_container" >/dev/null 2>&1 || true
    SEED_REQUIREMENTS_DB_VOLUME="$seed_volume"
    SEED_REQUIREMENTS_DB_READY=true
    return 0
}

prepare_redis_seed_volume() {
    if [ "$SEED_REQUIREMENTS_REDIS_READY" = true ]; then
        return 0
    fi

    if is_port_free "$REDIS_PORT_BASE"; then
        return 1
    fi

    local base_container
    base_container=$(find_container_by_port "$REDIS_PORT_BASE" "6379" 2>/dev/null || true)
    if [ -z "$base_container" ]; then
        echo -e "${YELLOW}Base Redis container not found on port ${REDIS_PORT_BASE}.${NC}"
        return 1
    fi

    local base_volume
    base_volume=$(container_volume_for_path "$base_container" "/data")
    if [ -z "$base_volume" ]; then
        echo -e "${YELLOW}Base Redis container has no named volume; cannot seed by volume.${NC}"
        return 1
    fi

    local seed_volume="${base_container}-seed-${TIMESTAMP}"
    echo -e "${CYAN}Creating Redis seed volume from ${base_container}...${NC}"
    if ! docker stop "$base_container" >/dev/null 2>&1; then
        echo -e "${YELLOW}Could not stop ${base_container}; skipping Redis volume seed.${NC}"
        return 1
    fi

    docker volume create "$seed_volume" >/dev/null 2>&1 || true
    if ! docker run --rm -v "${base_volume}:/from" -v "${seed_volume}:/to" alpine \
        sh -c "cp -a /from/. /to/" >/dev/null 2>&1; then
        echo -e "${YELLOW}Failed to copy Redis volume; skipping volume seed.${NC}"
        docker start "$base_container" >/dev/null 2>&1 || true
        return 1
    fi

    docker start "$base_container" >/dev/null 2>&1 || true
    SEED_REQUIREMENTS_REDIS_VOLUME="$seed_volume"
    SEED_REQUIREMENTS_REDIS_READY=true
    return 0
}

seed_tree_postgres_volume() {
    local target_volume=$1
    if [ "$SEED_REQUIREMENTS_DB_READY" != true ] || [ -z "$SEED_REQUIREMENTS_DB_VOLUME" ]; then
        return 1
    fi

    echo -e "${CYAN}Copying base DB volume into ${target_volume}...${NC}"
    docker volume create "$target_volume" >/dev/null 2>&1 || true
    if docker run --rm -v "${SEED_REQUIREMENTS_DB_VOLUME}:/from" -v "${target_volume}:/to" alpine \
        sh -c "cp -a /from/. /to/" >/dev/null 2>&1; then
        return 0
    fi
    echo -e "${YELLOW}⚠ Failed to copy base volume into ${target_volume}.${NC}"
    return 1
}

seed_tree_redis_volume() {
    local target_volume=$1
    if [ "$SEED_REQUIREMENTS_REDIS_READY" != true ] || [ -z "$SEED_REQUIREMENTS_REDIS_VOLUME" ]; then
        return 1
    fi

    echo -e "${CYAN}Copying base Redis volume into ${target_volume}...${NC}"
    docker volume create "$target_volume" >/dev/null 2>&1 || true
    if docker run --rm -v "${SEED_REQUIREMENTS_REDIS_VOLUME}:/from" -v "${target_volume}:/to" alpine \
        sh -c "cp -a /from/. /to/" >/dev/null 2>&1; then
        return 0
    fi
    echo -e "${YELLOW}⚠ Failed to copy base Redis volume into ${target_volume}.${NC}"
    return 1
}

seed_tree_postgres_from_base() {
    local container_name=$1
    local args=()
    args=($(docker_host_gateway_args))

    echo -e "${CYAN}Seeding ${container_name} from base DB...${NC}"
    if docker run --rm "${args[@]}" -e PGPASSWORD="$DB_PASSWORD" postgres:15-alpine \
        pg_dump -h "$SEED_REQUIREMENTS_HOST" -p "$DB_PORT_BASE" -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges \
        | docker exec -i "$container_name" psql -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Seeded ${container_name}${NC}"
        return 0
    fi
    echo -e "${YELLOW}⚠ Failed to seed ${container_name}; continuing.${NC}"
    return 1
}

prepare_redis_seed_file() {
    if [ "$SEED_REQUIREMENTS_MODE" = "volume" ]; then
        return 1
    fi
    if [ "$REDIS_SEED_READY" = true ]; then
        return 0
    fi
    if is_port_free "$REDIS_PORT_BASE"; then
        return 1
    fi

    local tmp_dir="${LOGS_DIR}/redis-seed"
    mkdir -p "$tmp_dir"
    local seed_path="${tmp_dir}/dump.rdb"
    local args=()
    args=($(docker_host_gateway_args))
    local redis_args=()
    if [ -n "$REDIS_PASSWORD" ]; then
        redis_args+=("-a" "$REDIS_PASSWORD")
    fi

    if docker run --rm "${args[@]}" -v "${tmp_dir}:/out" redis:7-alpine \
        redis-cli -h "$SEED_REQUIREMENTS_HOST" -p "$REDIS_PORT_BASE" "${redis_args[@]}" --rdb /out/dump.rdb >/dev/null 2>&1; then
        if [ -f "$seed_path" ]; then
            REDIS_SEED_FILE="$seed_path"
            REDIS_SEED_READY=true
            return 0
        fi
    fi
    return 1
}

seed_tree_redis_from_base() {
    local container_name=$1
    if ! prepare_redis_seed_file; then
        echo -e "${YELLOW}⚠ Redis seed unavailable; continuing without seed.${NC}"
        return 1
    fi
    echo -e "${CYAN}Seeding ${container_name} from base Redis...${NC}"
    docker stop "$container_name" >/dev/null 2>&1 || true
    if ! docker cp "$REDIS_SEED_FILE" "$container_name":/data/dump.rdb >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠ Failed to copy Redis seed to ${container_name}.${NC}"
        docker start "$container_name" >/dev/null 2>&1 || true
        return 1
    fi
    docker start "$container_name" >/dev/null 2>&1 || true
    return 0
}
