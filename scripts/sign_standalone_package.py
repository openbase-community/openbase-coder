#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Code sign Mach-O files in an Openbase Coder package."
    )
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print files that would be signed without calling codesign.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir.resolve()
    if not package_dir.is_dir():
        raise RuntimeError(f"Package directory not found: {package_dir}")

    files = list(macho_files(package_dir))
    if not files:
        print("No Mach-O files found to sign.")
        return 0

    for path in files:
        if args.dry_run:
            print(path)
            continue
        sign_file(path, args.identity)
        print(f"Signed {path}")

    return 0


def macho_files(package_dir: Path):
    candidates = sorted(
        (
            path
            for path in package_dir.rglob("*")
            if could_be_macho(path)
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in candidates:
        result = subprocess.run(
            ["file", "-b", str(path)],
            check=True,
            capture_output=True,
            errors="replace",
            text=True,
        )
        if "Mach-O" in result.stdout:
            yield path


def could_be_macho(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    if os.access(path, os.X_OK):
        return True
    if path.suffix in {".dylib", ".so", ".bundle"}:
        return True
    return any(suffix.endswith(".so") for suffix in path.suffixes)


def sign_file(path: Path, identity: str) -> None:
    subprocess.run(
        [
            "codesign",
            "--force",
            "--timestamp",
            "--options",
            "runtime",
            "--sign",
            identity,
            str(path),
        ],
        check=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
