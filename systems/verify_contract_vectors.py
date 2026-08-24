"""Lightweight contract vector and schema validation script.

Validates:
1. JSON Schemas under contracts/schemas/**/*.schema.json
2. Example files under contracts/examples/
3. Test vectors under contracts/test-vectors/ (structure, manifest, payload integrity, expected consistency)

This script is standalone, fast, and does NOT execute heavy runtime/Docker/DB services.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import jsonschema
    from jsonschema.validators import validator_for
except ImportError:
    print("ERROR: 'jsonschema' package is required to run systems/verify_contract_vectors.py", file=sys.stderr)
    sys.exit(1)


@dataclass
class VerificationError:
    context: str
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None

    def format(self) -> str:
        lines = [f"FAIL [{self.context}]: {self.message}"]
        if self.expected is not None:
            lines.append(f"  expected: {self.expected}")
        if self.actual is not None:
            lines.append(f"  actual:   {self.actual}")
        return "\n".join(lines)


@dataclass
class VerificationResult:
    schema_count: int = 0
    example_count: int = 0
    vector_count: int = 0
    manifest_count: int = 0
    payload_count: int = 0
    verified_vectors: list[str] = field(default_factory=list)
    errors: list[VerificationError] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ContractVectorVerifier:
    def __init__(self, repo_root: Optional[Path] = None):
        if repo_root is None:
            self.repo_root = Path(__file__).resolve().parents[1]
        else:
            self.repo_root = Path(repo_root).resolve()

        self.contracts_dir = self.repo_root / "contracts"
        self.schemas_dir = self.contracts_dir / "schemas"
        self.examples_dir = self.contracts_dir / "examples"
        self.vectors_dir = self.contracts_dir / "test-vectors"

    def verify_all(self) -> VerificationResult:
        result = VerificationResult()

        # 1. Verify JSON Schemas
        self._verify_schemas(result)

        # 2. Verify Examples
        self._verify_examples(result)

        # 3. Verify Test Vectors
        self._verify_test_vectors(result)

        return result

    def _verify_schemas(self, result: VerificationResult) -> None:
        if not self.schemas_dir.is_dir():
            result.errors.append(
                VerificationError(
                    context="schemas_dir",
                    message=f"Schemas directory not found: {self.schemas_dir}",
                )
            )
            return

        schema_files = sorted(self.schemas_dir.glob("**/*.schema.json"))
        if not schema_files:
            result.errors.append(
                VerificationError(
                    context="schemas_dir",
                    message=f"No JSON schema files found under {self.schemas_dir} (false-green protection)",
                    expected=">= 1 schema files",
                    actual="0 schema files",
                )
            )
            return

        seen_ids: dict[str, Path] = {}

        for sfile in schema_files:
            rel_path = sfile.relative_to(self.repo_root)
            try:
                content = sfile.read_text(encoding="utf-8")
                schema = json.loads(content)
            except Exception as e:
                result.errors.append(
                    VerificationError(
                        context=str(rel_path),
                        message=f"Invalid JSON in schema file: {e}",
                    )
                )
                continue

            result.schema_count += 1

            # Validate against Draft meta-schema if $schema is present
            if isinstance(schema, dict) and "$schema" in schema:
                try:
                    validator_cls = validator_for(schema)
                    validator_cls.check_schema(schema)
                except Exception as e:
                    result.errors.append(
                        VerificationError(
                            context=str(rel_path),
                            message=f"Schema violates its meta-schema ({schema.get('$schema')}): {e}",
                        )
                    )

            # Check $id uniqueness
            if isinstance(schema, dict) and "$id" in schema:
                schema_id = schema["$id"]
                if schema_id in seen_ids:
                    result.errors.append(
                        VerificationError(
                            context=str(rel_path),
                            message=f"Duplicate schema $id '{schema_id}' already used in {seen_ids[schema_id]}",
                            expected="Unique $id across all schema files",
                            actual=f"Duplicate $id '{schema_id}'",
                        )
                    )
                else:
                    seen_ids[schema_id] = rel_path

    def _get_manifest_validator(
        self, result: VerificationResult, context: str
    ) -> Optional[jsonschema.Draft202012Validator]:
        """Load and compile the canonical Dataset Input Manifest schema in a fail-closed manner."""
        manifest_schema_path = self.schemas_dir / "generator-dataset-input-manifest.schema.json"
        if not manifest_schema_path.is_file():
            result.errors.append(
                VerificationError(
                    context=context,
                    message=f"Required manifest schema not found: {manifest_schema_path}",
                    expected="contracts/schemas/generator-dataset-input-manifest.schema.json exists",
                    actual="File missing",
                )
            )
            return None

        try:
            m_schema = json.loads(manifest_schema_path.read_text(encoding="utf-8"))
        except Exception as e:
            result.errors.append(
                VerificationError(
                    context=f"{manifest_schema_path.name}",
                    message=f"Failed to parse manifest schema JSON: {e}",
                )
            )
            return None

        try:
            jsonschema.Draft202012Validator.check_schema(m_schema)
            return jsonschema.Draft202012Validator(m_schema)
        except Exception as e:
            result.errors.append(
                VerificationError(
                    context=f"{manifest_schema_path.name}",
                    message=f"Manifest schema definition is invalid: {e}",
                )
            )
            return None

    def _verify_examples(self, result: VerificationResult) -> None:
        if not self.examples_dir.is_dir():
            return

        example_files = sorted(self.examples_dir.glob("**/*.json"))
        manifest_examples = [ef for ef in example_files if "manifest" in ef.name.lower()]
        manifest_validator = None
        if manifest_examples:
            manifest_validator = self._get_manifest_validator(result, context="examples")

        for efile in example_files:
            rel_path = efile.relative_to(self.repo_root)
            try:
                data = json.loads(efile.read_text(encoding="utf-8"))
            except Exception as e:
                result.errors.append(
                    VerificationError(
                        context=str(rel_path),
                        message=f"Invalid JSON in example file: {e}",
                    )
                )
                continue

            result.example_count += 1

            # If it's a dataset manifest example, validate against dataset manifest schema
            if "manifest" in efile.name.lower() and manifest_validator:
                try:
                    manifest_validator.validate(data)
                except jsonschema.ValidationError as e:
                    result.errors.append(
                        VerificationError(
                            context=str(rel_path),
                            message=f"Example manifest fails schema validation: {e.message}",
                        )
                    )

    def _verify_test_vectors(self, result: VerificationResult) -> None:
        if not self.vectors_dir.is_dir():
            result.errors.append(
                VerificationError(
                    context="test_vectors_dir",
                    message=f"Test vectors directory not found: {self.vectors_dir}",
                )
            )
            return

        vector_dirs = [d for d in sorted(self.vectors_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        if not vector_dirs:
            result.errors.append(
                VerificationError(
                    context="test_vectors_dir",
                    message=f"No test vector directories found under {self.vectors_dir} (false-green protection)",
                    expected=">= 1 test vector directory",
                    actual="0 test vector directories",
                )
            )
            return

        for vdir in vector_dirs:
            vname = vdir.name
            result.vector_count += 1
            error_count_before = len(result.errors)

            if vname.startswith("generator-training") or (vdir / "training-config.json").is_file():
                self._verify_training_vector(vname, vdir, result)
            elif vname.startswith("generator-feature-input") or (vdir / "observation").is_dir():
                manifest_validator = self._get_manifest_validator(result, context=vname)
                self._verify_feature_input_vector(vname, vdir, manifest_validator, result)
            else:
                result.errors.append(
                    VerificationError(
                        context=f"{vname}",
                        message=f"Unknown test vector structure for '{vname}'",
                    )
                )

            if len(result.errors) == error_count_before:
                result.verified_vectors.append(vname)

    def _verify_feature_input_vector(
        self,
        vector_name: str,
        vector_dir: Path,
        manifest_validator: Optional[jsonschema.Draft202012Validator],
        result: VerificationResult,
    ) -> None:
        # 3.1 Check required files
        req_files = [
            vector_dir / "request.json",
            vector_dir / "observation" / "dataset_manifest.json",
            vector_dir / "failure" / "dataset_manifest.json",
            vector_dir / "expected" / "feature_columns.json",
            vector_dir / "expected" / "labels.json",
            vector_dir / "expected" / "row_metadata.json",
            vector_dir / "expected" / "summary.json",
        ]
        missing = [f.relative_to(vector_dir) for f in req_files if not f.is_file()]
        if missing:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}",
                    message=f"Missing required test vector file(s): {', '.join(str(m) for m in missing)}",
                    expected="All required test vector files present",
                    actual=f"Missing {missing}",
                )
            )
            return

        # 3.2 Validate request.json as valid non-empty JSON object
        req_path = vector_dir / "request.json"
        try:
            req_content = req_path.read_text(encoding="utf-8").strip()
            if not req_content:
                result.errors.append(
                    VerificationError(
                        context=f"{vector_name}/request.json",
                        message="request.json is empty",
                        expected="Non-empty JSON object",
                        actual="Empty file",
                    )
                )
            else:
                req_data = json.loads(req_content)
                if not isinstance(req_data, dict):
                    result.errors.append(
                        VerificationError(
                            context=f"{vector_name}/request.json",
                            message=f"request.json top-level must be a JSON object, got {type(req_data).__name__}",
                            expected="JSON object ({...})",
                            actual=f"{type(req_data).__name__}",
                        )
                    )
        except Exception as e:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/request.json",
                    message=f"Invalid JSON in request.json: {e}",
                )
            )

        # 3.3 Verify Manifest & Payload Integrity (Observation & Failure)
        self._verify_vector_manifest(
            vector_name=vector_name,
            vector_dir=vector_dir,
            manifest_path=vector_dir / "observation" / "dataset_manifest.json",
            expected_dataset_type="observation",
            expected_role="observations",
            manifest_validator=manifest_validator,
            result=result,
        )

        self._verify_vector_manifest(
            vector_name=vector_name,
            vector_dir=vector_dir,
            manifest_path=vector_dir / "failure" / "dataset_manifest.json",
            expected_dataset_type="failure",
            expected_role="failures",
            manifest_validator=manifest_validator,
            result=result,
        )

        # 3.4 Verify Golden Expected Static Consistency
        self._verify_vector_expected(
            vector_name=vector_name,
            vector_dir=vector_dir,
            result=result,
        )

    def _verify_training_vector(
        self,
        vector_name: str,
        vector_dir: Path,
        result: VerificationResult,
    ) -> None:
        req_files = [
            vector_dir / "request.json",
            vector_dir / "training-config.json",
            vector_dir / "expected" / "artifact-manifest-required.json",
            vector_dir / "expected" / "split-summary.json",
        ]
        missing = [f.relative_to(vector_dir) for f in req_files if not f.is_file()]
        if missing:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}",
                    message=f"Missing required training test vector file(s): {', '.join(str(m) for m in missing)}",
                    expected="All required training test vector files present",
                    actual=f"Missing {missing}",
                )
            )
            return

        # 1. Validate request.json as valid non-empty JSON object
        req_path = vector_dir / "request.json"
        try:
            req_content = req_path.read_text(encoding="utf-8").strip()
            if not req_content:
                result.errors.append(
                    VerificationError(
                        context=f"{vector_name}/request.json",
                        message="request.json is empty",
                        expected="Non-empty JSON object",
                        actual="Empty file",
                    )
                )
            else:
                req_data = json.loads(req_content)
                if not isinstance(req_data, dict):
                    result.errors.append(
                        VerificationError(
                            context=f"{vector_name}/request.json",
                            message=f"request.json top-level must be a JSON object, got {type(req_data).__name__}",
                            expected="JSON object ({...})",
                            actual=f"{type(req_data).__name__}",
                        )
                    )
        except Exception as e:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/request.json",
                    message=f"Invalid JSON in request.json: {e}",
                )
            )

        # 2. Validate training-config.json against generator-training-config.schema.json (Fail-closed)
        cfg_schema_path = self.schemas_dir / "generator-training-config.schema.json"
        if not cfg_schema_path.is_file():
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}",
                    message=f"Required training config schema not found: {cfg_schema_path}",
                    expected="contracts/schemas/generator-training-config.schema.json exists",
                    actual="File missing",
                )
            )
        else:
            try:
                cfg_schema = json.loads(cfg_schema_path.read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator.check_schema(cfg_schema)
                cfg_validator = jsonschema.Draft202012Validator(cfg_schema)
                cfg_data = json.loads((vector_dir / "training-config.json").read_text(encoding="utf-8"))
                cfg_validator.validate(cfg_data)
            except Exception as e:
                result.errors.append(
                    VerificationError(
                        context=f"{vector_name}/training-config.json",
                        message=f"Training config schema validation failed: {e}",
                    )
                )

        # 3. Validate expected JSON files
        try:
            exp_manifest = json.loads((vector_dir / "expected" / "artifact-manifest-required.json").read_text(encoding="utf-8"))
            if not isinstance(exp_manifest, dict):
                result.errors.append(
                    VerificationError(
                        context=f"{vector_name}/expected/artifact-manifest-required.json",
                        message="artifact-manifest-required.json top-level must be a JSON object",
                    )
                )
            exp_split = json.loads((vector_dir / "expected" / "split-summary.json").read_text(encoding="utf-8"))
            if not isinstance(exp_split, dict):
                result.errors.append(
                    VerificationError(
                        context=f"{vector_name}/expected/split-summary.json",
                        message="split-summary.json top-level must be a JSON object",
                    )
                )
        except Exception as e:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected",
                    message=f"Invalid JSON in expected training files: {e}",
                )
            )

    def _verify_vector_manifest(
        self,
        vector_name: str,
        vector_dir: Path,
        manifest_path: Path,
        expected_dataset_type: str,
        expected_role: str,
        manifest_validator: Optional[jsonschema.Draft202012Validator],
        result: VerificationResult,
    ) -> None:
        rel_manifest = manifest_path.relative_to(self.repo_root)
        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            result.errors.append(
                VerificationError(
                    context=str(rel_manifest),
                    message=f"Invalid JSON in dataset manifest: {e}",
                )
            )
            return

        result.manifest_count += 1

        # Validate with JSON Schema
        if manifest_validator:
            try:
                manifest_validator.validate(m_data)
            except jsonschema.ValidationError as e:
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message=f"Manifest schema validation failed: {e.message}",
                    )
                )

        # dataset_type check
        actual_type = m_data.get("dataset_type")
        if actual_type != expected_dataset_type:
            result.errors.append(
                VerificationError(
                    context=str(rel_manifest),
                    message=f"dataset_type mismatch in manifest",
                    expected=expected_dataset_type,
                    actual=str(actual_type),
                )
            )

        files = m_data.get("files", [])
        if not isinstance(files, list):
            result.errors.append(
                VerificationError(
                    context=str(rel_manifest),
                    message="'files' field must be a list",
                )
            )
            return

        # Check role presence and uniqueness
        matching_roles = [f for f in files if isinstance(f, dict) and f.get("role") == expected_role]
        if len(matching_roles) != 1:
            result.errors.append(
                VerificationError(
                    context=str(rel_manifest),
                    message=f"Manifest must contain exactly one file entry with role '{expected_role}'",
                    expected=f"1 entry with role '{expected_role}'",
                    actual=f"{len(matching_roles)} entries",
                )
            )

        # Check for duplicate roles
        roles = [f.get("role") for f in files if isinstance(f, dict)]
        if len(roles) != len(set(roles)):
            result.errors.append(
                VerificationError(
                    context=str(rel_manifest),
                    message="Duplicate roles declared in files list",
                    expected="All file roles must be unique",
                    actual=str(roles),
                )
            )

        # Verify each payload file
        manifest_dir = manifest_path.parent
        for file_entry in files:
            if not isinstance(file_entry, dict):
                continue

            declared_path_str = file_entry.get("path")
            declared_sha = file_entry.get("sha256")
            declared_size = file_entry.get("size_bytes")

            if not declared_path_str:
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message="File entry missing 'path'",
                    )
                )
                continue

            # Path safety checks: must be relative, no '..', not absolute
            is_absolute_path = (
                declared_path_str.startswith("/")
                or declared_path_str.startswith("\\")
                or os.path.isabs(declared_path_str)
                or Path(declared_path_str).is_absolute()
                or (len(declared_path_str) > 1 and declared_path_str[1] == ":")
            )
            if is_absolute_path:
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message=f"Payload path must not be absolute: '{declared_path_str}'",
                    )
                )
                continue

            if ".." in Path(declared_path_str).parts:
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message=f"Payload path must not traverse parent directories (..): '{declared_path_str}'",
                    )
                )
                continue

            target_path = (manifest_dir / declared_path_str).resolve()
            # Ensure resolved path is inside manifest_dir / vector_dir
            try:
                target_path.relative_to(vector_dir.resolve())
            except ValueError:
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message=f"Payload path resolves outside vector directory: '{declared_path_str}'",
                    )
                )
                continue

            if not target_path.is_file():
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message=f"Declared payload file does not exist: {target_path}",
                    )
                )
                continue

            # SHA-256 check
            actual_sha = compute_sha256(target_path)
            if declared_sha and actual_sha.lower() != declared_sha.lower():
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message=f"Payload SHA-256 checksum mismatch for '{declared_path_str}'",
                        expected=str(declared_sha),
                        actual=str(actual_sha),
                    )
                )

            # File size check
            actual_size = target_path.stat().st_size
            if declared_size is not None and actual_size != declared_size:
                result.errors.append(
                    VerificationError(
                        context=str(rel_manifest),
                        message=f"Payload size_bytes mismatch for '{declared_path_str}'",
                        expected=f"{declared_size} bytes",
                        actual=f"{actual_size} bytes",
                    )
                )

            result.payload_count += 1

    def _verify_vector_expected(
        self,
        vector_name: str,
        vector_dir: Path,
        result: VerificationResult,
    ) -> None:
        expected_dir = vector_dir / "expected"

        try:
            feat_cols = json.loads((expected_dir / "feature_columns.json").read_text(encoding="utf-8"))
            labels = json.loads((expected_dir / "labels.json").read_text(encoding="utf-8"))
            row_meta = json.loads((expected_dir / "row_metadata.json").read_text(encoding="utf-8"))
            summary = json.loads((expected_dir / "summary.json").read_text(encoding="utf-8"))
        except Exception as e:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected",
                    message=f"Failed to parse expected JSON file: {e}",
                )
            )
            return

        # 1. feature_columns consistency
        cols = feat_cols.get("columns", [])
        col_count = feat_cols.get("count")
        if not isinstance(cols, list) or col_count != len(cols):
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/feature_columns.json",
                    message="feature_columns.json count mismatch",
                    expected=f"count == len(columns) ({len(cols)})",
                    actual=f"count: {col_count}",
                )
            )

        # 2. labels array consistency
        if not isinstance(labels, list):
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/labels.json",
                    message="labels.json must be a JSON array",
                )
            )
            return

        for idx, label_val in enumerate(labels):
            if label_val not in (0, 1):
                result.errors.append(
                    VerificationError(
                        context=f"{vector_name}/expected/labels.json",
                        message=f"Invalid label value at index {idx}: {label_val}",
                        expected="0 or 1",
                        actual=str(label_val),
                    )
                )
                break

        # 3. row_metadata consistency
        if not isinstance(row_meta, list):
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/row_metadata.json",
                    message="row_metadata.json must be a JSON array",
                )
            )
            return

        for idx, r_item in enumerate(row_meta):
            if not isinstance(r_item, dict) or "asset_id" not in r_item or "timestamp" not in r_item:
                result.errors.append(
                    VerificationError(
                        context=f"{vector_name}/expected/row_metadata.json",
                        message=f"Row metadata entry at index {idx} missing 'asset_id' or 'timestamp'",
                    )
                )
                break

        # 4. Length parity between labels and row_metadata
        if len(labels) != len(row_meta):
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected",
                    message="Length mismatch between labels and row_metadata",
                    expected=f"len(labels) == len(row_metadata) ({len(labels)})",
                    actual=f"labels: {len(labels)}, row_metadata: {len(row_meta)}",
                )
            )

        # 5. summary.json consistency
        expected_row_count = summary.get("row_count")
        expected_feat_count = summary.get("feature_count")
        pos_count = summary.get("positive_label_count")
        neg_count = summary.get("negative_label_count")

        if expected_row_count != len(labels):
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/summary.json",
                    message="summary.json row_count mismatch",
                    expected=f"row_count == len(labels) ({len(labels)})",
                    actual=f"row_count: {expected_row_count}",
                )
            )

        if expected_feat_count != len(cols):
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/summary.json",
                    message="summary.json feature_count mismatch",
                    expected=f"feature_count == len(columns) ({len(cols)})",
                    actual=f"feature_count: {expected_feat_count}",
                )
            )

        actual_pos = sum(1 for x in labels if x == 1)
        actual_neg = sum(1 for x in labels if x == 0)

        if pos_count != actual_pos:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/summary.json",
                    message="summary.json positive_label_count mismatch",
                    expected=f"positive_label_count == {actual_pos}",
                    actual=f"positive_label_count: {pos_count}",
                )
            )

        if neg_count != actual_neg:
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/summary.json",
                    message="summary.json negative_label_count mismatch",
                    expected=f"negative_label_count == {actual_neg}",
                    actual=f"negative_label_count: {neg_count}",
                )
            )

        if pos_count is not None and neg_count is not None and (pos_count + neg_count != len(labels)):
            result.errors.append(
                VerificationError(
                    context=f"{vector_name}/expected/summary.json",
                    message="Sum of positive and negative label counts does not equal total row_count",
                    expected=f"pos ({pos_count}) + neg ({neg_count}) == {len(labels)}",
                    actual=f"sum: {pos_count + neg_count}",
                )
            )


def main() -> int:
    verifier = ContractVectorVerifier()
    result = verifier.verify_all()

    if result.passed:
        print(f"PASS schemas: {result.schema_count}")
        print(f"PASS examples: {result.example_count}")
        print(f"PASS vectors: {result.vector_count}")
        print(f"PASS manifests: {result.manifest_count}")
        print(f"PASS payload integrity: {result.payload_count}")
        if result.verified_vectors:
            print(f"PASS expected consistency: {', '.join(result.verified_vectors)}")
        print("Contract vector verification passed.")
        return 0
    else:
        for err in result.errors:
            print(err.format(), file=sys.stderr)
        print(f"\nContract vector verification failed with {len(result.errors)} error(s).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
