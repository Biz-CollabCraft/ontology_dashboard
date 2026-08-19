"""Generate the public What-if producer result schema."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.preventive_intervention.contracts import preventive_what_if_schema


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "schemas" / "preventive-what-if.schema.json"


def main() -> None:
    TARGET.write_text(
        json.dumps(preventive_what_if_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
