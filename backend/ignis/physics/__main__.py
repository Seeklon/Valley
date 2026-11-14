"""Compile checks without starting a calculation on the coordinating host."""

import argparse
import json
from pathlib import Path

from .compiler import compile_case
from .parser import parse_result
from .verification import verification_cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["compile-check", "parse"])
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--case", choices=["cold", "transport", "coupled"], default="cold")
    args = parser.parse_args()
    if args.command == "compile-check":
        scene, config = verification_cases()[args.case]
        manifest = compile_case(scene, config, args.output_dir)
        print(
            json.dumps(
                {
                    "input": str(args.output_dir / manifest["input_file"]),
                    "mesh": manifest["mesh"],
                    "devices": manifest["estimates"]["device_count"],
                }
            )
        )
    else:
        result = parse_result(args.output_dir)
        target = args.output_dir / "result.json"
        target.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        print(json.dumps({"output": str(target), "summary": result["summary"]}))


if __name__ == "__main__":
    main()
