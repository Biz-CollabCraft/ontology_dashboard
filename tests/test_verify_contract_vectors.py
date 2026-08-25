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


# ==========================================
# Manifest Schema Fail-Closed Tests
# ==========================================

def test_missing_manifest_schema_fails(tmp_path: Path):
    """Verify that deleting generator-dataset-input-manifest.schema.json fails verification."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    schema_path = contracts_dir / "schemas" / "generator-dataset-input-manifest.schema.json"
    schema_path.unlink()

    result = verifier.verify_all()
    assert not result.passed
    assert any("Required manifest schema not found" in e.message for e in result.errors)


def test_invalid_json_manifest_schema_fails(tmp_path: Path):
    """Verify that malformed JSON in manifest schema fails verification."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    schema_path = contracts_dir / "schemas" / "generator-dataset-input-manifest.schema.json"
    schema_path.write_text("{ unclosed json: ", encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Failed to parse manifest schema JSON" in e.message or "Invalid JSON in schema file" in e.message for e in result.errors)


def test_invalid_meta_manifest_schema_fails(tmp_path: Path):
    """Verify that invalid schema definition in manifest schema fails verification."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    schema_path = contracts_dir / "schemas" / "generator-dataset-input-manifest.schema.json"
    schema_path.write_text(
        json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "not_a_valid_json_schema_type",
        }),
        encoding="utf-8",
    )

    result = verifier.verify_all()
    assert not result.passed
    assert any("Manifest schema definition is invalid" in e.message or "Schema violates its meta-schema" in e.message for e in result.errors)


def test_manifest_missing_manifest_version_fails(tmp_path: Path):
    """Verify that removing manifest_version from dataset manifest fails schema check."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    manifest_path = vdir / "observation" / "dataset_manifest.json"
    m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    del m_data["manifest_version"]
    manifest_path.write_text(json.dumps(m_data), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Manifest schema validation failed" in e.message for e in result.errors)


def test_manifest_missing_dataset_version_fails(tmp_path: Path):
    """Verify that removing dataset_version from dataset manifest fails schema check."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    manifest_path = vdir / "observation" / "dataset_manifest.json"
    m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    del m_data["dataset_version"]
    manifest_path.write_text(json.dumps(m_data), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Manifest schema validation failed" in e.message for e in result.errors)


def test_manifest_file_entry_missing_media_type_fails(tmp_path: Path):
    """Verify that removing media_type from files entry fails schema check."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    manifest_path = vdir / "observation" / "dataset_manifest.json"
    m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    del m_data["files"][0]["media_type"]
    manifest_path.write_text(json.dumps(m_data), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Manifest schema validation failed" in e.message for e in result.errors)


# ==========================================
# Feature Vector request.json Tests
# ==========================================

def test_feature_vector_request_json_syntax_error_fails(tmp_path: Path):
    """Verify that syntax error in request.json fails verification."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    (vdir / "request.json").write_text("{ syntax error: ", encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Invalid JSON in request.json" in e.message for e in result.errors)


def test_feature_vector_request_json_array_fails(tmp_path: Path):
    """Verify that top-level JSON array in request.json fails verification."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    (vdir / "request.json").write_text(json.dumps(["item1", "item2"]), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("request.json top-level must be a JSON object" in e.message for e in result.errors)


def test_feature_vector_request_json_empty_fails(tmp_path: Path):
    """Verify that empty request.json fails verification."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    vdir = contracts_dir / "test-vectors" / "generator-feature-input-v1"
    (vdir / "request.json").write_text("", encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("request.json is empty" in e.message for e in result.errors)


# ==========================================
# Training Vector Fail-Closed Tests
# ==========================================

def test_training_vector_missing_schema_fails(tmp_path: Path):
    """Verify that if a training vector exists without its schema, verification fails fail-closed."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    # create synthetic training vector
    t_vdir = contracts_dir / "test-vectors" / "generator-training-v1"
    t_vdir.mkdir(parents=True, exist_ok=True)
    (t_vdir / "expected").mkdir(parents=True, exist_ok=True)
    (t_vdir / "request.json").write_text(json.dumps({"dataset_id": "ai4i"}), encoding="utf-8")
    (t_vdir / "training-config.json").write_text(json.dumps({"training_config_version": "v1"}), encoding="utf-8")
    (t_vdir / "expected" / "artifact-manifest-required.json").write_text(json.dumps({"model_id": "pdm-lgb"}), encoding="utf-8")
    (t_vdir / "expected" / "split-summary.json").write_text(json.dumps({"train_rows": 10}), encoding="utf-8")

    # If schema is missing
    schema_path = contracts_dir / "schemas" / "generator-training-config.schema.json"
    if schema_path.exists():
        schema_path.unlink()

    result = verifier.verify_all()
    assert not result.passed
    assert any("Required training config schema not found" in e.message for e in result.errors)


def test_training_vector_invalid_config_schema_fails(tmp_path: Path):
    """Verify that if training-config.json violates generator-training-config.schema.json, verification fails."""
    contracts_dir, verifier = _setup_isolated_contracts(tmp_path)
    # create schema
    schema_path = contracts_dir / "schemas" / "generator-training-config.schema.json"
    schema_path.write_text(
        json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["split_ratio"],
            "properties": {
                "split_ratio": {"type": "object"}
            }
        }),
        encoding="utf-8",
    )

    t_vdir = contracts_dir / "test-vectors" / "generator-training-v1"
    t_vdir.mkdir(parents=True, exist_ok=True)
    (t_vdir / "expected").mkdir(parents=True, exist_ok=True)
    (t_vdir / "request.json").write_text(json.dumps({"dataset_id": "ai4i"}), encoding="utf-8")
    # missing required split_ratio
    (t_vdir / "training-config.json").write_text(json.dumps({"training_config_version": "v1"}), encoding="utf-8")
    (t_vdir / "expected" / "artifact-manifest-required.json").write_text(json.dumps({"model_id": "pdm-lgb"}), encoding="utf-8")
    (t_vdir / "expected" / "split-summary.json").write_text(json.dumps({"train_rows": 10}), encoding="utf-8")

    result = verifier.verify_all()
    assert not result.passed
    assert any("Training config schema validation failed" in e.message for e in result.errors)
