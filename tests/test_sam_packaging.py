import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "build_lambda_artifact.py"
STAGED_ARTIFACT = ROOT / ".build" / "runtime-read"
EXPECTED_RUNTIME_FILES = {"lambda_function.py", "zoolanding_lambda_common.py"}


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

    def test_build_directory_and_public_artifact_contract_are_documented(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(".build/", gitignore)
        self.assertIn("`.build/runtime-read`", readme)
        self.assertIn("only `lambda_function.py` and `zoolanding_lambda_common.py`", readme)


if __name__ == "__main__":
    unittest.main()
