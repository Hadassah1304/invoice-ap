"""Command line interface for datagen.

Commands:
  python -m datagen finalize  --base base/ --out build/ --seed 42
  python -m datagen validate  --base base/ --seed 42 [--pipeline-config config.yaml]
  python -m datagen compile   --base base/ --out build/ --seed 42 [--pipeline-config config.yaml]
  python -m datagen build     --base base/ --out build/ --seed 42 [--pipeline-config config.yaml]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from datagen.compile import compile_dataset
from datagen.constants import Config
from datagen.finalize import finalize_state
from datagen.loader import load_authored_base


def cmd_finalize(args: argparse.Namespace) -> int:
    loaded = load_authored_base(args.base)
    if loaded.load_errors:
        print(f"Errors loading base files from {args.base}:", file=sys.stderr)
        for err in loaded.load_errors:
            print(f"  [{err['severity']}] {err['code']}: {err['message']}", file=sys.stderr)
        return 1

    finalized = finalize_state(loaded, seed=args.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    state_path = out_dir / "state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(finalized.state_output.model_dump(), f, indent=2, sort_keys=True, ensure_ascii=False)

    print(f"Successfully finalized state to {state_path}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = Config.from_pipeline_config(Path(args.pipeline_config)) if args.pipeline_config else Config()
    loaded = load_authored_base(args.base)

    result = compile_dataset(loaded, seed=args.seed, config=config)
    print(result.validation_report_md)

    if result.has_errors:
        return 1
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    config = Config.from_pipeline_config(Path(args.pipeline_config)) if args.pipeline_config else Config()
    loaded = load_authored_base(args.base)

    result = compile_dataset(loaded, seed=args.seed, config=config)
    if result.has_errors:
        print("Validation errors encountered. Cannot compile:", file=sys.stderr)
        print(result.validation_report_md, file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write cases.json
    with open(out_dir / "cases.json", "w", encoding="utf-8") as f:
        json.dump(result.cases_output.model_dump(), f, indent=2, sort_keys=True, ensure_ascii=False)

    # Write manifest_base.csv
    with open(out_dir / "manifest_base.csv", "w", encoding="utf-8") as f:
        f.write(result.manifest_csv_text)

    # Write validation_report.md & json
    with open(out_dir / "validation_report.md", "w", encoding="utf-8") as f:
        f.write(result.validation_report_md)
    with open(out_dir / "validation_report.json", "w", encoding="utf-8") as f:
        json.dump(result.validation_report_json, f, indent=2, sort_keys=True)

    print(f"Compilation successful. Outputs written to {out_dir}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    config = Config.from_pipeline_config(Path(args.pipeline_config)) if args.pipeline_config else Config()
    loaded = load_authored_base(args.base)

    result = compile_dataset(loaded, seed=args.seed, config=config)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Always write validation report so authors have fix hints
    with open(out_dir / "validation_report.md", "w", encoding="utf-8") as f:
        f.write(result.validation_report_md)
    with open(out_dir / "validation_report.json", "w", encoding="utf-8") as f:
        json.dump(result.validation_report_json, f, indent=2, sort_keys=True)

    if result.has_errors and not getattr(args, "force", False):
        print("Build failed with validation errors:", file=sys.stderr)
        print(result.validation_report_md, file=sys.stderr)
        return 1

    # Write state.json
    with open(out_dir / "state.json", "w", encoding="utf-8") as f:
        json.dump(result.finalized_state.state_output.model_dump(), f, indent=2, sort_keys=True, ensure_ascii=False)

    # Write cases.json
    with open(out_dir / "cases.json", "w", encoding="utf-8") as f:
        json.dump(result.cases_output.model_dump(), f, indent=2, sort_keys=True, ensure_ascii=False)

    # Write manifest_base.csv
    with open(out_dir / "manifest_base.csv", "w", encoding="utf-8") as f:
        f.write(result.manifest_csv_text)

    print(f"Build complete. All artifacts generated in {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="datagen", description="Deterministic invoice dataset generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # finalize
    p_fin = subparsers.add_parser("finalize", help="Compute derived numbers and write state.json")
    p_fin.add_argument("--base", required=True, help="Base directory with core.json and family_*.json")
    p_fin.add_argument("--out", required=True, help="Output directory")
    p_fin.add_argument("--seed", type=int, default=42, help="Random seed")

    # validate
    p_val = subparsers.add_parser("validate", help="Validate authored data against contract rules")
    p_val.add_argument("--base", required=True, help="Base directory with core.json and family_*.json")
    p_val.add_argument("--seed", type=int, default=42, help="Random seed")
    p_val.add_argument("--pipeline-config", default=None, help="Path to config.yaml")

    # compile
    p_comp = subparsers.add_parser("compile", help="Compile cases.json and manifest_base.csv")
    p_comp.add_argument("--base", required=True, help="Base directory with core.json and family_*.json")
    p_comp.add_argument("--out", required=True, help="Output directory")
    p_comp.add_argument("--seed", type=int, default=42, help="Random seed")
    p_comp.add_argument("--pipeline-config", default=None, help="Path to config.yaml")

    # build
    p_bld = subparsers.add_parser("build", help="Finalize, validate, and compile all outputs")
    p_bld.add_argument("--base", required=True, help="Base directory with core.json and family_*.json")
    p_bld.add_argument("--out", required=True, help="Output directory")
    p_bld.add_argument("--seed", type=int, default=42, help="Random seed")
    p_bld.add_argument("--pipeline-config", default=None, help="Path to config.yaml")
    p_bld.add_argument("--force", action="store_true", help="Write outputs even if validation errors exist")

    args = parser.parse_args()
    if args.command == "finalize":
        return cmd_finalize(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command == "compile":
        return cmd_compile(args)
    elif args.command == "build":
        return cmd_build(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
