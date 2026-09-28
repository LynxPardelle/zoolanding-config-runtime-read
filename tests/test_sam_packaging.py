import ast
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "build_lambda_artifact.py"
STAGED_ARTIFACT = ROOT / ".build" / "runtime-read"
EXPECTED_RUNTIME_FILES = {"lambda_function.py", "zoolanding_lambda_common.py"}


def load_builder_module():
    spec = importlib.util.spec_from_file_location("runtime_read_artifact_builder", BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("builder module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inventory(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


class SamPackagingTests(unittest.TestCase):
    def run_builder(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BUILDER), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_template_uses_the_allowlisted_runtime_directory(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")

        self.assertIn("CodeUri: .build/runtime-read", template)
        self.assertNotIn("CodeUri: .\n", template)

    def test_shared_template_keeps_production_on_the_existing_unaliased_path(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        function_start = template.index("  ConfigRuntimeReadFunction:")
        function_end = template.index("\nOutputs:", function_start)
        function = template[function_start:function_end]

        self.assertNotIn("AutoPublishAlias", function)
        self.assertNotIn("VersionDeletionPolicy", function)
        self.assertNotIn("AutoPublishCodeSha256", function)
        self.assertIn("Transform: AWS::Serverless-2016-10-31", template)
        self.assertNotIn("AWS::LanguageExtensions", template)

    def test_release_zip_is_reproducible_exact_and_uses_lambda_code_digest(self):
        module = load_builder_module()
        package_release = getattr(module, "package_test_release", None)

        self.assertIsNotNone(package_release)
        if package_release is None:
            return

        (ROOT / ".build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / ".build") as directory:
            temp_root = Path(directory)
            function_root = temp_root / "ConfigRuntimeReadFunction"
            function_root.mkdir()
            for relative_path in reversed(sorted(EXPECTED_RUNTIME_FILES)):
                shutil.copyfile(ROOT / relative_path, function_root / relative_path)

            built_template = temp_root / "template.yaml"
            built_template.write_text(
                "Transform: AWS::Serverless-2016-10-31\n"
                "Resources:\n"
                "  ConfigRuntimeReadFunction:\n"
                "    Type: AWS::Serverless::Function\n"
                "    Properties:\n"
                "      CodeUri: ConfigRuntimeReadFunction\n",
                encoding="utf-8",
            )

            release_one = temp_root / "release-one"
            package_release(function_root, built_template, release_one)
            zip_one = (release_one / "runtime-read.zip").read_bytes()

            for relative_path in EXPECTED_RUNTIME_FILES:
                os.utime(function_root / relative_path, (1_900_000_000, 1_900_000_000))

            release_two = temp_root / "release-two"
            package_release(function_root, built_template, release_two)
            zip_two = (release_two / "runtime-read.zip").read_bytes()

            self.assertEqual(zip_one, zip_two)
            expected_digest = base64.b64encode(hashlib.sha256(zip_one).digest()).decode("ascii")
            self.assertEqual(
                expected_digest,
                (release_one / "lambda-code-sha256.txt").read_text(encoding="ascii").strip(),
            )
            release_template = (release_one / "template.yaml").read_text(encoding="utf-8")
            self.assertIn("CodeUri: runtime-read.zip", release_template)
            self.assertIn(
                "Transform:\n- AWS::LanguageExtensions\n- AWS::Serverless-2016-10-31",
                release_template,
            )
            self.assertIn("      AutoPublishAlias: live", release_template)
            self.assertIn("      AutoPublishAliasAllProperties: true", release_template)
            self.assertIn("      VersionDeletionPolicy: Retain", release_template)

            with zipfile.ZipFile(release_one / "runtime-read.zip") as archive:
                self.assertEqual(sorted(EXPECTED_RUNTIME_FILES), archive.namelist())
                for info in archive.infolist():
                    self.assertEqual((1980, 1, 1, 0, 0, 0), info.date_time)
                    self.assertEqual(zipfile.ZIP_STORED, info.compress_type)
                    self.assertEqual(0o100644, info.external_attr >> 16)
                    self.assertEqual((ROOT / info.filename).read_bytes(), archive.read(info.filename))

    def test_runtime_allowlist_covers_every_local_python_import(self):
        local_dependencies: set[str] = set()
        for relative_path in EXPECTED_RUNTIME_FILES:
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".", 1)[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module.split(".", 1)[0]]
                else:
                    continue
                for module in modules:
                    candidate = ROOT / f"{module}.py"
                    if candidate.is_file():
                        local_dependencies.add(candidate.relative_to(ROOT).as_posix())

        self.assertLessEqual(local_dependencies, EXPECTED_RUNTIME_FILES)

    def test_builder_stages_only_the_two_runtime_files(self):
        result = self.run_builder()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(EXPECTED_RUNTIME_FILES, inventory(STAGED_ARTIFACT))
        for relative_path in EXPECTED_RUNTIME_FILES:
            self.assertEqual(
                (ROOT / relative_path).read_bytes(),
                (STAGED_ARTIFACT / relative_path).read_bytes(),
            )

    def test_unsafe_link_helper_detects_junctions_portably(self):
        module = load_builder_module()
        helper = getattr(module, "_is_unsafe_link", None)

        self.assertIsNotNone(helper)
        if helper is None:
            return

        junction = Mock(spec=["is_symlink", "is_junction"])
        junction.is_symlink.return_value = False
        junction.is_junction.return_value = True
        self.assertTrue(helper(junction))

        symlink = Mock(spec=["is_symlink"])
        symlink.is_symlink.return_value = True
        self.assertTrue(helper(symlink))

        regular_path = Mock(spec=["is_symlink"])
        regular_path.is_symlink.return_value = False
        self.assertFalse(helper(regular_path))

    def test_delete_containment_rejects_paths_outside_project(self):
        module = load_builder_module()
        containment = getattr(module, "_assert_within_project", None)

        self.assertIsNotNone(containment)
        if containment is None:
            return

        containment(ROOT / ".build" / "runtime-read")
        with self.assertRaises(module.ArtifactError):
            containment(ROOT.parent / "runtime-read-outside-project")

    def test_mocked_junction_is_rejected_before_rmtree(self):
        module = load_builder_module()
        helper = getattr(module, "_is_unsafe_link", None)

        self.assertIsNotNone(helper)
        if helper is None:
            return

        with (
            patch.object(
                module,
                "_is_unsafe_link",
                side_effect=lambda path: path == module.DEFAULT_ARTIFACT,
            ),
            patch.object(module.shutil, "rmtree") as rmtree,
        ):
            with self.assertRaises(module.ArtifactError):
                module._prepare_default_artifact()
            rmtree.assert_not_called()

    @unittest.skipUnless(
        os.name == "nt" and hasattr(Path, "is_junction"),
        "real directory junctions require Windows and pathlib junction support",
    )
    def test_verifier_rejects_a_real_windows_junction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            junction = root / "junction"
            target.mkdir()
            for relative_path in EXPECTED_RUNTIME_FILES:
                shutil.copyfile(ROOT / relative_path, target / relative_path)

            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest("Windows refused junction creation in this environment")

            try:
                self.assertTrue(junction.is_junction())
                rejected = self.run_builder("--verify-artifact", str(junction))
                self.assertNotEqual(0, rejected.returncode)
                self.assertIn("unsafe", rejected.stderr)
            finally:
                if junction.is_junction():
                    junction.rmdir()

    def test_verifier_rejects_extra_missing_or_modified_sam_function_files(self):
        result = self.run_builder()
        self.assertEqual(0, result.returncode, result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            function_root = Path(directory) / ".aws-sam" / "build" / "ConfigRuntimeReadFunction"
            function_root.mkdir(parents=True)
            for relative_path in EXPECTED_RUNTIME_FILES:
                shutil.copyfile(ROOT / relative_path, function_root / relative_path)

            verified = self.run_builder("--verify-artifact", str(function_root))
            self.assertEqual(0, verified.returncode, verified.stderr)

            (function_root / "unexpected.py").write_text("raise RuntimeError\n", encoding="utf-8")
            rejected = self.run_builder("--verify-artifact", str(function_root))
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("unexpected artifact files: unexpected.py", rejected.stderr)

            (function_root / "unexpected.py").unlink()
            (function_root / "lambda_function.py").unlink()
            rejected = self.run_builder("--verify-artifact", str(function_root))
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("missing artifact files: lambda_function.py", rejected.stderr)

            shutil.copyfile(ROOT / "lambda_function.py", function_root / "lambda_function.py")
            (function_root / "zoolanding_lambda_common.py").write_text("# modified\n", encoding="utf-8")
            rejected = self.run_builder("--verify-artifact", str(function_root))
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn(
                "artifact file differs from source: zoolanding_lambda_common.py",
                rejected.stderr,
            )

    def test_ci_and_validation_jobs_build_and_verify_the_exact_sam_artifact(self):
        package_command = (
            "python tools/build_lambda_artifact.py --package-test-release "
            ".aws-sam/build/ConfigRuntimeReadFunction "
            "--sam-template .aws-sam/build/template.yaml"
        )
        for workflow_name in ("ci.yml", "deploy-test.yml", "deploy-production.yml"):
            with self.subTest(workflow=workflow_name):
                workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
                self.assertIn("python tools/build_lambda_artifact.py", workflow)
                self.assertIn("sam build --no-cached", workflow)
                self.assertIn(
                    "python tools/build_lambda_artifact.py --verify-artifact "
                    ".aws-sam/build/ConfigRuntimeReadFunction",
                    workflow,
                )
                build = workflow.index("python tools/build_lambda_artifact.py")
                sam_build = workflow.index("sam build --no-cached", build)
                verify = workflow.index(
                    "python tools/build_lambda_artifact.py --verify-artifact "
                    ".aws-sam/build/ConfigRuntimeReadFunction",
                    sam_build,
                )
                self.assertLess(build, sam_build)
                self.assertLess(sam_build, verify)
                if workflow_name == "deploy-production.yml":
                    self.assertNotIn(package_command, workflow)
                else:
                    package = workflow.index(package_command, verify)
                    self.assertLess(verify, package)

    def test_workflows_restore_exact_revision_after_tests_before_build(self):
        checkout = "uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd"
        for workflow_name in ("ci.yml", "deploy-test.yml", "deploy-production.yml"):
            with self.subTest(workflow=workflow_name):
                workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
                tests = workflow.index('python -m unittest discover -s tests -p "test_*.py"')
                build = workflow.index("python tools/build_lambda_artifact.py", tests)
                restored = workflow.rfind(checkout, tests, build)

                self.assertGreater(restored, tests)
                restore_step = workflow[restored:build]
                self.assertIn("ref: ${{ github.sha }}", restore_step)
                self.assertIn("clean: true", restore_step)
                self.assertIn("fetch-depth: 0", restore_step)
                self.assertIn("persist-credentials: false", restore_step)

    def test_build_directory_and_public_artifact_contract_are_documented(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(".build/", gitignore)
        self.assertIn("`.build/runtime-read`", readme)
        self.assertIn("only `lambda_function.py` and `zoolanding_lambda_common.py`", readme)


if __name__ == "__main__":
    unittest.main()
