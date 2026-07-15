import pathlib
import subprocess
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeployWorkflowTests(unittest.TestCase):
    def test_dev_is_local_only_and_has_no_sam_deploy_profile(self):
        samconfig = (REPO_ROOT / "samconfig.toml").read_text(encoding="utf-8")
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        workflows_dir = REPO_ROOT / ".github" / "workflows"
        workflow_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(workflows_dir.glob("*.yml"))
        )
        deploy_environments = {
            line.removeprefix("[").removesuffix(".deploy.parameters]")
            for line in samconfig.splitlines()
            if line.startswith("[") and line.endswith(".deploy.parameters]")
        }

        self.assertIn("[test.deploy.parameters]", samconfig)
        self.assertIn("[prod.deploy.parameters]", samconfig)
        self.assertEqual(deploy_environments, {"default", "test", "prod"})
        self.assertNotRegex(samconfig, r"(?m)^\[dev\.")
        self.assertFalse((workflows_dir / "deploy-dev.yml").exists())
        self.assertNotIn("--config-env dev", workflow_text)
        self.assertNotIn("Pushes to `dev`, `test`, and `main` trigger AWS deployment workflows", readme)
        self.assertNotIn("includes `dev`, `test`, and `prod` deployment profiles", readme)
        self.assertNotRegex(readme, r"(?m)^- `dev` uses ")
        self.assertIn("Pushes to `dev` run CI only", readme)

    def test_ci_runs_the_audited_node_promotion_contract(self):
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("actions/setup-node@v5", text)
        setup_node = text.index("actions/setup-node@v5")
        unit_tests = text.index('python -m unittest discover -s tests -p "test_*.py"')

        self.assertLess(setup_node, unit_tests)
        self.assertIn("node-version: '22'", text)

        result = subprocess.run(
            ["node", "--test", "tests/promotion_provenance.spec.mjs"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_promotion_verifier_matches_the_audited_hub_blob(self):
        verifier = REPO_ROOT / "tools" / "verify-promotion-commit.mjs"
        self.assertTrue(verifier.is_file())

        result = subprocess.run(
            ["git", "hash-object", "--path=tools/verify-promotion-commit.mjs", str(verifier)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "dcbdf1a3a3ac5422ff09870a060ceddb4c109e5d")

    def test_ci_guard_uses_environment_indirection_for_github_refs(self):
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        for variable, expression in (
            ("EVENT_NAME", "github.event_name"),
            ("BASE_REF", "github.base_ref"),
            ("HEAD_REF", "github.head_ref"),
        ):
            with self.subTest(variable=variable):
                self.assertIn(f"{variable}: ${{{{ {expression} }}}}", text)

        self.assertIn('if [[ "$EVENT_NAME" != "pull_request" ]]', text)
        self.assertIn('base="$BASE_REF"', text)
        self.assertIn('head="$HEAD_REF"', text)
        self.assertNotIn('if [[ "${{ github.event_name }}"', text)
        self.assertNotIn('base="${{ github.base_ref }}"', text)
        self.assertNotIn('head="${{ github.head_ref }}"', text)

    def test_deploy_workflows_do_not_override_samconfig_parameters(self):
        expected_config_envs = {
            "deploy-test.yml": "test",
            "deploy-production.yml": "prod",
        }

        for workflow_name, config_env in expected_config_envs.items():
            with self.subTest(workflow=workflow_name):
                workflow = REPO_ROOT / ".github" / "workflows" / workflow_name
                text = workflow.read_text(encoding="utf-8")
                self.assertIn(f"sam deploy --config-env {config_env}", text)
                self.assertNotIn("--parameter-overrides", text)

    def test_deploy_workflows_require_exact_merged_pr_provenance(self):
        cases = {
            "deploy-test.yml": ("dev", "test", "test"),
            "deploy-production.yml": ("test", "main", "production"),
        }

        for workflow_name, (source_branch, target_branch, environment_name) in cases.items():
            with self.subTest(workflow=workflow_name):
                text = (REPO_ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
                jobs_index = text.index("\njobs:")
                top_level = text[:jobs_index]
                deploy_index = text.index("\n  deploy:")
                exact_command = (
                    f"node tools/verify-promotion-commit.mjs --source={source_branch} --target={target_branch}"
                )

                self.assertIn("workflow_dispatch:", text)
                self.assertIn("contents: read", top_level)
                self.assertIn("pull-requests: read", top_level)
                self.assertNotIn("id-token: write", top_level)
                self.assertIn("concurrency:", top_level)
                self.assertIn(
                    f"group: runtime-read-{environment_name}-${{{{ github.repository }}}}-${{{{ github.ref }}}}",
                    top_level,
                )
                self.assertIn("cancel-in-progress: false", top_level)
                self.assertNotIn("cancel-in-progress: true", text)
                self.assertNotIn("concurrency:", text[deploy_index:])
                self.assertEqual(text.count(exact_command), 2)
                self.assertNotIn("--tip-only=true", text)
                self.assertLess(text.index("actions/setup-node@v5"), text.index(exact_command))
                self.assertNotIn("rev-list --parents", text)
                self.assertNotIn("merge-base --is-ancestor", text)
                self.assertNotIn("HEAD^2", text)
                self.assertIn(f"environment: {environment_name}", text[deploy_index:])
                self.assertIn("id-token: write", text[deploy_index:])
                self.assertIn("pull-requests: read", text[deploy_index:])
                self.assertIn("persist-credentials: false", text[deploy_index:])
                self.assertIn("fetch-depth: 0", text[deploy_index:])
                self.assertIn("test \"$(git rev-parse HEAD)\" = \"$EXPECTED_SHA\"", text[deploy_index:])

                first_verifier = text.index(exact_command)
                second_verifier = text.index(exact_command, first_verifier + len(exact_command))
                rebuild = text.index("- name: Rebuild validated commit", deploy_index)
                credentials = text.index("aws-actions/configure-aws-credentials@v6", deploy_index)
                credentials_step = text.rfind("\n      - uses:", second_verifier, credentials)
                self.assertLess(rebuild, second_verifier)
                self.assertLess(second_verifier, credentials_step)
                self.assertNotIn("\n      - ", text[second_verifier + len(exact_command):credentials_step])

    def test_template_allows_slug_pointer_reads_on_content_hub_tables(self):
        text = (REPO_ROOT / "template.yaml").read_text(encoding="utf-8")

        for parameter_name in (
            "ContentHubMetadataTableName",
            "ContentHubMetadataTableNameTest",
            "ContentHubMetadataTableNameProd",
        ):
            with self.subTest(parameter=parameter_name):
                table_reference = f"table/${{{parameter_name}}}"
                reference_index = text.find(table_reference)
                self.assertNotEqual(reference_index, -1)
                preceding_policy = text[max(0, reference_index - 220):reference_index]
                self.assertIn("dynamodb:GetItem", preceding_policy)
                self.assertIn("dynamodb:Query", preceding_policy)

    def test_template_denies_canonical_server_objects_before_the_bucket_allow(self):
        text = (REPO_ROOT / "template.yaml").read_text(encoding="utf-8")
        deny_resource = "Fn::Sub: arn:aws:s3:::${ConfigPayloadsBucketName}/*/server/*"
        allow_resource = "Fn::Sub: arn:aws:s3:::${ConfigPayloadsBucketName}/*"

        self.assertIn(deny_resource, text)
        deny_index = text.index(deny_resource)
        allow_index = text.index(allow_resource, deny_index + len(deny_resource))
        deny_statement = text[max(0, deny_index - 180):deny_index]

        self.assertLess(deny_index, allow_index)
        self.assertIn("Effect: Deny", deny_statement)
        self.assertIn("s3:GetObject", deny_statement)

    def test_template_allows_bucket_metadata_for_missing_optional_payloads(self):
        text = (REPO_ROOT / "template.yaml").read_text(encoding="utf-8")
        list_bucket_statement = """            - Effect: Allow
              Action:
                - s3:ListBucket
              Resource:
                Fn::Sub: arn:aws:s3:::${ConfigPayloadsBucketName}"""

        self.assertIn(list_bucket_statement, text)

    def test_server_only_iam_case_boundary_and_future_hardening_are_documented(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("case-sensitive", text)
        self.assertIn("case-insensitive application guard", text)
        self.assertIn("403 Access Denied", text)
        self.assertIn("404 Not Found", text)
        self.assertIn("separate public and server-only prefixes or buckets", text)

    def test_manual_smoke_uses_verified_test_pilot_and_documents_rendered_404(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        start = text.index("## Manual smoke test")
        end = text.index("## Content hub runtime metadata", start)
        smoke = text[start:end]

        self.assertIn("test.zoositioweb.com.mx", smoke)
        self.assertNotIn("test.zoolandingpage.com.mx", smoke)
        self.assertIn("HTTP `200`", smoke)
        self.assertIn("`metadata.statusCode` is `404`", smoke)
        self.assertIn("`metadata.notFound` is `true`", smoke)
        self.assertIn("does not expose a server descriptor", smoke)


if __name__ == "__main__":
    unittest.main()
