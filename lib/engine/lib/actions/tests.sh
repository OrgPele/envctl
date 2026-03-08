#!/usr/bin/env bash

# Test runner helpers (extracted from test-all-trees.sh).

run_backend_tests() {
    local name=$1
    local dir=$2
    local log_file=$3
    
    if [ "$PARALLEL_MODE" = false ]; then
        echo -e "${BLUE}Running backend tests for $name...${NC}" | tee -a "$log_file"
    else
        echo "Running backend tests for $name..." >> "$log_file"
    fi
    
    if [ ! -d "$dir" ]; then
        echo -e "${YELLOW}Backend directory not found: $dir${NC}" | tee -a "$log_file"
        return 2
    fi

    cd "$dir"
    
    # Set required environment variables for backend tests
    export DATABASE_URL="postgresql+asyncpg://test:test@localhost/test"
    export REDIS_URL="redis://localhost:6379"
    export ENVIRONMENT="test"
    
    # Detect test framework and run tests
    if [ -f "pyproject.toml" ] && command -v poetry >/dev/null 2>&1; then
        echo "Using Poetry to run tests..." >> "$log_file"
        
        # Check if pytest is available
        if poetry run pytest --version >> "$log_file" 2>&1; then
            echo "Running pytest..." >> "$log_file"
            
            if [ "$RUN_COVERAGE" = true ]; then
                if [ "$VERBOSE_MODE" = true ]; then
                    poetry run pytest -v --cov=app --cov-report=html --cov-report=term 2>&1 | tee -a "$log_file"
                else
                    poetry run pytest --cov=app --cov-report=html --cov-report=term >> "$log_file" 2>&1
                fi
                RESULT=${PIPESTATUS[0]}
                
                # Copy coverage report if it exists
                if [ -d "htmlcov" ]; then
                    cp -r htmlcov "$RESULTS_DIR/${name}_backend_coverage"
                    echo -e "${GREEN}Coverage report saved to: $RESULTS_DIR/${name}_backend_coverage${NC}" | tee -a "$log_file"
                fi
            else
                if [ "$VERBOSE_MODE" = true ]; then
                    poetry run pytest -v 2>&1 | tee -a "$log_file"
                else
                    poetry run pytest >> "$log_file" 2>&1
                fi
                RESULT=${PIPESTATUS[0]}
            fi
            
            return $RESULT
        else
            echo -e "${YELLOW}pytest not found in Poetry environment${NC}" | tee -a "$log_file"
        fi
        
        # Try make test
        if [ -f "Makefile" ] && grep -q "^test:" Makefile; then
            echo "Running make test..." >> "$log_file"
            if [ "$VERBOSE_MODE" = true ]; then
                make test 2>&1 | tee -a "$log_file"
            else
                make test >> "$log_file" 2>&1
            fi
            return $?
        fi
        
    elif [ -f "requirements.txt" ]; then
        echo "Using pip/venv to run tests..." >> "$log_file"
        
        # Set required environment variables for backend tests
        export DATABASE_URL="postgresql+asyncpg://test:test@localhost/test"
        export REDIS_URL="redis://localhost:6379"
        export ENVIRONMENT="test"
        
        # Activate venv if it exists
        if [ -d "venv" ]; then
            source venv/bin/activate
        fi
        
        # Check if pytest is available
        if pytest --version >> "$log_file" 2>&1; then
            echo "Running pytest..." >> "$log_file"
            
            if [ "$RUN_COVERAGE" = true ]; then
                if [ "$VERBOSE_MODE" = true ]; then
                    pytest -v --cov=app --cov-report=html --cov-report=term 2>&1 | tee -a "$log_file"
                else
                    pytest --cov=app --cov-report=html --cov-report=term >> "$log_file" 2>&1
                fi
                RESULT=$?
                
                # Copy coverage report if it exists
                if [ -d "htmlcov" ]; then
                    cp -r htmlcov "$RESULTS_DIR/${name}_backend_coverage"
                    echo -e "${GREEN}Coverage report saved to: $RESULTS_DIR/${name}_backend_coverage${NC}" | tee -a "$log_file"
                fi
            else
                if [ "$VERBOSE_MODE" = true ]; then
                    pytest -v 2>&1 | tee -a "$log_file"
                else
                    pytest >> "$log_file" 2>&1
                fi
                RESULT=$?
            fi
            
            return $RESULT
        fi
        
        # Try python -m pytest
        if python -m pytest --version >> "$log_file" 2>&1; then
            echo "Running python -m pytest..." >> "$log_file"
            if [ "$VERBOSE_MODE" = true ]; then
                python -m pytest -v 2>&1 | tee -a "$log_file"
            else
                python -m pytest >> "$log_file" 2>&1
            fi
            return $?
        fi
    fi
    
    # Try make test as last resort
    if [ -f "Makefile" ] && grep -q "^test:" Makefile; then
        echo "Running make test..." >> "$log_file"
        if [ "$VERBOSE_MODE" = true ]; then
            make test 2>&1 | tee -a "$log_file"
        else
            make test >> "$log_file" 2>&1
        fi
        return $?
    fi
    
    echo -e "${YELLOW}No test runner found for backend${NC}" | tee -a "$log_file"
    return 2
}

# Function to run frontend tests

run_frontend_tests() {
    local name=$1
    local dir=$2
    local log_file=$3
    local backend_port=${4:-}
    local backend_health=${5:-}
    local frontend_health=${6:-}
    local frontend_reason=${7:-}
    local setup_patched=false
    local setup_backup=""
    local setup_file=""
    local frontend_runner="${FRONTEND_TEST_RUNNER:-bun}"
    frontend_runner=$(printf "%s" "$frontend_runner" | tr '[:upper:]' '[:lower:]')
    if [ -z "$frontend_runner" ]; then
        frontend_runner="auto"
    fi
    if [ "$frontend_runner" = "bun" ] && ! command -v bun >/dev/null 2>&1; then
        echo -e "${YELLOW}bun not found; falling back to npm for frontend tests${NC}" | tee -a "$log_file"
        frontend_runner="auto"
    fi
    
    if [ "$PARALLEL_MODE" = false ]; then
        echo -e "${BLUE}Running frontend tests for $name...${NC}" | tee -a "$log_file"
    else
        echo "Running frontend tests for $name..." >> "$log_file"
    fi
    
    if [ ! -d "$dir" ]; then
        echo -e "${YELLOW}Frontend directory not found: $dir${NC}" | tee -a "$log_file"
        return 2
    fi

    if [ -n "$frontend_health" ] && [ "$frontend_health" != "healthy" ]; then
        local reason="${frontend_reason:-frontend not healthy}"
        echo -e "${YELLOW}Skipping frontend tests for $name: $reason${NC}" | tee -a "$log_file"
        return 3
    fi
    
    cd "$dir"
    
    # Check if package.json exists
    if [ ! -f "package.json" ]; then
        echo -e "${YELLOW}No package.json found${NC}" | tee -a "$log_file"
        return 2
    fi
    
    # Install dependencies if node_modules doesn't exist
    if [ ! -d "node_modules" ]; then
        if [ "$frontend_runner" = "bun" ]; then
            echo "Installing dependencies with bun..." >> "$log_file"
            bun install >> "$log_file" 2>&1 || {
                echo "bun install failed; falling back to npm install" >> "$log_file"
                npm install >> "$log_file" 2>&1
            }
        else
            echo "Installing dependencies..." >> "$log_file"
            npm ci >> "$log_file" 2>&1 || npm install >> "$log_file" 2>&1
        fi
    fi
    
    local has_test_script=false
    if grep -q '"test"' package.json; then
        has_test_script=true
    fi

    local env_vars=()
    if [ -n "$backend_port" ]; then
        env_vars+=("VITE_API_URL=http://localhost:${backend_port}/api/v1")
    fi

    local run_integration="${VITE_RUN_INTEGRATION_TESTS:-}"
    if [ -n "$backend_health" ] && [ "$backend_health" != "healthy" ] && [ "$run_integration" = "true" ]; then
        run_integration="false"
        echo -e "${YELLOW}Skipping frontend integration tests for $name: backend not healthy${NC}" | tee -a "$log_file"
    fi
    if [ -n "$run_integration" ]; then
        env_vars+=("VITE_RUN_INTEGRATION_TESTS=$run_integration")
    fi

    local vitest_bin=""
    local has_vitest=false
    if [ -x "node_modules/.bin/vitest" ]; then
        vitest_bin="./node_modules/.bin/vitest"
        if grep -q '"vitest"' package.json || [ -f "vitest.config.js" ] || [ -f "vitest.config.ts" ]; then
            has_vitest=true
        fi
    fi

    if [ "$RUN_COVERAGE" = true ] && grep -q '"test:coverage"' package.json; then
        if [ "$frontend_runner" = "bun" ]; then
            echo "Running bun run test:coverage..." >> "$log_file"
            if [ "$VERBOSE_MODE" = true ]; then
                if [ ${#env_vars[@]} -gt 0 ]; then
                    env "${env_vars[@]}" bun run test:coverage 2>&1 | tee -a "$log_file"
                else
                    bun run test:coverage 2>&1 | tee -a "$log_file"
                fi
            else
                if [ ${#env_vars[@]} -gt 0 ]; then
                    env "${env_vars[@]}" bun run test:coverage >> "$log_file" 2>&1
                else
                    bun run test:coverage >> "$log_file" 2>&1
                fi
            fi
            RESULT=${PIPESTATUS[0]}
        else
            echo "Running npm run test:coverage..." >> "$log_file"
            if [ "$VERBOSE_MODE" = true ]; then
                if [ ${#env_vars[@]} -gt 0 ]; then
                    env "${env_vars[@]}" npm run test:coverage 2>&1 | tee -a "$log_file"
                else
                    npm run test:coverage 2>&1 | tee -a "$log_file"
                fi
            else
                if [ ${#env_vars[@]} -gt 0 ]; then
                    env "${env_vars[@]}" npm run test:coverage >> "$log_file" 2>&1
                else
                    npm run test:coverage >> "$log_file" 2>&1
                fi
            fi
            RESULT=${PIPESTATUS[0]}
        fi
        
        # Copy coverage report if it exists
        if [ -d "coverage" ]; then
            cp -r coverage "$RESULTS_DIR/${name}_frontend_coverage"
            echo -e "${GREEN}Coverage report saved to: $RESULTS_DIR/${name}_frontend_coverage${NC}" | tee -a "$log_file"
        fi
        return $RESULT
    fi

    if [ "$frontend_runner" = "bun" ] && [ "$has_test_script" = true ]; then
        echo "Running bun run test..." >> "$log_file"
        if [ "$VERBOSE_MODE" = true ]; then
            if [ ${#env_vars[@]} -gt 0 ]; then
                env "${env_vars[@]}" bun run test -- --passWithNoTests 2>&1 | tee -a "$log_file"
            else
                bun run test -- --passWithNoTests 2>&1 | tee -a "$log_file"
            fi
        else
            if [ ${#env_vars[@]} -gt 0 ]; then
                env "${env_vars[@]}" bun run test -- --passWithNoTests >> "$log_file" 2>&1
            else
                bun run test -- --passWithNoTests >> "$log_file" 2>&1
            fi
        fi
        RESULT=${PIPESTATUS[0]}
        if [ "$setup_patched" = true ] && [ -n "$setup_backup" ]; then
            mv "$setup_backup" "$setup_file"
        fi
        return $RESULT
    fi

    if [ "$has_vitest" = true ]; then
        echo "Running vitest..." >> "$log_file"
        local vitest_args=("run" "--passWithNoTests")
        if [ "$RUN_COVERAGE" = true ]; then
            vitest_args=("run" "--coverage" "--passWithNoTests")
        fi
        if [ "$VERBOSE_MODE" = true ]; then
            if [ ${#env_vars[@]} -gt 0 ]; then
                env "${env_vars[@]}" "$vitest_bin" "${vitest_args[@]}" 2>&1 | tee -a "$log_file"
            else
                "$vitest_bin" "${vitest_args[@]}" 2>&1 | tee -a "$log_file"
            fi
        else
            if [ ${#env_vars[@]} -gt 0 ]; then
                env "${env_vars[@]}" "$vitest_bin" "${vitest_args[@]}" >> "$log_file" 2>&1
            else
                "$vitest_bin" "${vitest_args[@]}" >> "$log_file" 2>&1
            fi
        fi
        RESULT=${PIPESTATUS[0]}
        if [ "$setup_patched" = true ] && [ -n "$setup_backup" ]; then
            mv "$setup_backup" "$setup_file"
        fi
        return $RESULT
    fi

    if [ "$has_test_script" = true ]; then
        echo "Running npm test..." >> "$log_file"
        if [ "$VERBOSE_MODE" = true ]; then
            if [ ${#env_vars[@]} -gt 0 ]; then
                env "${env_vars[@]}" npm test -- --passWithNoTests 2>&1 | tee -a "$log_file"
            else
                npm test -- --passWithNoTests 2>&1 | tee -a "$log_file"
            fi
        else
            if [ ${#env_vars[@]} -gt 0 ]; then
                env "${env_vars[@]}" npm test -- --passWithNoTests >> "$log_file" 2>&1
            else
                npm test -- --passWithNoTests >> "$log_file" 2>&1
            fi
        fi
        RESULT=${PIPESTATUS[0]}
        if [ "$setup_patched" = true ] && [ -n "$setup_backup" ]; then
            mv "$setup_backup" "$setup_file"
        fi
        return $RESULT
    fi

    if [ "$setup_patched" = true ] && [ -n "$setup_backup" ]; then
        mv "$setup_backup" "$setup_file"
    fi
    echo -e "${YELLOW}No test script found in package.json${NC}" | tee -a "$log_file"
    return 2
}

# Function to test a project

extract_test_counts() {
    local log_file=$1
    local passed=0
    local failed=0
    local errors=0
    
    if [ -f "$log_file" ]; then
        local clean_log
        clean_log=$(sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g' "$log_file")

        # Try to extract pytest summary (e.g., "3 failed, 297 passed")
        # Look for lines with multiple equals signs and test results
        local summary=$(printf '%s\n' "$clean_log" | grep -E "=+\s*[0-9]+.*failed.*passed.*=+|=+\s*[0-9]+.*passed.*=+|=+.*[0-9]+\s+failed.*[0-9]+\s+passed.*=+" | tail -1)
        if [ -n "$summary" ]; then
            # Extract passed count
            if echo "$summary" | grep -q "passed"; then
                passed=$(echo "$summary" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+" | head -1)
            fi
            # Extract failed count
            if echo "$summary" | grep -q "failed"; then
                failed=$(echo "$summary" | grep -oE "[0-9]+ failed" | grep -oE "[0-9]+" | head -1)
            fi
            # Extract error count (pytest)
            if echo "$summary" | grep -q "error"; then
                errors=$(echo "$summary" | grep -oE "[0-9]+ errors?" | grep -oE "[0-9]+" | head -1)
            fi
        else
            local test_summary=$(printf '%s\n' "$clean_log" | grep -E "^[[:space:]]*Tests[:[:space:]]+[0-9]+.*(passed|failed)" | tail -1)
            if [ -n "$test_summary" ]; then
                if echo "$test_summary" | grep -q "passed"; then
                    passed=$(echo "$test_summary" | grep -oE "[0-9]+[[:space:]]+passed" | grep -oE "[0-9]+" | head -1)
                fi
                if echo "$test_summary" | grep -q "failed"; then
                    failed=$(echo "$test_summary" | grep -oE "[0-9]+[[:space:]]+failed" | grep -oE "[0-9]+" | head -1)
                fi
            else
                # Fall back to PASS/FAIL counts (Jest/Vitest)
                passed=$(printf '%s\n' "$clean_log" | grep -cE "^[[:space:]]*PASS[[:space:]]" 2>/dev/null || echo 0)
                failed=$(printf '%s\n' "$clean_log" | grep -cE "^[[:space:]]*FAIL[[:space:]]" 2>/dev/null || echo 0)
            fi
        fi
    fi
    
    if [[ ! "$passed" =~ ^[0-9]+$ ]]; then
        passed=0
    fi
    if [[ ! "$failed" =~ ^[0-9]+$ ]]; then
        failed=0
    fi
    if [[ ! "$errors" =~ ^[0-9]+$ ]]; then
        errors=0
    fi

    failed=$((failed + errors))

    echo "$passed $failed"
}

# Function to extract failed test names from log file

extract_failed_test_names() {
    local log_file=$1
    local failed_tests=""
    
    if [ -f "$log_file" ]; then
        # For pytest format, look for FAILED/ERROR lines
        # Example: FAILED tests/test_auth.py::test_login_invalid_credentials - AssertionError
        if grep -q "^FAILED " "$log_file"; then
            failed_tests+=$(grep "^FAILED " "$log_file" | sed 's/^FAILED //' | sed 's/ - .*//')
            failed_tests+=$'\n'
        fi
        if grep -q "^ERROR[[:space:]]\\+tests/" "$log_file"; then
            failed_tests+=$(grep "^ERROR[[:space:]]\\+tests/" "$log_file" | sed -E 's/^ERROR[[:space:]]+//' | sed 's/ - .*//')
            failed_tests+=$'\n'
        fi
        # Also check for the summary section format
        if [ -z "$failed_tests" ] && grep -q "^tests/.*::.*FAILED" "$log_file"; then
            failed_tests=$(grep "::.*FAILED" "$log_file" | awk '{print $1}')
        # For Jest/Vitest format, look for FAIL lines
        # Example: FAIL src/components/Button.test.tsx
        elif [ -z "$failed_tests" ] && grep -qE "^[[:space:]]*FAIL[[:space:]]" "$log_file"; then
            # Extract test files that failed
            failed_files=$(grep -E "^[[:space:]]*FAIL[[:space:]]" "$log_file" | sed -E 's/^[[:space:]]*FAIL[[:space:]]+//' | sed -E 's/[[:space:]]*\\[.*\\]$//' | sed -E 's/[[:space:]]*\\(.*\\)$//')
            
            # For each failed file, extract the specific test names when possible
            while IFS= read -r test_file; do
                [ -z "$test_file" ] && continue
                if [[ "$test_file" == *" > "* ]]; then
                    failed_tests="${failed_tests}${test_file}\n"
                    continue
                fi

                # Find line number of this FAIL entry (best effort)
                line_num=$(grep -n -F "FAIL  $test_file" "$log_file" | head -1 | cut -d: -f1)
                if [ -z "$line_num" ]; then
                    line_num=$(grep -n -F "FAIL $test_file" "$log_file" | head -1 | cut -d: -f1)
                fi
                
                if [ -n "$line_num" ]; then
                    # Extract failed test names (marked with ✕) after this FAIL line
                    # Look for the next 20 lines or until we hit another FAIL/PASS line
                    failed_test_names=$(tail -n +$((line_num + 1)) "$log_file" | head -20 | grep "✕" | sed 's/^[[:space:]]*✕[[:space:]]*//' | sed 's/ ([0-9.]* ms)$//')
                    
                    if [ -n "$failed_test_names" ]; then
                        while IFS= read -r test_name; do
                            [ -n "$test_name" ] && failed_tests="${failed_tests}${test_file}::${test_name}\n"
                        done <<< "$failed_test_names"
                    else
                        failed_tests="${failed_tests}${test_file}\n"
                    fi
                else
                    failed_tests="${failed_tests}${test_file}\n"
                fi
            done <<< "$failed_files"
            
            failed_tests=$(echo -e "$failed_tests" | grep -v '^$' | sort | uniq)
        fi
    fi

    if [ -n "$failed_tests" ]; then
        failed_tests=$(echo -e "$failed_tests" | grep -v '^$' | sort | uniq)
    fi

    echo "$failed_tests"
}

# Function to extract error details from pytest log

extract_pytest_errors() {
    local log_file=$1
    local tree_name=$2
    
    if [ ! -f "$log_file" ]; then
        return
    fi
    
    # Debug logging
    if [ "$DEBUG_VERBOSE" = true ]; then
        local debug_file="${log_file%.log}_pytest_debug.log"
        echo "=== DEBUG: extract_pytest_errors for $tree_name ===" > "$debug_file"
        echo "Log file: $log_file" >> "$debug_file"
        echo -e "\n=== Looking for FAILURES section ===" >> "$debug_file"
    fi
    
    # First pass: collect mapping of test headers to full paths
    local -A test_header_to_path=()
    local in_summary=false
    
    if [ "$DEBUG_VERBOSE" = true ]; then
        echo -e "\n=== Building test name mapping ===" >> "$debug_file"
    fi
    
    while IFS= read -r line; do
        if [[ "$line" =~ =+[[:space:]]*short[[:space:]]+test[[:space:]]+summary[[:space:]]+info[[:space:]]*=+ ]]; then
            in_summary=true
            if [ "$DEBUG_VERBOSE" = true ]; then
                echo "Found short test summary section" >> "$debug_file"
            fi
        elif [ "$in_summary" = true ] && [[ "$line" =~ ^FAILED[[:space:]]+(.*)[[:space:]]-[[:space:]] ]]; then
            local full_path="${BASH_REMATCH[1]:-}"
            # Extract just the test name part for mapping
            if [[ "$full_path" =~ ::([^:]+)$ ]]; then
                local test_name="${BASH_REMATCH[1]:-}"
                test_header_to_path["$test_name"]="$full_path"
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Mapped: $test_name -> $full_path" >> "$debug_file"
                fi
            fi
            if [[ "$full_path" =~ ::([^:]+)::([^:]+)$ ]]; then
                local class_method="${BASH_REMATCH[1]:-}.${BASH_REMATCH[2]:-}"
                test_header_to_path["$class_method"]="$full_path"
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Mapped: $class_method -> $full_path" >> "$debug_file"
                fi
            fi
            if [[ "$full_path" =~ ^tests/[^[:space:]]+$ ]]; then
                test_header_to_path["$full_path"]="$full_path"
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Mapped: $full_path -> $full_path" >> "$debug_file"
                fi
            fi
        elif [ "$in_summary" = true ] && [[ "$line" =~ ^ERROR[[:space:]]+(.*)$ ]]; then
            local full_path="${BASH_REMATCH[1]:-}"
            if [[ "$full_path" =~ ::([^:]+)$ ]]; then
                local test_name="${BASH_REMATCH[1]:-}"
                test_header_to_path["$test_name"]="$full_path"
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Mapped: $test_name -> $full_path" >> "$debug_file"
                fi
            fi
            if [[ "$full_path" =~ ::([^:]+)::([^:]+)$ ]]; then
                local class_method="${BASH_REMATCH[1]:-}.${BASH_REMATCH[2]:-}"
                test_header_to_path["$class_method"]="$full_path"
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Mapped: $class_method -> $full_path" >> "$debug_file"
                fi
            fi
            if [[ "$full_path" =~ ^tests/[^[:space:]]+$ ]]; then
                test_header_to_path["$full_path"]="$full_path"
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Mapped: $full_path -> $full_path" >> "$debug_file"
                fi
            fi
        fi
    done < "$log_file"
    
    # Second pass: extract errors
    local in_failures_section=false
    local in_errors_section=false
    local current_test=""
    local current_test_full=""
    local in_test_block=false
    local error_message=""
    local capture_mode=""
    local line_count=0
    local capturing_error=false
    
    while IFS= read -r line; do
        ((line_count++))
        
        # Check for ERRORS/FAILURES sections
        if [[ "$line" =~ =+[[:space:]]*ERRORS[[:space:]]*=+ ]]; then
            if [ "$in_failures_section" = true ] || [ "$in_errors_section" = true ]; then
                if [ -n "$current_test" ] && [ -n "$error_message" ]; then
                    local full_path="${test_header_to_path[$current_test]:-}"
                    if [ -n "$full_path" ]; then
                        local key="${tree_name}:${full_path}"
                        backend_test_errors["$key"]="$error_message"
                    else
                        if [ -n "${backend_failed_tests[$tree_name]:-}" ]; then
                            while IFS= read -r failed_test; do
                                if [[ "$failed_test" =~ $current_test ]] || [[ "$failed_test" =~ ::$current_test$ ]]; then
                                    full_path="$failed_test"
                                    break
                                fi
                            done <<< "${backend_failed_tests[$tree_name]}"
                        fi
                        if [ -n "$full_path" ]; then
                            local key="${tree_name}:${full_path}"
                            backend_test_errors["$key"]="$error_message"
                        else
                            local key="${tree_name}:${current_test}"
                            backend_test_errors["$key"]="$error_message"
                        fi
                    fi
                fi
            fi
            in_errors_section=true
            in_failures_section=false
            in_test_block=false
            capturing_error=false
            current_test=""
            error_message=""
            if [ "$DEBUG_VERBOSE" = true ]; then
                echo "Line $line_count: Found ERRORS section" >> "$debug_file"
            fi
            continue
        elif [[ "$line" =~ =+[[:space:]]*FAILURES[[:space:]]*=+ ]]; then
            if [ "$in_errors_section" = true ]; then
                if [ -n "$current_test" ] && [ -n "$error_message" ]; then
                    local full_path="${test_header_to_path[$current_test]:-}"
                    if [ -n "$full_path" ]; then
                        local key="${tree_name}:${full_path}"
                        backend_test_errors["$key"]="$error_message"
                    else
                        if [ -n "${backend_failed_tests[$tree_name]:-}" ]; then
                            while IFS= read -r failed_test; do
                                if [[ "$failed_test" =~ $current_test ]] || [[ "$failed_test" =~ ::$current_test$ ]]; then
                                    full_path="$failed_test"
                                    break
                                fi
                            done <<< "${backend_failed_tests[$tree_name]}"
                        fi
                        if [ -n "$full_path" ]; then
                            local key="${tree_name}:${full_path}"
                            backend_test_errors["$key"]="$error_message"
                        else
                            local key="${tree_name}:${current_test}"
                            backend_test_errors["$key"]="$error_message"
                        fi
                    fi
                fi
            fi
            in_failures_section=true
            in_errors_section=false
            in_test_block=false
            capturing_error=false
            current_test=""
            error_message=""
            if [ "$DEBUG_VERBOSE" = true ]; then
                echo "Line $line_count: Found FAILURES section" >> "$debug_file"
            fi
            continue
        elif [[ "$line" =~ =+[[:space:]]*(warnings|short)[[:space:]]*(summary|test)[[:space:]]*(info)?[[:space:]]*=+ ]]; then
            if [ "$in_failures_section" = true ] || [ "$in_errors_section" = true ]; then
                # Save last test if exists
                if [ -n "$current_test" ] && [ -n "$error_message" ]; then
                    # Look up the full path from our mapping
                    local full_path="${test_header_to_path[$current_test]:-}"
                    
                    if [ -n "$full_path" ]; then
                        local key="${tree_name}:${full_path}"
                        backend_test_errors["$key"]="$error_message"
                    else
                        # Fallback: try to find in failed tests list
                        if [ -n "${backend_failed_tests[$tree_name]:-}" ]; then
                            while IFS= read -r failed_test; do
                                if [[ "$failed_test" =~ $current_test ]] || [[ "$failed_test" =~ ::$current_test$ ]]; then
                                    full_path="$failed_test"
                                    break
                                fi
                            done <<< "${backend_failed_tests[$tree_name]}"
                        fi
                        
                        if [ -n "$full_path" ]; then
                            local key="${tree_name}:${full_path}"
                            backend_test_errors["$key"]="$error_message"
                        else
                            # Use the header as key if we can't find the full path
                            local key="${tree_name}:${current_test}"
                            backend_test_errors["$key"]="$error_message"
                        fi
                    fi
                    
                    if [ "$DEBUG_VERBOSE" = true ]; then
                        echo "Stored final error for: ${full_path:-$current_test}" >> "$debug_file"
                    fi
                fi
                in_failures_section=false
                in_errors_section=false
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Line $line_count: End of FAILURES section" >> "$debug_file"
                fi
            fi
        fi
        
        if [ "$in_failures_section" = true ] || [ "$in_errors_section" = true ]; then
            # Check if this is a test name line (starts and ends with underscores)
            # Format: ________________ test_name ________________ or
            #         ________________ ClassName.test_method ________________
            header_test=""
            if [ "$in_errors_section" = true ] && [[ "$line" =~ ^_+[[:space:]]+ERROR[[:space:]]+at[[:space:]]+(setup|teardown)[[:space:]]+of[[:space:]]+(.+)[[:space:]]+_+$ ]]; then
                header_test="${BASH_REMATCH[2]:-}"
            elif [[ "$line" =~ ^_+[[:space:]]+(.+)[[:space:]]+_+$ ]]; then
                header_test="${BASH_REMATCH[1]:-}"
            fi

            if [ -n "$header_test" ]; then
                if [[ "$header_test" =~ ^ERROR[[:space:]]+collecting[[:space:]]+(tests/[^[:space:]]+) ]]; then
                    header_test="${BASH_REMATCH[1]:-}"
                fi
                # Save previous test if exists
                if [ -n "$current_test" ] && [ -n "$error_message" ]; then
                    # Look up the full path from our mapping
                    local full_path="${test_header_to_path[$current_test]:-}"
                    
                    if [ -n "$full_path" ]; then
                        local key="${tree_name}:${full_path}"
                        backend_test_errors["$key"]="$error_message"
                    else
                        # Fallback: try to find in failed tests list
                        if [ -n "${backend_failed_tests[$tree_name]:-}" ]; then
                            while IFS= read -r failed_test; do
                                if [[ "$failed_test" =~ $current_test ]] || [[ "$failed_test" =~ ::$current_test$ ]]; then
                                    full_path="$failed_test"
                                    break
                                fi
                            done <<< "${backend_failed_tests[$tree_name]}"
                        fi
                        
                        if [ -n "$full_path" ]; then
                            local key="${tree_name}:${full_path}"
                            backend_test_errors["$key"]="$error_message"
                        else
                            # Use the header as key if we can't find the full path
                            local key="${tree_name}:${current_test}"
                            backend_test_errors["$key"]="$error_message"
                        fi
                    fi
                    
                    if [ "$DEBUG_VERBOSE" = true ]; then
                        echo "Stored error for: ${full_path:-$current_test}" >> "$debug_file"
                        echo "Error message: $error_message" >> "$debug_file"
                    fi
                fi
                
                # Extract new test name
                current_test="$header_test"
                error_message=""
                in_test_block=true
                capturing_error=false
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Line $line_count: Found test header: $current_test" >> "$debug_file"
                fi
                
                # If test header is empty, mark it for later resolution
                if [ -z "$current_test" ] || [[ "$current_test" =~ ^[[:space:]]*$ ]]; then
                    current_test="__empty_header__"
                    capturing_error=true  # Start capturing immediately for empty headers
                fi
            elif [ "$in_test_block" = true ]; then
                # For empty headers, try to extract test name from context
                if [ "$current_test" = "__empty_header__" ]; then
                    if [[ "$line" =~ ^[[:space:]]*async[[:space:]]+def[[:space:]]+([a-zA-Z_][a-zA-Z0-9_]*)\( ]]; then
                        current_test="${BASH_REMATCH[1]:-}"
                        if [ "$DEBUG_VERBOSE" = true ]; then
                            echo "Line $line_count: Found test name from async def: $current_test" >> "$debug_file"
                        fi
                    elif [[ "$line" =~ ^[[:space:]]*def[[:space:]]+([a-zA-Z_][a-zA-Z0-9_]*)\( ]]; then
                        current_test="${BASH_REMATCH[1]:-}"
                        if [ "$DEBUG_VERBOSE" = true ]; then
                            echo "Line $line_count: Found test name from def: $current_test" >> "$debug_file"
                        fi
                    fi
                fi
                
                # Skip empty lines and test setup lines
                if [[ "$line" =~ ^[[:space:]]*$ ]]; then
                    if [ "$capturing_error" = true ] && [ -n "$error_message" ]; then
                        # Empty line after error, might be end of error block
                        capturing_error=false
                    fi
                    continue
                elif [[ "$line" =~ ^self[[:space:]]*= ]] || [[ "$line" =~ ^[[:space:]]+@pytest ]]; then
                    # Skip test setup and definition lines
                    continue
                elif [[ "$line" =~ ^\>[[:space:]]+(.*) ]]; then
                    # Line with > indicates the failed line
                    capturing_error=true
                    local detail="${BASH_REMATCH[1]:-}"
                    error_message="${error_message}      > ${detail}
"
                    if [ "$DEBUG_VERBOSE" = true ]; then
                        echo "Line $line_count: Captured failed line: $detail" >> "$debug_file"
                    fi
                elif [[ "$line" =~ ^E[[:space:]]+(.*) ]]; then
                    # E indicates error details
                    capturing_error=true
                    local detail="${BASH_REMATCH[1]:-}"
                    error_message="${error_message}      ${detail}
"
                    if [ "$DEBUG_VERBOSE" = true ]; then
                        echo "Line $line_count: Captured error detail: $detail" >> "$debug_file"
                    fi
                elif [[ "$line" =~ ^(tests/.+\.py:[0-9]+:) ]] && [ "$capturing_error" = true ]; then
                    # File location line
                    error_message="${error_message}      ${line}
"
                    if [ "$DEBUG_VERBOSE" = true ]; then
                        echo "Line $line_count: Captured location: $line" >> "$debug_file"
                    fi
                elif [[ "$line" =~ ^[=_]{3,}[[:space:]]*$ ]]; then
                    if [ "$capturing_error" = true ] && [ -n "$error_message" ]; then
                        error_message="${error_message}      ${line}
"
                    fi
                    continue
                fi
            fi
        fi
        
        # Also check for inline FAILED lines in short summary
        if [[ "$line" =~ ^FAILED[[:space:]]+(.*)[[:space:]]-[[:space:]]+(.*) ]]; then
            local test_name="${BASH_REMATCH[1]:-}"
            local error_msg="${BASH_REMATCH[2]:-}"
            
            # Only store if we don't already have this test
            local key="${tree_name}:${test_name}"
            if [ -z "${backend_test_errors[$key]:-}" ]; then
                # Try to extract more meaningful error message
                if [[ "$error_msg" =~ AssertionError:?[[:space:]]*(.*) ]]; then
                    error_msg="${BASH_REMATCH[1]:-}"
                    if [ -z "$error_msg" ] || [ "$error_msg" = "assert" ]; then
                        error_msg="AssertionError"
                    fi
                elif [ "$error_msg" = "..." ]; then
                    # Default message when pytest truncates
                    error_msg="Test failed (see full output above)"
                fi
                backend_test_errors["$key"]="      ${error_msg}"
                if [ "$DEBUG_VERBOSE" = true ]; then
                    echo "Line $line_count: Found FAILED line for: $test_name with error: $error_msg" >> "$debug_file"
                fi
            fi
        fi
    done < "$log_file"
    
    # Save last test if exists
    if [ "$in_failures_section" = true ] && [ -n "$current_test" ] && [ -n "$error_message" ]; then
        # Look up the full path from our mapping
        local full_path="${test_header_to_path[$current_test]:-}"
        
        if [ -n "$full_path" ]; then
            local key="${tree_name}:${full_path}"
            backend_test_errors["$key"]="$error_message"
        else
            # Fallback: try to find in failed tests list
            if [ -n "${backend_failed_tests[$tree_name]:-}" ]; then
                while IFS= read -r failed_test; do
                    if [[ "$failed_test" =~ $current_test ]] || [[ "$failed_test" =~ ::$current_test$ ]]; then
                        full_path="$failed_test"
                        break
                    fi
                done <<< "${backend_failed_tests[$tree_name]}"
            fi
            
            if [ -n "$full_path" ]; then
                local key="${tree_name}:${full_path}"
                backend_test_errors["$key"]="$error_message"
            else
                # Use the header as key if we can't find the full path
                local key="${tree_name}:${current_test}"
                backend_test_errors["$key"]="$error_message"
            fi
        fi
        
        if [ "$DEBUG_VERBOSE" = true ]; then
            echo "Stored final error for: ${full_path:-$current_test}" >> "$debug_file"
        fi
    fi
    
    if [ "$DEBUG_VERBOSE" = true ]; then
        echo -e "\n=== Total errors stored: ${#backend_test_errors[@]} ===" >> "$debug_file"
        for key in "${!backend_test_errors[@]}"; do
            echo "Key: $key" >> "$debug_file"
            echo "Error: ${backend_test_errors[$key]}" >> "$debug_file"
            echo "---" >> "$debug_file"
        done
    fi
}

# Function to extract error details from Jest/Vitest npm test log

extract_jest_errors() {
    local log_file=$1
    local tree_name=$2
    
    if [ ! -f "$log_file" ]; then
        return
    fi
    
    # Parse the log file once and store errors
    local current_file=""
    local in_error_block=false
    local error_message=""
    local capture_lines=0
    local pending_error=false
    
    while IFS= read -r line; do
        # Check for FAIL line
        if [[ "$line" =~ ^[[:space:]]*FAIL[[:space:]]+(.*) ]]; then
            # Save previous error if exists
            if [ -n "$current_file" ] && [ -n "$error_message" ]; then
                local key="${tree_name}:${current_file}"
                frontend_test_errors["$key"]="$error_message"
            fi
            
            # Extract filename (remove timing info in parentheses)
            current_file=$(echo "${BASH_REMATCH[1]}" | sed -E 's/[[:space:]]*\\[.*\\]$//' | sed -E 's/[[:space:]]*\\(.*\\)$//')
            error_message=""
            in_error_block=false
            pending_error=true
        elif [[ "$line" =~ ^[[:space:]]*●[[:space:]]+(.*) ]]; then
            # Found error marker
            in_error_block=true
            error_message="${BASH_REMATCH[1]}"
            capture_lines=0
            pending_error=false
        elif [ "$pending_error" = true ] && [ -z "$error_message" ] && [[ "$line" =~ ^[[:space:]]*[^[:space:]] ]]; then
            # Vitest failure message follows FAIL line
            in_error_block=true
            error_message="$line"
            capture_lines=0
            pending_error=false
        elif [ "$in_error_block" = true ] && [ $capture_lines -lt 20 ]; then
            # Capture error details
            if [[ "$line" =~ ^[[:space:]]*$ ]]; then
                # Empty line
                if [ $capture_lines -gt 0 ]; then
                    ((capture_lines++))
                fi
            elif [[ "$line" =~ ^[[:space:]]*Details: ]] || [[ "$line" =~ ^[[:space:]]*at[[:space:]] ]] || [[ "$line" =~ ^[[:space:]]*\> ]] || [[ "$line" =~ ^[[:space:]]*\| ]] || [[ "$line" =~ ^[[:space:]]*[0-9]+[[:space:]]*\| ]]; then
                # Important error details
                error_message="${error_message}
      ${line}"
                ((capture_lines++))
            elif [[ "$line" =~ SyntaxError: ]] || [[ "$line" =~ TypeError: ]] || [[ "$line" =~ ReferenceError: ]] || [[ "$line" =~ Error: ]] || [[ "$line" =~ Cannot ]] || [[ "$line" =~ Unexpected ]] || [[ "$line" =~ Expected: ]] || [[ "$line" =~ Received: ]]; then
                # Error messages
                error_message="${error_message}
      ${line}"
                ((capture_lines++))
            elif [[ "$line" =~ ^PASS[[:space:]]|^FAIL[[:space:]]|^Test[[:space:]]Suites: ]]; then
                # End of error block
                in_error_block=false
            fi
        fi
    done < "$log_file"
    
    # Save last error if exists
    if [ -n "$current_file" ] && [ -n "$error_message" ]; then
        local key="${tree_name}:${current_file}"
        frontend_test_errors["$key"]="$error_message"
    fi
}

# Function to extract frontend failed tests and error snippets in one pass

extract_frontend_failures() {
    local log_file=$1
    local tree_name=$2
    local capture_errors=${3:-false}

    if [ ! -f "$log_file" ]; then
        return 0
    fi

    local list_file
    local errors_file
    list_file=$(mktemp "${TMPDIR:-/tmp}/envctl_frontend_failed_list_${tree_name// /_}.XXXXXX")
    errors_file=$(mktemp "${TMPDIR:-/tmp}/envctl_frontend_failed_errors_${tree_name// /_}.XXXXXX")

    awk -v list="$list_file" -v err="$errors_file" -v capture="$capture_errors" '
        BEGIN {
            sep = sprintf("%c", 31)
            nl = sprintf("%c", 30)
        }
        function flush_entry() {
            if (current != "") {
                print current >> list
                if (capture == "true" && err_msg != "") {
                    err_out = err_msg
                    gsub(/\n/, nl, err_out)
                    print current sep err_out >> err
                }
            }
            current = ""
            err_msg = ""
            err_lines = 0
        }
        function flush_pending(with_error,    i) {
            for (i = 1; i <= pending_count; i++) {
                print pending[i] >> list
                if (capture == "true" && with_error != "") {
                    err_out = with_error
                    gsub(/\n/, nl, err_out)
                    print pending[i] sep err_out >> err
                }
            }
            pending_count = 0
            suite_err = ""
            suite_err_lines = 0
            suite_capture = 0
        }
        /Failed Suites/ {
            flush_entry()
            suite_block = 1
            pending_count = 0
            suite_err = ""
            suite_err_lines = 0
            suite_capture = 0
            next
        }
        {
            if (suite_block == 1) {
                if ($0 ~ /^[[:space:]]*FAIL[[:space:]]+/) {
                    line = $0
                    sub(/^[[:space:]]*FAIL[[:space:]]+/, "", line)
                    pending[++pending_count] = line
                    next
                }
                if (suite_capture == 1) {
                    if ($0 ~ /^[^[:alnum:]]{5,}/ || $0 ~ /^[[:space:]]*Failed Tests/ || $0 ~ /^[[:space:]]*Test (Files|Suites|Suite|Tests):/) {
                        flush_pending(suite_err)
                        suite_block = 0
                        # fall through to handle this line normally
                    } else {
                        if (suite_err_lines < 18) {
                            suite_err = suite_err "\n" $0
                            suite_err_lines++
                        }
                        next
                    }
                }
                if (suite_block == 1 && capture == "true" && suite_err == "" && $0 ~ /(AssertionError:|TypeError:|ReferenceError:|SyntaxError:|Error:|Expected:|Received:)/) {
                    suite_err = $0
                    suite_capture = 1
                    suite_err_lines = 0
                    next
                }
                if (suite_block == 1 && ($0 ~ /^[^[:alnum:]]{5,}/ || $0 ~ /^[[:space:]]*Failed Tests/ || $0 ~ /^[[:space:]]*Test (Files|Suites|Suite|Tests):/)) {
                    flush_pending("")
                    suite_block = 0
                    # fall through to handle this line normally
                } else if (suite_block == 1) {
                    next
                }
            }
        }
        /^[[:space:]]*FAIL[[:space:]]+/ {
            flush_entry()
            current = $0
            sub(/^[[:space:]]*FAIL[[:space:]]+/, "", current)
            next
        }
        {
            if (current == "") next
            if ($0 ~ /^[[:space:]]*(PASS|FAIL)[[:space:]]/ || $0 ~ /^[[:space:]]*Test (Files|Suites|Suite|Tests):/) {
                flush_entry()
                next
            }
            if (capture == "true") {
                if (err_msg == "" && $0 ~ /(AssertionError:|TypeError:|ReferenceError:|SyntaxError:|Error:|Expected:|Received:)/) {
                    err_msg = $0
                    next
                }
                if (err_msg != "" && err_lines < 18) {
                    err_msg = err_msg "\n" $0
                    err_lines++
                }
            }
        }
        END {
            if (suite_block == 1 && pending_count > 0) {
                flush_pending(suite_err)
            }
            flush_entry()
        }
    ' "$log_file"

    if [ -s "$list_file" ]; then
        frontend_failed_tests["$tree_name"]=$(sort -u "$list_file")
    fi

    if [ "$capture_errors" = true ] && [ -s "$errors_file" ]; then
        while IFS=$'\037' read -r test_line err_msg; do
            [ -n "$test_line" ] || continue
            err_msg="${err_msg//$'\036'/$'\n'}"
            frontend_test_errors["${tree_name}:${test_line}"]="$err_msg"
        done < "$errors_file"
    fi

    rm -f "$list_file" "$errors_file"
}


strip_ansi() {
    sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g'
}


error_hash() {
    printf "%s" "$1" | cksum | awk '{print $1 "-" $2}'
}


count_list_entries() {
    local list="$1"
    if [ -z "$list" ]; then
        echo 0
        return 0
    fi
    printf "%s\n" "$list" | sed '/^$/d' | wc -l | tr -d ' '
}


resolve_backend_error_text() {
    local project="$1"
    local failed_test="$2"
    local error_key="${project}:${failed_test}"
    local error_text="${backend_test_errors[$error_key]:-}"

    if [ -n "$error_text" ]; then
        printf "%s" "$error_text"
        return 0
    fi

    local header_key=""
    if [[ "$failed_test" == *"::"* ]]; then
        local test_name="${failed_test##*::}"
        local remainder="${failed_test%::*}"
        if [[ "$remainder" == *"::"* ]]; then
            local class_name="${remainder##*::}"
            header_key="${class_name}.${test_name}"
        else
            header_key="$test_name"
        fi
    fi

    if [ -n "$header_key" ]; then
        error_key="${project}:${header_key}"
        error_text="${backend_test_errors[$error_key]:-}"
    fi

    printf "%s" "$error_text"
}


resolve_frontend_error_text() {
    local project="$1"
    local failed_test="$2"
    local error_key="${project}:${failed_test}"
    local error_text="${frontend_test_errors[$error_key]:-}"

    if [ -n "$error_text" ]; then
        printf "%s" "$error_text"
        return 0
    fi

    if [[ "$failed_test" == *"::"* ]]; then
        error_key="${project}:${failed_test%%::*}"
        error_text="${frontend_test_errors[$error_key]:-}"
    fi

    printf "%s" "$error_text"
}


write_grouped_failures() {
    local type="$1"
    local project="$2"
    local failed_list="$3"

    declare -A group_errors=()
    declare -A group_tests=()
    declare -a group_order=()
    declare -A group_test_params=()
    declare -A test_error_texts=()

    while IFS= read -r failed_test; do
        [ -n "$failed_test" ] || continue

        local error_text=""
        if [ "$type" = "backend" ]; then
            error_text=$(resolve_backend_error_text "$project" "$failed_test")
        else
            error_text=$(resolve_frontend_error_text "$project" "$failed_test")
        fi

        if [ -n "$error_text" ]; then
            error_text=$(printf "%s\n" "$error_text" | strip_ansi)
        fi

        if [ -z "$error_text" ]; then
            error_text="(No extracted error details; see log)"
        fi

        test_error_texts["$failed_test"]="$error_text"

        local core_error="$error_text"
        local params_text=""
        if [ "$type" = "backend" ]; then
            local core_lines=()
            while IFS= read -r line; do
                if [[ "$line" =~ \[parameters: ]] || [[ "$line" =~ ^[[:space:]]*parameters: ]]; then
                    params_text+="${line}"$'\n'
                    continue
                fi
                core_lines+=("$line")
            done <<< "$error_text"
            core_error=$(printf "%s\n" "${core_lines[@]}")
            if [ -z "$core_error" ]; then
                core_error="$error_text"
            fi
        fi

        local base_key
        base_key=$(error_hash "$core_error")
        local key="$base_key"

        if [ -n "${group_errors[$key]+x}" ] && [ "${group_errors[$key]}" != "$core_error" ]; then
            local suffix=2
            while [ -n "${group_errors[${base_key}_${suffix}]+x}" ] && [ "${group_errors[${base_key}_${suffix}]}" != "$core_error" ]; do
                suffix=$((suffix + 1))
            done
            key="${base_key}_${suffix}"
        fi

        if [ -z "${group_errors[$key]+x}" ]; then
            group_errors[$key]="$core_error"
            group_tests[$key]="$failed_test"
            group_order+=("$key")
        else
            group_tests[$key]="${group_tests[$key]}"$'\n'"$failed_test"
        fi

        if [ "$type" = "backend" ] && [ -n "$params_text" ]; then
            group_test_params["${key}|${failed_test}"]="$params_text"
        fi
    done <<< "$failed_list"

    for key in "${group_order[@]}"; do
        local tests_block="${group_tests[$key]}"
        local test_count
        test_count=$(printf "%s\n" "$tests_block" | sed '/^$/d' | wc -l | tr -d ' ')

        if [ "$test_count" -le 1 ]; then
            local single_test
            single_test=$(printf "%s" "$tests_block" | head -n 1)
            echo "  - ${single_test}"
            printf "%s\n" "${test_error_texts[$single_test]}" | sed 's/^/      /'
        else
            echo "  - Shared error for ${test_count} tests:"
            if [ "$type" = "backend" ]; then
                printf "%s\n" "${group_errors[$key]}" | sed 's/^/      /'
                echo "      Tests:"
                while IFS= read -r test_name; do
                    [ -n "$test_name" ] || continue
                    echo "        - ${test_name}"
                    if [ -n "${group_test_params[${key}|${test_name}]:-}" ]; then
                        printf "%s\n" "${group_test_params[${key}|${test_name}]}" | sed 's/^/          /'
                    fi
                done <<< "$tests_block"
            else
                printf "%s\n" "$tests_block" | sed 's/^/      - /'
                printf "%s\n" "${group_errors[$key]}" | sed 's/^/      /'
            fi
        fi
        echo ""
    done
}

# Function to show progress bar

format_duration() {
    local seconds=$1
    local minutes=$((seconds / 60))
    local remaining_seconds=$((seconds % 60))
    
    if [ $minutes -gt 0 ]; then
        printf "%dm %ds" $minutes $remaining_seconds
    else
        printf "%ds" $seconds
    fi
}
