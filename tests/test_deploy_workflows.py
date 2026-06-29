import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeployWorkflowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
