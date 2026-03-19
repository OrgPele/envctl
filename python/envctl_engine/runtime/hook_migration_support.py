from __future__ import annotations

from typing import Any

from envctl_engine.shared.hooks import migrate_legacy_shell_hooks
from envctl_engine.ui.path_links import render_path_for_terminal


def run_hook_migration(runtime: Any, route: Any) -> int:
    result = migrate_legacy_shell_hooks(runtime.config.base_dir, force=bool(getattr(route, "flags", {}).get("force")))
    if result.error:
        print(result.error)
        if result.starter_stub:
            print("")
            print(f"Starter stub for {result.python_hook_path.name}:")
            print(result.starter_stub, end="" if result.starter_stub.endswith("\n") else "\n")
        return 1 if result.skipped_hooks else 0
    print(f"Wrote {render_path_for_terminal(result.python_hook_path, env=getattr(runtime, 'env', {}))}")
    if result.migrated_hooks:
        print("Migrated hooks: " + ", ".join(result.migrated_hooks))
    return 0
