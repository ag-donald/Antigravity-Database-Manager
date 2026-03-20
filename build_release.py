#!/usr/bin/env python3
"""
Agmercium Recovery Suite — Build Script.

Builds a PEP 441 zipapp (.pyz) that bundles the entire project into a single
portable file. The user only needs Python 3.10+ to run the resulting archive.

Usage:
    python build_release.py
    python build_release.py --dist release/
"""

from __future__ import annotations

import argparse
import os
import shutil
import zipapp


def build_zipapp(dist_dir: str) -> str:
    """
    Build a PEP 441 zipapp (.pyz) that bundles the entire project.
    The user only needs Python 3.10+ to run the resulting file.
    """
    print("[BUILD] Creating zipapp bundle...")

    # Create a staging directory
    staging = os.path.join(dist_dir, "_staging")
    if os.path.exists(staging):
        shutil.rmtree(staging, ignore_errors=True)
        if os.path.exists(staging):
            # Force-remove read-only files (Windows __pycache__)
            for root, dirs, files in os.walk(staging, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    os.chmod(fp, 0o777)
                    os.remove(fp)
                for d in dirs:
                    os.rmdir(os.path.join(root, d))
            os.rmdir(staging)
    os.makedirs(staging)

    # Copy source files (exclude __pycache__ and .pyc files)
    project_root = os.path.dirname(os.path.abspath(__file__))
    shutil.copytree(
        os.path.join(project_root, "src"),
        os.path.join(staging, "src"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copy2(os.path.join(project_root, "antigravity_recover.py"), staging)

    # Create __main__.py for the archive
    main_py = os.path.join(staging, "__main__.py")
    with open(main_py, "w", encoding="utf-8") as f:
        f.write("from antigravity_recover import main\nmain()\n")

    # Build the archive
    output_path = os.path.join(dist_dir, "AgmerciumRecovery.pyz")
    zipapp.create_archive(
        staging,
        target=output_path,
        interpreter="/usr/bin/env python3",
        compressed=True,
    )

    # Clean up staging
    shutil.rmtree(staging, ignore_errors=True)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"[ OK ] {output_path} ({size_kb:.0f} KB)")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Agmercium Recovery — Release Builder")
    parser.add_argument("--dist", default="dist", help="Output directory (default: dist/)")
    args = parser.parse_args()

    dist_dir = os.path.abspath(args.dist)
    os.makedirs(dist_dir, exist_ok=True)

    build_zipapp(dist_dir)

    print("\n[DONE] Build complete.")


if __name__ == "__main__":
    main()
