#!/usr/bin/env python3
"""
Agmercium Recovery Suite — Build Script.

Compiles the project into distributable artifacts for GitHub Releases:
  --zipapp   →  dist/AgmerciumRecovery.pyz  (requires Python 3.8+)
  --binary   →  dist/AgmerciumRecovery[.exe] (standalone, via PyInstaller)

Usage:
    python build_release.py --zipapp
    python build_release.py --binary
    python build_release.py --all
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipapp


def build_zipapp(dist_dir: str) -> str:
    """
    Build a PEP 441 zipapp (.pyz) that bundles the entire project.
    The user only needs Python 3.8+ to run the resulting file.
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

    print(f"[ OK ] {output_path}")
    return output_path


def build_binary(dist_dir: str) -> str:
    """
    Build a standalone binary via PyInstaller.
    Requires PyInstaller to be installed (pip install pyinstaller).
    """
    print("[BUILD] Creating standalone binary via PyInstaller...")

    project_root = os.path.dirname(os.path.abspath(__file__))
    entry = os.path.join(project_root, "antigravity_recover.py")

    try:
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller",
                "--onefile",
                "--console",
                "--name", "AgmerciumRecovery",
                "--distpath", dist_dir,
                "--workpath", os.path.join(dist_dir, "_build"),
                "--specpath", os.path.join(dist_dir, "_build"),
                "--clean",
                entry,
            ],
            check=True,
        )
    except FileNotFoundError:
        print("[ERROR] PyInstaller is not installed.")
        print("        Run:  pip install pyinstaller")
        return ""

    # Determine output name
    ext = ".exe" if sys.platform == "win32" else ""
    output_path = os.path.join(dist_dir, f"AgmerciumRecovery{ext}")

    if os.path.isfile(output_path):
        print(f"[ OK ] {output_path}")
    else:
        print("[ERROR] Build completed but output file not found.")
        output_path = ""

    # Clean up build artifacts
    build_dir = os.path.join(dist_dir, "_build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Agmercium Recovery — Release Builder")
    parser.add_argument("--zipapp", action="store_true", help="Build .pyz zipapp")
    parser.add_argument("--binary", action="store_true", help="Build standalone binary via PyInstaller")
    parser.add_argument("--all", action="store_true", help="Build both zipapp and binary")
    parser.add_argument("--dist", default="dist", help="Output directory (default: dist/)")
    args = parser.parse_args()

    if not (args.zipapp or args.binary or args.all):
        parser.print_help()
        return

    dist_dir = os.path.abspath(args.dist)
    os.makedirs(dist_dir, exist_ok=True)

    if args.zipapp or args.all:
        build_zipapp(dist_dir)

    if args.binary or args.all:
        build_binary(dist_dir)

    print("\n[DONE] Build complete.")


if __name__ == "__main__":
    main()
