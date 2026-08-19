"""Repository port and fixture adapter for the Equipment bounded context."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Iterable, Mapping, Protocol, cast

from .equipment_domain import EquipmentCurrentState, EquipmentMaster, next_state_version
from .equipment_exception import EquipmentStateVersionConflictError


class EquipmentRepository(Protocol):
    """Persistence-neutral contract consumed by :class:`EquipmentService`."""

    def list_masters(self, *, project_id: str) -> list[EquipmentMaster]: ...

    def get_master(self, *, project_id: str, equipment_id: str) -> EquipmentMaster | None: ...

    def get_current_state(
        self, *, project_id: str, equipment_id: str
    ) -> EquipmentCurrentState | None: ...

    def compare_and_set_state(
        self,
        *,
        project_id: str,
        equipment_id: str,
        expected_state_version: int | None,
        state: Mapping[str, Any],
    ) -> EquipmentCurrentState: ...


class FixtureEquipmentRepository:
    """Fixture-backed adapter for the existing manufacturing showcase host.

    Current-state storage and compare-and-set locking are intentionally
    process-local and non-durable. They are sufficient for the single-process
    showcase adapter only; distributed/durable Equipment state persistence is
    owned by the follow-up Maintenance persistence work (#59).

    Master fixtures are validated eagerly at composition time so malformed
    canonical fixture data fails fast instead of producing partially usable
    Equipment master state.
    """

    def __init__(
        self,
        masters: Iterable[tuple[str, Mapping[str, Any]]],
    ) -> None:
        self._masters: dict[tuple[str, str], EquipmentMaster] = {}
        for project_id, payload in masters:
            master = EquipmentMaster.from_mapping(payload)
            self._masters[(project_id, master.equipment_id)] = master
        self._states: dict[tuple[str, str], EquipmentCurrentState] = {}
        self._state_lock = RLock()

    def list_masters(self, *, project_id: str) -> list[EquipmentMaster]:
        return sorted(
            (
                master
                for (candidate_project_id, _), master in self._masters.items()
                if candidate_project_id == project_id
            ),
            key=lambda master: master.equipment_id,
        )

    def get_master(self, *, project_id: str, equipment_id: str) -> EquipmentMaster | None:
        return self._masters.get((project_id, equipment_id))

    def get_current_state(
        self, *, project_id: str, equipment_id: str
    ) -> EquipmentCurrentState | None:
        with self._state_lock:
            snapshot = self._states.get((project_id, equipment_id))
            if snapshot is None:
                return None
            return EquipmentCurrentState(
                equipment_id=snapshot.equipment_id,
                state_version=snapshot.state_version,
                state=deepcopy(dict(snapshot.state)),
            )

    def compare_and_set_state(
        self,
        *,
        project_id: str,
        equipment_id: str,
        expected_state_version: int | None,
        state: Mapping[str, Any],
    ) -> EquipmentCurrentState:
        key = (project_id, equipment_id)
        with self._state_lock:
            current = self._states.get(key)
            actual_version = None if current is None else current.state_version
            if actual_version != expected_state_version:
                raise EquipmentStateVersionConflictError(
                    expected=expected_state_version,
                    actual=actual_version,
                )
            self._states[key] = EquipmentCurrentState(
                equipment_id=equipment_id,
                state_version=next_state_version(actual_version),
                state=deepcopy(dict(state)),
            )
            return cast(
                EquipmentCurrentState,
                self.get_current_state(project_id=project_id, equipment_id=equipment_id),
            )
