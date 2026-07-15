#!/usr/bin/env python3
"""Stage and verify the exact Runtime Read Lambda source artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / ".build"
DEFAULT_ARTIFACT = BUILD_ROOT / "runtime-read"
RUNTIME_FILES = (Path("lambda_function.py"), Path("zoolanding_lambda_common.py"))
EXPECTED_FILES = {path.as_posix() for path in RUNTIME_FILES}


class ArtifactError(RuntimeError):
    """Raised when the staged artifact violates its public file contract."""


def _assert_regular_source(relative_path: Path) -> Path:
    source = PROJECT_ROOT / relative_path
    if source.is_symlink() or not source.is_file():
        raise ArtifactError(f"invalid runtime source: {relative_path.as_posix()}")
    return source


def _inventory(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("artifact directory is missing or unsafe")

    files: set[str] = set()
    directories: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ArtifactError(f"artifact symlink is not allowed: {relative}")
        if path.is_dir():
            directories.append(relative)
        elif path.is_file():
            files.add(relative)
        else:
            raise ArtifactError(f"unsupported artifact entry: {relative}")

    if directories:
        raise ArtifactError(f"unexpected artifact directories: {', '.join(sorted(directories))}")
    return files


def verify_artifact(artifact: Path) -> None:
    files = _inventory(artifact)
    unexpected = sorted(files - EXPECTED_FILES)
    missing = sorted(EXPECTED_FILES - files)
    if unexpected:
        raise ArtifactError(f"unexpected artifact files: {', '.join(unexpected)}")
    if missing:
        raise ArtifactError(f"missing artifact files: {', '.join(missing)}")

    for relative_path in RUNTIME_FILES:
        source = _assert_regular_source(relative_path)
        staged = artifact / relative_path
        if staged.read_bytes() != source.read_bytes():
            raise ArtifactError(f"artifact file differs from source: {relative_path.as_posix()}")


def _prepare_default_artifact() -> None:
    if BUILD_ROOT.is_symlink() or (BUILD_ROOT.exists() and not BUILD_ROOT.is_dir()):
        raise ArtifactError("build directory is unsafe")
    BUILD_ROOT.mkdir(exist_ok=True)

    if DEFAULT_ARTIFACT.is_symlink():
        raise ArtifactError("artifact directory is unsafe")
    if DEFAULT_ARTIFACT.exists():
        _inventory(DEFAULT_ARTIFACT)
        shutil.rmtree(DEFAULT_ARTIFACT)
    DEFAULT_ARTIFACT.mkdir()


def build_artifact() -> None:
    sources = [(relative_path, _assert_regular_source(relative_path)) for relative_path in RUNTIME_FILES]
    _prepare_default_artifact()
    for relative_path, source in sources:
        shutil.copyfile(source, DEFAULT_ARTIFACT / relative_path)
    verify_artifact(DEFAULT_ARTIFACT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-artifact",
        type=Path,
        help="verify an existing SAM function artifact instead of staging sources",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.verify_artifact is None:
            build_artifact()
            print("runtime artifact staged")
        else:
            verify_artifact(args.verify_artifact)
            print("runtime artifact verified")
    except (ArtifactError, OSError) as error:
        print(f"artifact_error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
