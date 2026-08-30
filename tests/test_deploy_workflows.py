import pathlib
import re
import shlex
import subprocess
import tomllib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

CHECKOUT_ACTION = "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd"
SETUP_NODE_ACTION = "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444"
SETUP_PYTHON_ACTION = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
SETUP_SAM_ACTION = "aws-actions/setup-sam@89ddb14d60e682855e3fea4be85b3c56485de310"
UPLOAD_ARTIFACT_ACTION = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWNLOAD_ARTIFACT_ACTION = "actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131"
GITHUB_SCRIPT_ACTION = "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd"
CONFIGURE_AWS_ACTION = "aws-actions/configure-aws-credentials@517a711dbcd0e402f90c77e7e2f81e849156e31d"
VERIFIER_BLOB = "a1e369e4e6d7a24b3595e5604a6fddab51af526d"


def deploy_script(workflow_text):
    marker = "      - name: Deploy "
    start = workflow_text.rindex(marker)
    run_marker = "        run: |\n"
    run_line = "        run: "
    if run_marker not in workflow_text[start:]:
        line_start = workflow_text.index(run_line, start) + len(run_line)
        return workflow_text[line_start:].splitlines()[0]
    script_start = workflow_text.index(run_marker, start) + len(run_marker)
    lines = []
    for line in workflow_text[script_start:].splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line else "")
    return "\n".join(lines).strip()


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

    def test_runtime_execution_boundary_is_required_for_every_deploy_profile(self):
        template = (REPO_ROOT / "template.yaml").read_text(encoding="utf-8")
        parameter_start = template.index("  RuntimeExecutionBoundaryArn:")
        parameter_end = template.index("\nConditions:", parameter_start)
        parameter_block = template[parameter_start:parameter_end]

        self.assertIn("    Type: String", parameter_block)
        self.assertNotIn("Default:", parameter_block)
        self.assertIn(
            "      PermissionsBoundary:\n        Ref: RuntimeExecutionBoundaryArn",
            template,
        )

        expected_boundary_arns = {
            "default": (
                "arn:aws:iam::765932874577:policy/"
                "zoolanding-config-runtime-read-production-execution-boundary"
            ),
            "test": (
                "arn:aws:iam::765932874577:policy/"
                "zoolanding-config-runtime-read-test-execution-boundary"
            ),
            "prod": (
                "arn:aws:iam::765932874577:policy/"
                "zoolanding-config-runtime-read-production-execution-boundary"
            ),
        }
        with (REPO_ROOT / "samconfig.toml").open("rb") as handle:
            samconfig = tomllib.load(handle)

        for config_env, boundary_arn in expected_boundary_arns.items():
            with self.subTest(config_env=config_env):
                overrides = samconfig[config_env]["deploy"]["parameters"]["parameter_overrides"]
                self.assertEqual(
                    [value for value in overrides if value.startswith("RuntimeExecutionBoundaryArn=")],
                    [f"RuntimeExecutionBoundaryArn={boundary_arn}"],
                )

    def test_ci_runs_the_audited_node_promotion_contract(self):
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn(CHECKOUT_ACTION, text)
        self.assertIn(SETUP_NODE_ACTION, text)
        self.assertIn(SETUP_PYTHON_ACTION, text)
        self.assertIn(SETUP_SAM_ACTION, text)
        self.assertIn("version: 1.163.0", text)
        setup_node = text.index(SETUP_NODE_ACTION)
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

    def test_promotion_verifier_matches_the_audited_blob(self):
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
        self.assertEqual(result.stdout.strip(), VERIFIER_BLOB)
        verifier_text = verifier.read_text(encoding="utf-8")
        self.assertNotIn("tip-only", verifier_text)
        self.assertIn("parents[0] !== pullRequest.base.sha", verifier_text)
        self.assertIn("parents[1] !== pullRequest.head.sha", verifier_text)
        self.assertIn("const finalTargetTipSha = await fetchTargetBranchSha", verifier_text)

    def test_all_workflow_actions_are_sha_pinned(self):
        for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            for reference in re.findall(r"(?m)^\s+(?:-\s+)?uses:\s+([^\s#]+)", text):
                with self.subTest(workflow=workflow.name, reference=reference):
                    self.assertRegex(reference, r"@[a-f0-9]{40}$")

    def test_ci_guard_uses_environment_indirection_for_github_refs(self):
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        for variable, expression in (
            ("EVENT_NAME", "github.event_name"),
            ("BASE_REF", "github.base_ref"),
            ("HEAD_REF", "github.head_ref"),
            ("HEAD_REPO", "github.event.pull_request.head.repo.full_name"),
            ("REPOSITORY", "github.repository"),
        ):
            with self.subTest(variable=variable):
                self.assertIn(f"{variable}: ${{{{ {expression} }}}}", text)

        self.assertIn('if [[ "$EVENT_NAME" != "pull_request" ]]', text)
        self.assertIn('base="$BASE_REF"', text)
        self.assertIn('head="$HEAD_REF"', text)
        self.assertIn('if [[ "$base" == "test" || "$base" == "main" ]]', text)
        self.assertIn('[[ "$HEAD_REPO" != "$REPOSITORY" ]]', text)
        self.assertNotIn('if [[ "${{ github.event_name }}"', text)
        self.assertNotIn('base="${{ github.base_ref }}"', text)
        self.assertNotIn('head="${{ github.head_ref }}"', text)

    def test_deploy_workflows_reproduce_samconfig_with_explicit_parameters(self):
        expected_config_envs = {
            "deploy-test.yml": ("test", ".aws-sam/release/template.yaml"),
            "deploy-production.yml": ("prod", ".aws-sam/build/template.yaml"),
        }

        with (REPO_ROOT / "samconfig.toml").open("rb") as handle:
            samconfig = tomllib.load(handle)

        for workflow_name, (config_env, template_path) in expected_config_envs.items():
            with self.subTest(workflow=workflow_name):
                workflow = REPO_ROOT / ".github" / "workflows" / workflow_name
                text = workflow.read_text(encoding="utf-8")
                parameters = samconfig[config_env]["deploy"]["parameters"]
                self.assertEqual(
                    {
                        "stack_name",
                        "resolve_s3",
                        "s3_prefix",
                        "region",
                        "confirm_changeset",
                        "capabilities",
                        "parameter_overrides",
                    },
                    set(parameters),
                )
                self.assertIs(parameters["resolve_s3"], True)
                self.assertIs(parameters["confirm_changeset"], False)
                command = deploy_script(text).replace("\\\n", " ")
                tokens = shlex.split(command)
                expected_before_parameters = [
                    "sam", "deploy",
                    "--template-file", template_path,
                    "--stack-name", parameters["stack_name"],
                    "--region", parameters["region"],
                    "--resolve-s3",
                    "--s3-prefix", parameters["s3_prefix"],
                    "--capabilities", parameters["capabilities"],
                    "--role-arn", "$AWS_CLOUDFORMATION_ROLE_ARN",
                    "--no-confirm-changeset",
                    "--no-fail-on-empty-changeset",
                    "--parameter-overrides",
                ]
                self.assertEqual(tokens[:len(expected_before_parameters)], expected_before_parameters)
                self.assertEqual(tokens[len(expected_before_parameters):], parameters["parameter_overrides"])
                self.assertNotIn("--config-env", tokens)

    def test_deploy_workflows_require_exact_merged_pr_provenance(self):
        cases = {
            "deploy-test.yml": (
                "dev",
                "test",
                "test",
                "arn:aws:iam::765932874577:role/"
                "zoolanding-config-runtime-read-test-cfn-exec",
            ),
            "deploy-production.yml": (
                "test",
                "main",
                "production",
                "arn:aws:iam::765932874577:role/"
                "zoolanding-config-runtime-read-production-cfn-exec",
            ),
        }
        inline_verifiers = []

        for workflow_name, (
            source_branch,
            target_branch,
            environment_name,
            expected_cloudformation_role_arn,
        ) in cases.items():
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
                self.assertIn("AWS_DEFAULT_REGION: us-east-1", top_level)
                self.assertIn("AWS_REGION: us-east-1", top_level)
                self.assertIn("SAM_CLI_TELEMETRY: 0", top_level)
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
                for action in (
                    CHECKOUT_ACTION,
                    SETUP_NODE_ACTION,
                    SETUP_PYTHON_ACTION,
                    SETUP_SAM_ACTION,
                    UPLOAD_ARTIFACT_ACTION,
                ):
                    self.assertIn(action, text[:deploy_index])
                self.assertNotIn("rev-list --parents", text)
                self.assertNotIn("merge-base --is-ancestor", text)
                self.assertNotIn("HEAD^2", text)
                self.assertIn(f"environment: {environment_name}", text[deploy_index:])
                self.assertIn("id-token: write", text[deploy_index:])
                self.assertIn("pull-requests: read", text[deploy_index:])

                first_verifier = text.index(exact_command)
                second_verifier = text.index(exact_command, first_verifier + len(exact_command))
                validate_section = text[text.index("\n  validate:"):deploy_index]
                deploy_section = text[deploy_index:]
                credentials = text.index(CONFIGURE_AWS_ACTION, deploy_index)
                exact_role_validation = (
                    'test "$AWS_CLOUDFORMATION_ROLE_ARN" = '
                    f'"{expected_cloudformation_role_arn}"'
                )
                role_validation = text.find(exact_role_validation, deploy_index)
                self.assertNotEqual(role_validation, -1)
                self.assertIn(
                    "AWS_CLOUDFORMATION_ROLE_ARN: "
                    "${{ vars.AWS_CLOUDFORMATION_ROLE_ARN }}",
                    deploy_section,
                )
                self.assertNotIn('test -n "$AWS_CLOUDFORMATION_ROLE_ARN"', deploy_section)
                self.assertLess(role_validation, credentials)
                artifact_name = (
                    f"runtime-read-{environment_name}-build-"
                    "${{ github.run_id }}-${{ github.run_attempt }}-${{ github.sha }}"
                )

                self.assertIn("python -m unittest", validate_section)
                self.assertIn("sam validate --lint", validate_section)
                self.assertIn("sam build --no-cached", validate_section)
                self.assertIn("python tools/build_lambda_artifact.py", validate_section)
                self.assertIn(
                    "python tools/build_lambda_artifact.py --verify-artifact "
                    ".aws-sam/build/ConfigRuntimeReadFunction",
                    validate_section,
                )
                exact_release = workflow_name == "deploy-test.yml"
                if exact_release:
                    self.assertIn(
                        "python tools/build_lambda_artifact.py --package-test-release "
                        ".aws-sam/build/ConfigRuntimeReadFunction "
                        "--sam-template .aws-sam/build/template.yaml",
                        validate_section,
                    )
                    self.assertIn("release-manifest.sha256", validate_section)
                else:
                    self.assertNotIn("--package-test-release", validate_section)
                    self.assertIn("build-manifest.sha256", validate_section)
                self.assertIn("outputs:", validate_section)
                self.assertIn("artifact_id: ${{ steps.upload.outputs.artifact-id }}", validate_section)
                self.assertIn("artifact_name: ${{ steps.artifact_metadata.outputs.artifact_name }}", validate_section)
                self.assertIn("manifest_digest: ${{ steps.artifact_metadata.outputs.manifest_digest }}", validate_section)
                self.assertIn("id: artifact_metadata", validate_section)
                self.assertIn("id: upload", validate_section)
                self.assertIn('[[ "$manifest_digest" =~ ^[a-f0-9]{64}$ ]]', validate_section)
                self.assertEqual(text.count(artifact_name), 1)
                self.assertIn("include-hidden-files: true", validate_section)
                self.assertIn("retention-days: 1", validate_section)
                expected_artifact_paths = (
                    "path: |\n"
                    "            .aws-sam/release/template.yaml\n"
                    "            .aws-sam/release/runtime-read.zip\n"
                    "            .aws-sam/release/lambda-code-sha256.txt\n"
                    "            .aws-sam/release-manifest.sha256"
                    if exact_release else
                    "path: |\n"
                    "            .aws-sam/build/template.yaml\n"
                    "            .aws-sam/build/ConfigRuntimeReadFunction/lambda_function.py\n"
                    "            .aws-sam/build/ConfigRuntimeReadFunction/zoolanding_lambda_common.py\n"
                    "            .aws-sam/build-manifest.sha256"
                )
                self.assertIn(expected_artifact_paths, validate_section)
                self.assertNotIn("            .aws-sam/build/\n", validate_section)
                self.assertNotIn(".env", validate_section)
                self.assertNotIn("samconfig.toml", validate_section)
                self.assertGreater(second_verifier, text.index(UPLOAD_ARTIFACT_ACTION))
                self.assertIn(DOWNLOAD_ARTIFACT_ACTION, deploy_section)
                self.assertIn(SETUP_SAM_ACTION, deploy_section)
                self.assertIn("version: 1.163.0", deploy_section)
                self.assertIn(GITHUB_SCRIPT_ACTION, deploy_section)
                self.assertIn(CONFIGURE_AWS_ACTION, deploy_section)
                self.assertIn("id: validate_artifact_metadata", deploy_section)
                self.assertEqual(deploy_section.count("${{ needs.validate.outputs.artifact_id }}"), 1)
                self.assertEqual(deploy_section.count("${{ needs.validate.outputs.artifact_name }}"), 1)
                self.assertEqual(deploy_section.count("${{ needs.validate.outputs.manifest_digest }}"), 1)
                self.assertIn("RAW_ARTIFACT_ID: ${{ needs.validate.outputs.artifact_id }}", deploy_section)
                self.assertIn("RAW_ARTIFACT_NAME: ${{ needs.validate.outputs.artifact_name }}", deploy_section)
                self.assertIn("RAW_MANIFEST_DIGEST: ${{ needs.validate.outputs.manifest_digest }}", deploy_section)
                self.assertIn("artifact-ids: ${{ steps.validate_artifact_metadata.outputs.artifact_id }}", deploy_section)
                self.assertIn("ARTIFACT_ID: ${{ steps.validate_artifact_metadata.outputs.artifact_id }}", deploy_section)
                self.assertIn("ARTIFACT_NAME: ${{ steps.validate_artifact_metadata.outputs.artifact_name }}", deploy_section)
                self.assertIn(
                    "EXPECTED_MANIFEST_DIGEST: "
                    "${{ steps.validate_artifact_metadata.outputs.manifest_digest }}",
                    deploy_section,
                )
                self.assertIn('[[ "$artifact_id" =~ ^[1-9][0-9]*$ ]]', deploy_section)
                self.assertIn('[[ "$artifact_id" != *","* ]]', deploy_section)
                self.assertIn('[[ "$manifest_digest" =~ ^[a-f0-9]{64}$ ]]', deploy_section)
                self.assertIn("EXPECTED_SHA: ${{ github.sha }}", deploy_section)
                self.assertIn(
                    f'[[ "$artifact_name" =~ ^runtime-read-{environment_name}-build-'
                    '[1-9][0-9]*-[1-9][0-9]*-${EXPECTED_SHA}$ ]]',
                    deploy_section,
                )
                self.assertIn(
                    "printf 'artifact_id=%s\\nartifact_name=%s\\nmanifest_digest=%s\\n'",
                    deploy_section,
                )
                expected_manifest = "release-manifest.sha256" if exact_release else "build-manifest.sha256"
                self.assertIn(f"sha256sum --check --strict ../{expected_manifest}", deploy_section)
                self.assertIn('[[ "$EXPECTED_MANIFEST_DIGEST" =~ ^[a-f0-9]{64}$ ]]', deploy_section)
                self.assertIn('test "$actual_manifest_digest" = "$EXPECTED_MANIFEST_DIGEST"', deploy_section)
                if exact_release:
                    self.assertIn("openssl dgst -sha256 -binary", deploy_section)
                    self.assertIn('test "$actual_code_sha256" = "$expected_code_sha256"', deploy_section)
                else:
                    self.assertNotIn("openssl dgst -sha256 -binary", deploy_section)
                self.assertNotIn("python -m unittest", deploy_section)
                self.assertNotIn("sam build", deploy_section)
                self.assertNotIn(" zip ", deploy_section)
                self.assertNotIn("zip -", deploy_section)
                self.assertNotIn(SETUP_PYTHON_ACTION, deploy_section)
                self.assertNotIn(CHECKOUT_ACTION, deploy_section)
                self.assertNotIn(SETUP_NODE_ACTION, deploy_section)
                self.assertNotIn("tools/verify-promotion-commit.mjs", deploy_section)
                self.assertNotIn("run-id:", deploy_section)
                self.assertNotIn("github.run_id", deploy_section)
                self.assertNotIn("github.run_attempt", deploy_section)
                self.assertNotIn("ACTIONS_ID_TOKEN_REQUEST", deploy_section)
                self.assertIn("pullRequest.base?.repo?.full_name === repository", deploy_section)
                self.assertIn("pullRequest.head?.repo?.full_name === repository", deploy_section)
                self.assertIn("pullRequest.merge_commit_sha == null", deploy_section)
                self.assertIn("parents[0] !== pullRequest.base.sha", deploy_section)
                self.assertIn("parents[1] !== pullRequest.head.sha", deploy_section)
                self.assertIn("event.after !== sha", deploy_section)
                self.assertIn("context.eventName !== 'workflow_dispatch'", deploy_section)
                self.assertIn("branch.commit.sha !== sha", deploy_section)
                expected_template = (
                    ".aws-sam/release/template.yaml" if exact_release else ".aws-sam/build/template.yaml"
                )
                self.assertIn(f"--template-file {expected_template}", deploy_section)
                if exact_release:
                    self.assertIn("aws cloudformation describe-stacks", deploy_section)
                    self.assertIn("OutputKey=='FunctionName'", deploy_section)
                    self.assertNotIn('--query \\"', deploy_section)
                    self.assertNotIn("describe-stack-resource", deploy_section)
                    self.assertIn("aws lambda get-alias", deploy_section)
                    self.assertIn("aws lambda get-function-configuration", deploy_section)
                else:
                    self.assertNotIn("aws lambda get-alias", deploy_section)
                    self.assertNotIn("aws lambda get-function-configuration", deploy_section)

                download_start = text.index(DOWNLOAD_ARTIFACT_ACTION, deploy_index)
                download_end = text.index("\n      - name:", download_start)
                self.assertNotIn("github-token:", text[download_start:download_end])
                self.assertNotIn("run-id:", text[download_start:download_end])
                self.assertNotIn("name: runtime-read-", text[download_start:download_end])

                steps_start = text.index("\n    steps:\n", deploy_index) + len("\n    steps:\n")
                first_step = text.index("      - ", steps_start)
                metadata_step = text.index("      - name: Validate artifact metadata", deploy_index)
                self.assertEqual(first_step, metadata_step)
                self.assertLess(metadata_step, download_start)
                setup_sam = text.index(SETUP_SAM_ACTION, deploy_index)
                self.assertLess(download_start, setup_sam)

                digest_check = text.index('test "$actual_manifest_digest" = "$EXPECTED_MANIFEST_DIGEST"', deploy_index)
                strict_check = text.index("sha256sum --check --strict", digest_check)
                self.assertLess(digest_check, strict_check)

                github_script = text.index(GITHUB_SCRIPT_ACTION, deploy_index)
                self.assertLess(setup_sam, github_script)
                credentials_step = text.rfind("\n      - uses:", github_script, credentials)
                self.assertLess(github_script, credentials)
                final_tip_check = text.index("branch.commit.sha !== sha", github_script)
                self.assertNotIn("\n      - ", text[final_tip_check:credentials_step])

                script_marker = "          script: |\n"
                script_start = text.index(script_marker, github_script) + len(script_marker)
                script_lines = []
                for line in text[script_start:].splitlines():
                    if line and not line.startswith("            "):
                        break
                    script_lines.append(line[12:] if line else "")
                inline_verifiers.append("\n".join(script_lines).strip())

        self.assertEqual(len(inline_verifiers), 2)
        self.assertEqual(inline_verifiers[0], inline_verifiers[1])

    def test_release_docs_describe_the_nonexecuting_oidc_artifact_handoff(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        deploy = readme[readme.index("## Deploy"):readme.index("## Manual smoke test")]

        self.assertIn("validation job without OIDC", deploy)
        self.assertIn("same workflow run", deploy)
        self.assertIn("does not check out or execute repository code", deploy)
        self.assertIn("one day", deploy)
        self.assertIn("`runtime-read.zip`", deploy)
        self.assertIn("Lambda `CodeSha256`", deploy)
        self.assertIn("stable `live` alias", deploy)
        self.assertIn("explicit parameters", deploy)
        self.assertIn("cannot expand IAM permissions", deploy)
        self.assertIn("permissions boundary and CloudFormation execution role", deploy)
        self.assertNotIn("privileged job rebuilds the candidate", deploy)

    def test_release_docs_define_persistent_stack_role_and_safe_replacement_order(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        deploy = readme[readme.index("## Deploy"):readme.index("## Manual smoke test")]

        self.assertIn("CloudFormation stores `--role-arn` on the stack", deploy)
        self.assertIn("does not detach or roll back that association", deploy)
        self.assertIn("temporary bootstrap and caller rollback", deploy)
        self.assertIn("does not change the stack's retained CloudFormation role", deploy)
        self.assertIn("create or update the replacement in `zoolandingpage-aws-infra` first", deploy)
        self.assertIn("verify the stack's `RoleARN`", deploy)
        self.assertIn("fail closed before requesting AWS credentials", deploy)

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
