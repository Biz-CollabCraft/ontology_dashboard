"""Planner for data structure classification and column extraction rules."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional
import pandas as pd

import systems.generator.generator_llm_client as generator_llm_client
from systems.generator.app.extraction.extraction_schema import (
    ExtractionStructureResponse,
    ExtractionPlanResponse,
)
from systems.generator.app.extraction.extraction_exception import (
    ExtractionRoleError,
    ExtractionPlanningError,
)

logger = logging.getLogger(__name__)


class ExtractionPlanner:
    """Handles 2-stage analysis (structure classification & column planning) with strict validation."""

    def compute_fingerprint(self, df_preview: pd.DataFrame) -> str:
        raw_str = f"cols:{list(df_preview.columns)}|head:{df_preview.head(3).to_json()}"
        return hashlib.md5(raw_str.encode("utf-8")).hexdigest()

    def classify_structure(self, filepath: str, df_preview: pd.DataFrame) -> str:
        """Stage 1: Classify table format into supported structure types."""
        system_prompt = (
            "You are a manufacturing data structure classifier.\n"
            "Classify the input table format into EXACTLY ONE of the following structure types:\n"
            "- tabular_column_as_attribute: Standard table where each column is an attribute/sensor feature.\n"
            "- tabular_row_as_attribute: Long format table where rows contain sensor attribute names and values.\n"
            "- wide_pivot: Wide format matrix requiring reshaping.\n"
            "- unsupported: Unparseable unstructured text or binary.\n\n"
            "Respond ONLY with a JSON object: {\"structure_type\": \"...\", \"reason\": \"...\"}"
        )
        prompt = f"File: {os.path.basename(filepath)}\nColumns: {list(df_preview.columns)}\nSample:\n{df_preview.head(3).to_string()}"

        try:
            raw_res = generator_llm_client.call_llm(prompt, system=system_prompt)
            res = generator_llm_client.validate_or_transform_pydantic(raw_res, ExtractionStructureResponse)
            st_type = res.structure_type if res else "tabular_column_as_attribute"
            logger.info(f"[ExtractionPlanner] Stage 1 structure classification for '{filepath}': {st_type}")
            return st_type
        except Exception as e:
            logger.warning(f"[ExtractionPlanner] Stage 1 classification fallback: {e}")
            return "tabular_column_as_attribute"

    def plan_columns(
        self,
        filepath: str,
        structure_type: str,
        df_preview: pd.DataFrame,
        duplicate_policy: str = "error",
        aggregation: Optional[str] = None,
    ) -> dict[str, Any]:
        """Stage 2: Determine column roles and extraction mapping."""
        avail_cols = list(df_preview.columns)
        if structure_type == "tabular_row_as_attribute":
            system_prompt = (
                "You are a dataset extraction planner for long-format (tabular_row_as_attribute) manufacturing sensor data.\n"
                "Analyze the columns and sample data, then specify the exact role for each column:\n"
                "- id_column: The asset/machine identifier column.\n"
                "- time_column: The timestamp column (if present, else null).\n"
                "- attribute_column: The sensor/feature attribute name column.\n"
                "- value_column: The numeric measurement value column.\n"
                "- selected_columns: List of all relevant columns.\n"
                "Respond ONLY with a JSON object: {\n"
                '  "structure_type": "tabular_row_as_attribute",\n'
                '  "id_column": "col_id",\n'
                '  "time_column": "col_time",\n'
                '  "attribute_column": "col_attr",\n'
                '  "value_column": "col_val",\n'
                '  "duplicate_policy": "error",\n'
                '  "selected_columns": ["col1", "col2", ...]\n'
                "}"
            )
        else:
            system_prompt = (
                "You are a dataset column selector for manufacturing predictive maintenance.\n"
                "Select all relevant telemetry sensors, time/date fields, and asset identifiers for model analysis.\n"
                "Respond ONLY with a JSON object: {\"selected_columns\": [\"col1\", \"col2\", ...]}"
            )

        prompt = (
            f"File: {os.path.basename(filepath)}\n"
            f"Structure Type: {structure_type}\n"
            f"Available Columns: {avail_cols}\n"
            f"Sample:\n{df_preview.head(3).to_string()}"
        )

        try:
            raw_res = generator_llm_client.call_llm(prompt, system=system_prompt)
            res = generator_llm_client.validate_or_transform_pydantic(raw_res, ExtractionPlanResponse)
            if res:
                if structure_type == "tabular_row_as_attribute":
                    roles = [res.id_column, res.attribute_column, res.value_column]
                    if not all(roles) or not all(r in avail_cols for r in roles):
                        raise ExtractionRoleError(
                            f"Long-format extraction requires explicit id, attribute, and value columns; "
                            f"roles {roles} not fully found in columns {avail_cols}"
                        )
                cols = res.selected_columns if res.selected_columns else avail_cols
                return {
                    "selected_columns": cols,
                    "id_column": res.id_column,
                    "time_column": res.time_column,
                    "attribute_column": res.attribute_column,
                    "value_column": res.value_column,
                    "duplicate_policy": duplicate_policy or res.duplicate_policy or "error",
                    "aggregation": aggregation or res.aggregation,
                }
        except ExtractionRoleError:
            raise
        except Exception as e:
            logger.warning(f"[ExtractionPlanner] Stage 2 column selection LLM call failed: {e}")
            if structure_type == "tabular_row_as_attribute":
                raise ExtractionRoleError(
                    f"Long-format extraction requires explicit role columns (id, attribute, value). "
                    f"Planning failed: {e}"
                ) from e

        if structure_type == "tabular_row_as_attribute":
            raise ExtractionRoleError(
                f"Long-format extraction requires explicit id, attribute, and value columns for '{filepath}'"
            )

        return {
            "selected_columns": avail_cols,
            "duplicate_policy": duplicate_policy,
            "aggregation": aggregation,
        }

    def enforce_key_columns(self, selected_columns: list[str], available_columns: list[str]) -> list[str]:
        """Preserve key machine and timestamp column identifiers if present in available columns."""
        result = list(selected_columns)
        id_candidates = ["asset_id", "machineID", "equipment_id", "device_id", "asset", "machine"]
        time_candidates = ["observed_at", "datetime", "timestamp", "time", "date"]

        has_id = any(c in result for c in id_candidates)
        if not has_id:
            found_id = next((c for c in available_columns if c in id_candidates), None)
            if found_id and found_id not in result:
                result.append(found_id)

        has_time = any(c in result for c in time_candidates)
        if not has_time:
            found_time = next((c for c in available_columns if c in time_candidates), None)
            if found_time and found_time not in result:
                result.append(found_time)

        return result

    def build_plan(
        self,
        filepath: str,
        force_reanalyze: bool = False,
        duplicate_policy: str = "error",
        aggregation: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build extraction plan from preview data and LLM analysis."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".csv":
            df_preview = pd.read_csv(filepath, nrows=5)
        elif ext in (".xlsx", ".xls"):
            df_preview = pd.read_excel(filepath, nrows=5)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

        fingerprint = self.compute_fingerprint(df_preview)
        file_key = os.path.basename(filepath)

        structure_type = self.classify_structure(filepath, df_preview)
        if structure_type == "unsupported":
            raise ExtractionPlanningError(f"File '{filepath}' classified as unsupported format.")

        stage2_plan = self.plan_columns(
            filepath,
            structure_type,
            df_preview,
            duplicate_policy=duplicate_policy,
            aggregation=aggregation,
        )
        raw_selected = stage2_plan.get("selected_columns", list(df_preview.columns))
        final_selected = self.enforce_key_columns(raw_selected, list(df_preview.columns))

        plan = {
            "filepath": filepath,
            "filename": file_key,
            "fingerprint": fingerprint,
            "structure_type": structure_type,
            "selected_columns": final_selected,
            "id_column": stage2_plan.get("id_column"),
            "time_column": stage2_plan.get("time_column"),
            "attribute_column": stage2_plan.get("attribute_column"),
            "value_column": stage2_plan.get("value_column"),
            "duplicate_policy": stage2_plan.get("duplicate_policy", duplicate_policy),
            "aggregation": stage2_plan.get("aggregation", aggregation),
        }
        return plan
