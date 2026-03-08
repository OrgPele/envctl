#!/usr/bin/env bash

# Helpers for deploy-production.sh.

deploy_production_print_usage() {
    cat <<'USAGE'
envctl production deployment

Usage:
  ./deploy-production.sh [options]

Options:
  --registry=REGISTRY
  --namespace=NAMESPACE
  --backend-image=NAME
  --frontend-image=NAME
  --skip-build
  --skip-migrate
  --skip-health
  --skip-secrets
  --write-frontend-configs   Create Dockerfile/nginx.conf if missing
  --help, -h
USAGE
}

deploy_production_print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

deploy_production_print_error() {
    echo -e "${RED}✗${NC} $1"
}

deploy_production_print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

deploy_production_require_env() {
    local name=$1
    local value=${!name:-}
    if [ -z "$value" ]; then
        deploy_production_print_error "Missing required env: ${name}"
        exit 1
    fi
}
