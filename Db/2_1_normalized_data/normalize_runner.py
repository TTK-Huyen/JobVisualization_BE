#!/usr/bin/env python3
"""CLI wrapper to run the normalize controller.

Usage:
  python normalize_runner.py --input extracted.json --output normalized.json --fallback fallback.json
"""
from pathlib import Path
import argparse
import sys

from normalize_controller import run_normalize


def main():
    parser = argparse.ArgumentParser(description="Run normalization controller")
    parser.add_argument("--input", required=True, help="Path to extracted input JSON")
    parser.add_argument("--output", required=True, help="Path to write normalized JSON")
    parser.add_argument("--fallback", required=True, help="Path to write fallback JSON")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    fallback_path = Path(args.fallback)

    if not input_path.exists():
        print(f"Input not found: {input_path}")
        sys.exit(2)

    try:
        run_normalize(str(input_path), str(output_path), str(fallback_path))
    except Exception as e:
        print(f"Normalize failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
