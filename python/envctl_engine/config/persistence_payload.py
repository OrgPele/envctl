from __future__ import annotations

from dataclasses import dataclass

from envctl_engine.config.persistence_payload_mapping import hydrate_payload_mapping
from envctl_engine.config.persistence_values import (
    ManagedConfigValues,
    managed_values_from_mapping,
    managed_values_to_mapping,
)


@dataclass(frozen=True, slots=True)
class ConfigPayloadHydrator:
    base_values: ManagedConfigValues | None = None

    def hydrate(self, payload: dict[str, object]) -> ManagedConfigValues:
        mapping = managed_values_to_mapping(self.base_values or managed_values_from_mapping({}))
        return managed_values_from_mapping(hydrate_payload_mapping(payload, mapping))
