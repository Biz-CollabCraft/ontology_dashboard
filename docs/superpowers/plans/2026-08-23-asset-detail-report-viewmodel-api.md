# Asset Detail Report ViewModel API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first PR95 follow-up slice for `AssetDetailReportViewModel` as a backend-owned composition contract, without promoting prototype or gen_data fixture internals to runtime truth.

**Architecture:** Add a JSON Schema and Pydantic/domain composer under `app/report`. The composer accepts already-contracted Product Result Artifact, Observation series, runtime risk history, and maintenance history data through a port; unavailable data is represented with gaps instead of synthesized graph values.

**Tech Stack:** Python 3, Pydantic, pytest, jsonschema, existing `systems/backend/app/report` domain package.

---

### Task 1: Contract Schema And Fixtures

**Files:**
- Create: `contracts/schemas/asset-detail-report-view-model.schema.json`
- Create: `tests/fixtures/asset_detail_report_view_model/current-evidence-only.json`
- Create: `tests/test_asset_detail_report_view_model_contract.py`

- [ ] **Step 1: Write schema and fixture**

Create a schema with required top-level fields: `asset`, `risk`, `risk_series`, `features`, `equipment_history`, `evidence`, and `data_status`. `risk.status_grade` allows `normal`, `attention`, `warning`, `critical`, or `null`; `data_quality_hold` is represented by `data_status.is_data_quality_hold`.

- [ ] **Step 2: Validate fixture**

Run: `pytest -q tests/test_asset_detail_report_view_model_contract.py`
Expected before implementation: fail if schema or fixture is missing. Expected after implementation: pass.

### Task 2: Backend Composer

**Files:**
- Create: `systems/backend/app/report/asset_detail_report_view_model.py`
- Modify: `systems/backend/app/report/__init__.py`
- Test: `tests/test_asset_detail_report_view_model_composer.py`

- [ ] **Step 1: Write composer tests**

Cover schema-valid output, missing series gaps, rejected raw `gen_data`/precomputed timeline source refs, nullable baselines, and data-quality hold separation.

- [ ] **Step 2: Implement composer**

Define `AssetDetailReportRequest`, `AssetDetailReportReadPort`, `AssetDetailReportViewModelService`, and `compose_asset_detail_report_view_model()`. The service reads only from the port; the composer never opens files or imports generator/prototype modules.

- [ ] **Step 3: Verify**

Run: `pytest -q tests/test_asset_detail_report_view_model_contract.py tests/test_asset_detail_report_view_model_composer.py`
Expected: all tests pass.

### Task 3: Scope Guard

**Files:**
- Modify: `tests/test_report_domain_migration.py`

- [ ] **Step 1: Add the new report file to canonical report-domain checks**

Ensure `asset_detail_report_view_model.py` is recognized as canonical report-domain source and still has no `app.infra` or legacy `ontology_dashboard` imports.

- [ ] **Step 2: Verify**

Run: `pytest -q tests/test_report_domain_migration.py`
Expected: pass.

### Task 4: Final Validation

**Files:**
- All changed files

- [ ] **Step 1: Run focused tests**

Run: `pytest -q tests/test_asset_detail_report_view_model_contract.py tests/test_asset_detail_report_view_model_composer.py tests/test_report_domain_migration.py`

- [ ] **Step 2: Run whitespace check**

Run: `git diff --check`

- [ ] **Step 3: Report state**

Report changed files, test results, and explicit boundary: this slice adds contract/composer evidence, not a live Product API endpoint or frontend ViewModel consumption yet.
