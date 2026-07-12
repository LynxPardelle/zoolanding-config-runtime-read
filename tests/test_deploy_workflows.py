import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeployWorkflowTests(unittest.TestCase):
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
            "deploy-dev.yml": "dev",
            "deploy-test.yml": "test",
            "deploy-production.yml": "prod",
        }

        for workflow_name, config_env in expected_config_envs.items():
            with self.subTest(workflow=workflow_name):
                workflow = REPO_ROOT / ".github" / "workflows" / workflow_name
                text = workflow.read_text(encoding="utf-8")
                self.assertIn(f"sam deploy --config-env {config_env}", text)
                self.assertNotIn("--parameter-overrides", text)

    def test_template_allows_slug_pointer_reads_on_content_hub_tables(self):
        text = (REPO_ROOT / "template.yaml").read_text(encoding="utf-8")

        for parameter_name in (
            "ContentHubMetadataTableName",
            "ContentHubMetadataTableNameDev",
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


if __name__ == "__main__":
    unittest.main()
