from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import systems.verify_architecture as verifier


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class BackendDomainFirstArchitectureTests(unittest.TestCase):
    def _run_ratchet(self, root: Path) -> list[str]:
        systems = root / "systems"
        with patch.object(verifier, "ROOT", root), patch.object(verifier, "SYSTEMS", systems):
            errors: list[str] = []
            verifier.check_backend_domain_first_ratchet(errors)
        return errors

    def test_composition_root_may_import_fastapi_and_infra(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root / "systems/backend/app/main.py",
                "from fastapi import FastAPI\nfrom app.infra.db import connection\n",
            )
            _write(
                root / "systems/backend/app/dependencies.py",
                "from app.infra.storage import object_storage\n",
            )

            errors = self._run_ratchet(root)

        self.assertEqual(errors, [])

    def test_composition_root_still_obeys_legacy_import_ratchet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root / "systems/backend/app/health.py",
                "from ontology_dashboard.health import readiness\n",
            )

            errors = self._run_ratchet(root)

        self.assertTrue(
            any("new canonical-to-legacy Backend import is forbidden" in error for error in errors),
            errors,
        )

    def test_domain_relative_import_cannot_bypass_infra_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root / "systems/backend/app/equipment/equipment_service.py",
                "from ..infra.db import connection\n",
            )

            errors = self._run_ratchet(root)

        self.assertTrue(
            any(
                "backend domain imports infra implementation" in error
                and "app.infra.db" in error
                for error in errors
            ),
            errors,
        )

    def test_common_relative_import_cannot_bypass_reverse_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root / "systems/backend/app/common/helper.py",
                "from ..infra import db\n",
            )

            errors = self._run_ratchet(root)

        self.assertTrue(
            any(
                "backend common reverse dependency" in error and "app.infra" in error
                for error in errors
            ),
            errors,
        )

    def test_infra_relative_import_rejects_domain_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root / "systems/backend/app/infra/bridge.py",
                "from ..equipment.equipment_repository import EquipmentRepository\n",
            )

            errors = self._run_ratchet(root)

        self.assertTrue(
            any(
                "backend infra imports domain implementation" in error
                and "app.equipment.equipment_repository" in error
                for error in errors
            ),
            errors,
        )

    def test_multi_alias_relative_import_normalizes_each_module(self) -> None:
        node = ast.parse("from .. import infra as i, common as c\n").body[0]

        modules = verifier._module_names(node, package="app.equipment")

        self.assertEqual(modules, ["app.infra", "app.common"])

    def test_multi_alias_relative_import_cannot_bypass_infra_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root / "systems/backend/app/equipment/equipment_service.py",
                "from .. import infra as i, common as c\n",
            )

            errors = self._run_ratchet(root)

        self.assertTrue(
            any(
                "backend domain imports infra implementation" in error
                and "app.infra" in error
                for error in errors
            ),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
