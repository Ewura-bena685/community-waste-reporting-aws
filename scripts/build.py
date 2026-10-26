"""Copies each function in functions/<name>/ into build/<name>/ for Lambda (Python 3.13).

Tests are left out. Packages in requirements.txt (if any) are installed into every function, built for
Lambda's Arm (arm64) runtime. boto3 comes with the Lambda runtime, so it doesn't need to be listed.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
FUNCTIONS = ROOT / "functions"


def requirements() -> list[str]:
    path = ROOT / "requirements.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [line for line in (raw.split("#")[0].strip() for raw in lines) if line]


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    functions = sorted(p for p in FUNCTIONS.iterdir() if (p / "index.py").exists()) if FUNCTIONS.exists() else []  # skips __pycache__ etc.
    for fn in functions:
        out = BUILD / fn.name
        shutil.copytree(fn, out, ignore=shutil.ignore_patterns("test_*.py", "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache"))
        if requirements():
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(out), "--platform", "manylinux2014_aarch64",
                 "--implementation", "cp", "--python-version", "3.13", "--only-binary=:all:", "-r", str(ROOT / "requirements.txt")],
                check=True,
            )
        print(f"Built {fn.name}")
    print(f"Built {len(functions)} function(s) into build/")


if __name__ == "__main__":
    main()
