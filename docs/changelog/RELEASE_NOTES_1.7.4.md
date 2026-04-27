# envctl 1.7.4

`envctl` 1.7.4 is a hotfix release on top of `1.7.3`. It hardens managed requirement container recovery after a Docker host networking outage leaves envctl-owned containers with stale host-port bindings that are recorded in Docker config but not actually listening on localhost.

## Fixed

- Recreates adopted Redis/PostgreSQL/N8N-style requirement containers when their adopted host port never becomes reachable after the local settle path.
- Resets the effective requirement port back to the newly planned requested port after recreation, avoiding retries that keep probing stale host-port bindings from the broken container.
- Preserves the fast adopt-existing path when an existing container and its published port are healthy.

## Validation

- `./.venv/bin/python -m ruff check python/envctl_engine/requirements/adapter_base.py tests/python/requirements/test_requirements_adapters_real_contracts.py`
- `./.venv/bin/python -m pytest tests/python/requirements/test_requirements_retry.py tests/python/requirements/test_requirements_adapters_real_contracts.py -q`
- `./.venv/bin/python -m pytest tests/python/requirements -q`
- Manual Docker E2E: created an envctl-named Redis container with `--network none` and stale `HostConfig.PortBindings`; verified the local 1.7.4 code recreated it on the requested dynamic port and reached readiness.
