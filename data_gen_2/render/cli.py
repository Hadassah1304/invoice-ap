from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Optional

from manifest import build_manifest_and_report
from render.render_all import render_all_cases
from seed.build_seed import build_seed_json
from verify import verify_dataset


def cmd_files(build: str, out: str, seed: int):
    cases_path = Path(build) / "cases.json"
    if not cases_path.exists():
        print(f"Error: cases.json not found in {build}", file=sys.stderr)
        sys.exit(1)
    print(f"Rendering invoice files from {cases_path} into {out} (seed={seed})...")
    results = render_all_cases(str(cases_path), out_dir=out, seed=seed)
    print(f"Successfully rendered {len(results)} invoice cases.")


def cmd_seed(build: str, out: str, embedder: str):
    state_path = Path(build) / "state.json"
    if not state_path.exists():
        print(f"Error: state.json not found in {build}", file=sys.stderr)
        sys.exit(1)
    print(f"Building seed database file from {state_path} into {out} (embedder={embedder})...")
    build_seed_json(str(state_path), out_seed_path=out, embedder_backend=embedder)
    print(f"Successfully generated seed database file: {out}")


def cmd_manifest(build: str, out: str, embedder: str):
    print(f"Building manifest.csv and dataset_report.md for {out}...")
    m_path, r_path = build_manifest_and_report(build_dir=build, out_dir=out, embedder_backend=embedder)
    print(f"Generated manifest: {m_path}")
    print(f"Generated report: {r_path}")


def cmd_all(build: str, out: str, seed: int, embedder: str):
    print(f"=== Starting full dataset generation (seed={seed}, embedder={embedder}) ===")
    cmd_files(build, out, seed)
    seed_out = Path(out) / "seed.json"
    cmd_seed(build, str(seed_out), embedder)
    cmd_manifest(build, out, embedder)
    print(f"=== Dataset generation complete! Outputs written to {out} ===")


def cmd_verify(out: str, build: str):
    print(f"Verifying dataset in {out} against {build}...")
    success = verify_dataset(samples_dir=out, build_dir=build)
    if not success:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(prog="render", description="Invoice Dataset Renderer & Seeder CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: files
    p_files = subparsers.add_parser("files", help="Render invoice files (PDFs and degraded scans)")
    p_files.add_argument("--build", default="build/", help="Build directory containing cases.json")
    p_files.add_argument("--out", default="samples/", help="Output directory for generated files")
    p_files.add_argument("--seed", type=int, default=42, help="Random seed for determinism")

    # Subcommand: seed
    p_seed = subparsers.add_parser("seed", help="Build seed.json from state.json")
    p_seed.add_argument("--build", default="build/", help="Build directory containing state.json")
    p_seed.add_argument("--out", default="samples/seed.json", help="Output path for seed.json")
    p_seed.add_argument("--embedder", default="tfidf", choices=["minilm", "tfidf"], help="Embedding backend")

    # Subcommand: manifest
    p_manifest = subparsers.add_parser("manifest", help="Generate manifest.csv and dataset_report.md")
    p_manifest.add_argument("--build", default="build/", help="Build directory containing cases.json")
    p_manifest.add_argument("--out", default="samples/", help="Output directory containing generated files")
    p_manifest.add_argument("--embedder", default="tfidf", help="Embedding backend used")

    # Subcommand: all
    p_all = subparsers.add_parser("all", help="Generate files, seed, and manifest in one step")
    p_all.add_argument("--build", default="build/", help="Build directory containing state.json and cases.json")
    p_all.add_argument("--out", default="samples/", help="Output directory")
    p_all.add_argument("--seed", type=int, default=42, help="Random seed for determinism")
    p_all.add_argument("--embedder", default="tfidf", help="Embedding backend used")

    # Subcommand: verify
    p_verify = subparsers.add_parser("verify", help="Run end-to-end dataset checks")
    p_verify.add_argument("--out", default="samples/", help="Output directory to verify")
    p_verify.add_argument("--build", default="build/", help="Build directory with cases.json and state.json")

    args = parser.parse_args()

    if args.command == "files":
        cmd_files(args.build, args.out, args.seed)
    elif args.command == "seed":
        cmd_seed(args.build, args.out, args.embedder)
    elif args.command == "manifest":
        cmd_manifest(args.build, args.out, args.embedder)
    elif args.command == "all":
        cmd_all(args.build, args.out, args.seed, args.embedder)
    elif args.command == "verify":
        cmd_verify(args.out, args.build)


if __name__ == "__main__":
    main()
