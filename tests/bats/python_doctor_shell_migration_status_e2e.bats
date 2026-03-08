#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
}

@test "doctor reports shell migration status from ledger" {
  run "$BIN" --repo "$REPO_ROOT" --doctor
  [ "$status" -eq 0 ]
  [[ "$output" == *"shell_migration_status:"* ]]
  [[ "$output" == *"shell_ledger_hash:"* ]]
  [[ "$output" == *"shell_unmigrated_count:"* ]]
  [[ "$output" == *"shell_intentional_keep_count:"* ]]
}

@test "doctor strict mode defaults omitted intentional keep budget to zero" {
  run env \
    ENVCTL_RUNTIME_TRUTH_MODE=strict \
    ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED=0 \
    ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP=0 \
    "$BIN" --repo "$REPO_ROOT" --doctor
  [ "$status" -eq 0 ]
  [[ "$output" == *"shell_intentional_keep_budget: 0"* ]]
  [[ "$output" == *"shell_intentional_keep_status: pass"* ]]
}

@test "doctor strict mode defaults full shell budget profile when omitted" {
  run env \
    ENVCTL_RUNTIME_TRUTH_MODE=strict \
    ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED= \
    ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP= \
    ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP= \
    "$BIN" --repo "$REPO_ROOT" --doctor
  [ "$status" -eq 0 ]
  [[ "$output" == *"shell_unmigrated_budget: 0"* ]]
  [[ "$output" == *"shell_partial_keep_budget: 0"* ]]
  [[ "$output" == *"shell_intentional_keep_budget: 0"* ]]
  [[ "$output" == *"shell_prune_phase: cutover"* ]]
}

@test "doctor auto mode defaults full shell budget profile when omitted" {
  run env \
    ENVCTL_RUNTIME_TRUTH_MODE=auto \
    ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED= \
    ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP= \
    ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP= \
    "$BIN" --repo "$REPO_ROOT" --doctor
  [ "$status" -eq 0 ]
  [[ "$output" == *"shell_unmigrated_budget: 0"* ]]
  [[ "$output" == *"shell_partial_keep_budget: 0"* ]]
  [[ "$output" == *"shell_intentional_keep_budget: 0"* ]]
  [[ "$output" == *"shell_prune_phase: cutover"* ]]
}
