"""
__init__.py (extraction package)

담당 기능:
- extraction 도메인 공개 모듈 초기화 및 서비스 함수 파사드.

입력:
- None

출력:
- export symbols: load_all_sources, build_extraction_plan, build_family_registry, extract_with_plan

의존 모듈:
- extraction_service: load_all_sources, extract_with_plan
- extraction_agent: build_extraction_plan
- extraction_profiler: build_family_registry

예외/경계 상황:
- None

설계 원칙과의 연결:
- docs/architecture.md의 '도메인 서비스 파사드' 원칙에 따라 외부에 일관된 진입점을 제공한다.
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parents[3])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from systems.generator.extraction.extraction_service import load_all_sources, extract_with_plan
    from systems.generator.extraction.extraction_agent import build_extraction_plan
    from systems.generator.extraction.extraction_profiler import build_family_registry
except ImportError:
    load_all_sources = None
    extract_with_plan = None
    build_extraction_plan = None
    build_family_registry = None

__all__ = ["load_all_sources", "extract_with_plan", "build_extraction_plan", "build_family_registry"]
