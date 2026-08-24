"""Regression tests for systems/verify_contract_vectors.py."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from systems.verify_contract_vectors import ContractVectorVerifier, compute_sha256


def test_real_repository_contract_vectors_pass():
    """Verify that the real repository contract vectors and schemas pass all checks."""
    verifier = ContractVectorVerifier()
    result = verifier.verify_all()
    assert result.passed, f"Errors: {[e.format() for e in result.errors]}"
    assert result.schema_count >= 1
    assert result.vector_count >= 1
    assert result.manifest_count >= 2
    assert result.payload_count >= 2
    assert "generator-feature-input-v1" in result.verified_vectors


def _setup_isolated_contracts(tmp_path: Path) -> tuple[Path, ContractVectorVerifier]:
    """Helper to copy real contracts directory to a temporary path for mutation testing."""
    repo_root = Path(__file__).resolve().parents[1]
    src_contracts = repo_root / "contracts"

    dst_contracts = tmp_path / "contracts"
    shutil.copytree(src_contracts, dst_contracts)

    verifier = ContractVectorVerifier(repo_root=tmp_path)
    return dst_contracts, verifier


def test_valid_isolated_contracts_pass(tmp_path: Path):
    _, verifier = _setup_isolated_contracts(tmp_path)
    result = verifier.verify_all()
    assert result.passed


def test_invalid_schema_json_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    bad_schema = contracts_dir / "schemas" / "bad.schema.json"
    bad_schema.write_text("{ invalid json: ", encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Invalid JSON in schema file" in e.message for e in result.errors)


def test_schema_meta_draft_violation_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    bad_schema = contracts_dir / "schemas" / "bad_meta.schema.json"
    bad_schema.write_text(
        json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "invalid_primitive_type",
        }),
        encoding="utf-8",
    )

    result = verifier.verify_all()
    assert not result.passed
    assert any("Schema violates its meta-schema" in e.message for e in result.errors)


def test_duplicate_schema_id_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    # create duplicate id
    existing_schema_path = contracts_dir / "schemas" / "generator-dataset-input-manifest.schema.json"
    existing_schema = json.loads(existing_schema_path.read_text(encoding="utf-8"))
    dup_id = existing_schema["$id"]

    dup_schema = contracts_dir / "schemas" / "duplicate.schema.json"
    dup_schema.write_text(
        json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": dup_id,
            "type": "object",
        }),
        encoding="utf-8",
    )

    result = verifier.verify_all()
    assert not result.passed
    assert any("Duplicate schema $id" in e.message for e in result.errors)


def test_zero_schemas_fails_false_green_protection(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    shutil.rmtree(contracts_dir / "schemas")
    (contracts_dir / "schemas").mkdir()

    result = verifier.verify_all()
    assert not result.passed
    assert any("No JSON schema files found" in e.message for e in result.errors)


def test_zero_test_vectors_fails_false_green_protection(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    shutil.rmtree(contracts_dir / "test-vectors")
    (contracts_dir / "test-vectors").mkdir()

    result = verifier.verify_all()
    assert not result.passed
    assert any("No test vector directories found" in e.message for e in result.errors)


def test_missing_required_expected_file_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    (vdir / "expected" / "summary.json").unlink()

    result = verifier.verify_all()
    assert not result.passed
    assert any("Missing required test vector file" in e.message for e in result.errors)


def test_payload_sha256_mismatch_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    csv_file = vdir / "observation" / "observations.csv"
    csv_file.write_text(csv_file.read_text(encoding="utf-8") + "\n# corrupted row", encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Payload SHA-256 checksum mismatch" in e.message for e in result.errors)


def test_payload_size_mismatch_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    manifest_path = vdir / "observation" / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["size_bytes"] = 99999999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Payload size_bytes mismatch" in e.message for e in result.errors)


def test_payload_parent_directory_traversal_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    manifest_path = vdir / "observation" / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../secret.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Payload path must not traverse parent directories" in e.message for e in result.errors)


def test_payload_absolute_path_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    manifest_path = vdir / "observation" / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "/etc/passwd"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Payload path must not be absolute" in e.message for e in result.errors)


def test_expected_labels_and_row_metadata_length_mismatch_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    labels_file = vdir / "expected" / "labels.json"
    labels = json.loads(labels_file.read_text(encoding="utf-8"))
    labels.append(0)  # extra label
    labels_file.write_text(json.dumps(labels), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Length mismatch between labels and row_metadata" in e.message for e in result.errors)


def test_expected_summary_row_count_mismatch_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    summary_file = vdir / "expected" / "summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    summary["row_count"] = summary["row_count"] + 10
    summary_file.write_text(json.dumps(summary), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("summary.json row_count mismatch" in e.message for e in result.errors)


def test_invalid_label_value_fails(tmp_path: Path):
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    labels_file = vdir / "expected" / "labels.json"
    labels = json.loads(labels_file.read_text(encoding="utf-8"))
    labels[0] = 2  # invalid label
    labels_file.write_text(json.dumps(labels), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Invalid label value" in e.message for e in result.errors)
