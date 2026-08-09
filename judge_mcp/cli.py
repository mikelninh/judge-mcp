from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from judge_mcp.judge import judge_artifact
from judge_mcp.rubrics import get_rubric


def _load_rubric(rubric_id: str | None, rubric_file: str | None) -> dict:
    if rubric_file:
        data = json.loads(Path(rubric_file).read_text(encoding="utf-8"))
        return data.get("rubric", data)
    if rubric_id:
        rubric = get_rubric(rubric_id)
        if rubric is not None:
            return rubric
    raise SystemExit("Unknown rubric. Pass --rubric <id> or --rubric-file <path>.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Judge one artifact from stdin and emit machine-readable JSON."
    )
    parser.add_argument("--rubric", help="Built-in judge-mcp rubric id")
    parser.add_argument("--rubric-file", help="Path to a standalone rubric JSON file")
    parser.add_argument("--model", help="Optional model override")
    args = parser.parse_args()

    artifact = sys.stdin.read()
    if not artifact.strip():
        raise SystemExit("Artifact is empty; pipe text on stdin.")

    rubric = _load_rubric(args.rubric, args.rubric_file)
    result = judge_artifact(artifact, rubric, model=args.model)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
