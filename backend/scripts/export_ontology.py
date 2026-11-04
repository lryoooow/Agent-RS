"""Export live platform definitions or a saved schema to Ontology Playground JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent.ontology.catalog import build_catalog, load_schema, to_playground


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Optional saved ontology_schema.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    schema = load_schema(args.input) if args.input else build_catalog()[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(to_playground(schema), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(schema.entity_types)} entity types to {args.output}")


if __name__ == "__main__":
    main()
