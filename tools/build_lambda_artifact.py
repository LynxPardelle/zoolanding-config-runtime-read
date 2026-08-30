#!/usr/bin/env python3
"""Stage Runtime Read sources and package the exact TEST-only release artifact."""

from __future__ import annotations

import argparse
import base64
import hashlib
from pathlib import Path
import shutil
import sys
import zipfile


PROJECT_ROOT = Path(__file__).absolute().parents[1]
BUILD_ROOT = PROJECT_ROOT / ".build"
DEFAULT_ARTIFACT = BUILD_ROOT / "runtime-read"
DEFAULT_RELEASE = PROJECT_ROOT / ".aws-sam" / "release"
RELEASE_ZIP_NAME = "runtime-read.zip"
RELEASE_TEMPLATE_NAME = "template.yaml"
RELEASE_DIGEST_NAME = "lambda-code-sha256.txt"
RUNTIME_FILES = (Path("lambda_function.py"), Path("zoolanding_lambda_common.py"))
EXPECTED_FILES = {path.as_posix() for path in RUNTIME_FILES}
EXPECTED_RELEASE_FILES = {
    RELEASE_ZIP_NAME,
    RELEASE_TEMPLATE_NAME,
    RELEASE_DIGEST_NAME,
}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_FILE_MODE = 0o100644


class ArtifactError(RuntimeError):
    """Raised when the staged artifact violates its public file contract."""


def _is_unsafe_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction()) if callable(is_junction) else False
    except (NotImplementedError, OSError):
        return True


def _assert_safe_path(path: Path, label: str) -> None:
    if _is_unsafe_link(path):
        raise ArtifactError(f"unsafe filesystem link: {label}")


def _assert_within_project(path: Path) -> None:
    _assert_safe_path(PROJECT_ROOT, "project root")
    _assert_safe_path(path, "project path")
    try:
        resolved_project = PROJECT_ROOT.resolve(strict=True)
        resolved_path = path.resolve(strict=False)
        relative_path = resolved_path.relative_to(resolved_project)
    except (OSError, RuntimeError, ValueError) as error:
        raise ArtifactError("project path escapes the project root") from error
    if relative_path == Path("."):
        raise ArtifactError("project root cannot be an artifact target")


def _assert_regular_source(relative_path: Path) -> Path:
    source = PROJECT_ROOT / relative_path
    _assert_safe_path(PROJECT_ROOT, "project root")
    _assert_safe_path(source, f"runtime source {relative_path.as_posix()}")
    _assert_within_project(source)
    if not source.is_file():
        raise ArtifactError(f"invalid runtime source: {relative_path.as_posix()}")
    return source


def _inventory(root: Path) -> set[str]:
    _assert_safe_path(PROJECT_ROOT, "project root")
    _assert_safe_path(root, "artifact root")
    if not root.is_dir():
        raise ArtifactError("artifact directory is missing or unsafe")

    files: set[str] = set()
    directories: list[str] = []
    for path in root.iterdir():
        _assert_safe_path(root, "artifact root")
        relative = path.relative_to(root).as_posix()
        _assert_safe_path(path, f"artifact entry {relative}")
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
        _assert_safe_path(PROJECT_ROOT, "project root")
        _assert_safe_path(artifact, "artifact root")
        _assert_safe_path(source, f"runtime source {relative_path.as_posix()}")
        _assert_safe_path(staged, f"artifact entry {relative_path.as_posix()}")
        if staged.read_bytes() != source.read_bytes():
            raise ArtifactError(f"artifact file differs from source: {relative_path.as_posix()}")


def _prepare_default_artifact() -> None:
    _assert_safe_path(PROJECT_ROOT, "project root")
    _assert_safe_path(BUILD_ROOT, "build root")
    _assert_within_project(BUILD_ROOT)
    if BUILD_ROOT.exists() and not BUILD_ROOT.is_dir():
        raise ArtifactError("build directory is unsafe")
    BUILD_ROOT.mkdir(exist_ok=True)
    _assert_safe_path(BUILD_ROOT, "build root")
    _assert_within_project(BUILD_ROOT)

    _assert_safe_path(DEFAULT_ARTIFACT, "default artifact")
    _assert_within_project(DEFAULT_ARTIFACT)
    if DEFAULT_ARTIFACT.exists():
        _inventory(DEFAULT_ARTIFACT)
        _assert_safe_path(PROJECT_ROOT, "project root")
        _assert_safe_path(BUILD_ROOT, "build root")
        _assert_safe_path(DEFAULT_ARTIFACT, "default artifact")
        _assert_within_project(DEFAULT_ARTIFACT)
        shutil.rmtree(DEFAULT_ARTIFACT)
    _assert_safe_path(PROJECT_ROOT, "project root")
    _assert_safe_path(BUILD_ROOT, "build root")
    _assert_safe_path(DEFAULT_ARTIFACT, "default artifact")
    _assert_within_project(DEFAULT_ARTIFACT)
    DEFAULT_ARTIFACT.mkdir()
    _assert_safe_path(DEFAULT_ARTIFACT, "default artifact")
    _assert_within_project(DEFAULT_ARTIFACT)


def _prepare_empty_directory(directory: Path, label: str) -> None:
    _assert_safe_path(PROJECT_ROOT, "project root")
    _assert_safe_path(directory, label)
    _assert_within_project(directory)
    parent = directory.parent
    _assert_safe_path(parent, f"{label} parent")
    _assert_within_project(parent)
    parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_path(parent, f"{label} parent")
    if directory.exists():
        _inventory(directory)
        _assert_safe_path(directory, label)
        _assert_within_project(directory)
        shutil.rmtree(directory)
    directory.mkdir()
    _assert_safe_path(directory, label)
    _assert_within_project(directory)


def build_artifact() -> None:
    _assert_safe_path(PROJECT_ROOT, "project root")
    sources = [(relative_path, _assert_regular_source(relative_path)) for relative_path in RUNTIME_FILES]
    _prepare_default_artifact()
    for relative_path, source in sources:
        destination = DEFAULT_ARTIFACT / relative_path
        _assert_safe_path(PROJECT_ROOT, "project root")
        _assert_safe_path(BUILD_ROOT, "build root")
        _assert_safe_path(DEFAULT_ARTIFACT, "default artifact")
        _assert_safe_path(source, f"runtime source {relative_path.as_posix()}")
        _assert_safe_path(destination, f"artifact entry {relative_path.as_posix()}")
        _assert_within_project(DEFAULT_ARTIFACT)
        _assert_within_project(destination)
        shutil.copyfile(source, destination)
    verify_artifact(DEFAULT_ARTIFACT)


def _write_reproducible_zip(function_artifact: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, mode="w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for relative_path in sorted(RUNTIME_FILES, key=lambda path: path.as_posix()):
            info = zipfile.ZipInfo(relative_path.as_posix(), date_time=ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = ZIP_FILE_MODE << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, (function_artifact / relative_path).read_bytes())


def _build_test_release_template(template_text: str) -> str:
    transform = "Transform: AWS::Serverless-2016-10-31"
    if template_text.count(transform) != 1 or "AWS::LanguageExtensions" in template_text:
        raise ArtifactError("SAM build template has an unexpected transform contract")

    function_anchor = (
        "  ConfigRuntimeReadFunction:\n"
        "    Type: AWS::Serverless::Function\n"
        "    Properties:\n"
        "      CodeUri: ConfigRuntimeReadFunction\n"
    )
    if template_text.count(function_anchor) != 1:
        raise ArtifactError("SAM build template has an unexpected function contract")

    release_transform = (
        "Transform:\n"
        "- AWS::LanguageExtensions\n"
        "- AWS::Serverless-2016-10-31"
    )
    release_function = (
        "  ConfigRuntimeReadFunction:\n"
        "    Type: AWS::Serverless::Function\n"
        "    Properties:\n"
        f"      CodeUri: {RELEASE_ZIP_NAME}\n"
        "      AutoPublishAlias: live\n"
        "      AutoPublishAliasAllProperties: true\n"
        "      VersionDeletionPolicy: Retain\n"
    )
    return template_text.replace(transform, release_transform).replace(function_anchor, release_function)


def package_test_release(
    function_artifact: Path,
    sam_template: Path,
    release_root: Path = DEFAULT_RELEASE,
) -> None:
    _assert_within_project(function_artifact)
    _assert_within_project(sam_template)
    _assert_within_project(release_root)
    _assert_safe_path(function_artifact, "SAM function artifact")
    _assert_safe_path(sam_template, "SAM build template")
    if not sam_template.is_file():
        raise ArtifactError("SAM build template is missing or unsafe")
    verify_artifact(function_artifact)

    template_text = sam_template.read_text(encoding="utf-8")
    release_template_text = _build_test_release_template(template_text)

    _prepare_empty_directory(release_root, "release root")
    release_zip = release_root / RELEASE_ZIP_NAME
    release_template = release_root / RELEASE_TEMPLATE_NAME
    release_digest = release_root / RELEASE_DIGEST_NAME
    _write_reproducible_zip(function_artifact, release_zip)
    release_template.write_text(
        release_template_text,
        encoding="utf-8",
        newline="\n",
    )
    code_sha256 = base64.b64encode(hashlib.sha256(release_zip.read_bytes()).digest()).decode("ascii")
    release_digest.write_text(f"{code_sha256}\n", encoding="ascii", newline="\n")

    release_files = _inventory(release_root)
    if release_files != EXPECTED_RELEASE_FILES:
        raise ArtifactError("release artifact file contract is invalid")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--verify-artifact",
        type=Path,
        help="verify an existing SAM function artifact instead of staging sources",
    )
    mode.add_argument(
        "--package-test-release",
        dest="package_test_release",
        type=Path,
        help="package a verified SAM function artifact into the exact TEST-only Lambda release",
    )
    parser.add_argument(
        "--sam-template",
        type=Path,
        help="SAM-built template used with --package-test-release",
    )
    args = parser.parse_args()
    if (args.package_test_release is None) != (args.sam_template is None):
        parser.error("--package-test-release and --sam-template must be used together")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.package_test_release is not None:
            package_test_release(args.package_test_release, args.sam_template)
            print("runtime TEST release packaged")
        elif args.verify_artifact is None:
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
