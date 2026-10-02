"""Offline regressions for the TEST release's two deployment principals."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a" * 40
ZIP = "b" * 64
VERSION = "sealed-version"
GITHUB = "zoolanding-config-runtime-read-test-github-deploy"
CFN = "zoolanding-config-runtime-read-test-cfn-exec"


def operator():
    spec = importlib.util.spec_from_file_location("runtime_test_preflight", ROOT / "tools/runtime_test_preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeTestPreflightTests(unittest.TestCase):
    def decisions(self, *, cfn_version="allowed", outside="implicitDeny", bad_encryption="implicitDeny"):
        requests = []

        def aws(*args):
            self.assertEqual(args[:2], ("iam", "simulate-principal-policy"))
            request = json.loads(args[args.index("--cli-input-json") + 1])
            requests.append(request)
            role = request["PolicySourceArn"].rsplit("/", 1)[1]
            action = request["ActionNames"][0]
            resource = request["ResourceArns"][0]
            context = {entry["ContextKeyName"]: entry["ContextKeyValues"] for entry in request.get("ContextEntries", [])}
            if "/system/thn-runtime/outside-releases/" in resource:
                decision = outside
            elif action == "s3:PutObject" and context.get("s3:x-amz-server-side-encryption") != ["AES256"]:
                decision = bad_encryption
            elif action == "s3:GetObjectVersion" and context.get("s3:VersionId") in (None, ["null"]):
                decision = "implicitDeny"
            elif role == CFN and action == "s3:GetObjectVersion":
                decision = cfn_version
            else:
                decision = "allowed"
            return {"EvaluationResults": [{"EvalDecision": decision}]}

        return aws, requests

    def test_missing_cloudformation_version_read_blocks_even_when_github_allows(self):
        preflight = operator()
        aws, requests = self.decisions(cfn_version="implicitDeny")
        with self.assertRaisesRegex(ValueError, "role_access_cfn_getobjectversion"):
            preflight.verify_role_access(aws, SOURCE, ZIP, VERSION)
        self.assertTrue(any(CFN in item["PolicySourceArn"] and item["ActionNames"] == ["s3:GetObjectVersion"]
                            for item in requests))
        self.assertTrue(any(GITHUB in item["PolicySourceArn"] and item["ActionNames"] == ["s3:PutObject"]
                            for item in requests))

    def test_both_roles_and_negative_scope_cases_must_match(self):
        preflight = operator()
        aws, requests = self.decisions()
        preflight.verify_role_access(aws, SOURCE, ZIP, VERSION)
        self.assertTrue(any(CFN in item["PolicySourceArn"] for item in requests))
        self.assertTrue(any(GITHUB in item["PolicySourceArn"] for item in requests))
        self.assertTrue(any("/system/thn-runtime/outside-releases/" in item["ResourceArns"][0]
                            for item in requests))
        self.assertTrue(any(item["ActionNames"] == ["s3:PutObject"] and
                            {entry["ContextKeyName"]: entry["ContextKeyValues"] for entry in item.get("ContextEntries", [])}.get("s3:x-amz-server-side-encryption") == ["aws:kms"]
                            for item in requests))
        for options in ({"outside": "allowed"}, {"bad_encryption": "allowed"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                preflight.verify_role_access(self.decisions(**options)[0], SOURCE, ZIP, VERSION)

    def test_coordinates_require_exact_sha_digest_and_version(self):
        preflight = operator()
        for source, digest, version in (("short", ZIP, VERSION), (SOURCE, "short", VERSION),
                                        (SOURCE, ZIP, ""), (SOURCE, ZIP, "null")):
            with self.subTest(source=source[:8], digest=digest[:8], version=version), self.assertRaises(ValueError):
                preflight.verify_role_access(self.decisions()[0], source, digest, version)

    def test_failure_message_keeps_known_category_without_leaking_exception_text(self):
        preflight = operator()
        self.assertEqual(preflight.failure_message(ValueError("runtime_test_preflight_role_access_cfn_getobjectversion")),
                         "runtime_test_preflight_role_access_cfn_getobjectversion")
        self.assertEqual(preflight.failure_message(RuntimeError("secret-value-from-upstream-tool")),
                         "runtime_test_preflight_rejected")

    def test_stack_identity_requires_exact_test_cloudformation_role(self):
        preflight = operator()
        snapshot = {
            "stackId": "arn:aws:cloudformation:us-east-1:765932874577:stack/zoolanding-config-runtime-read-test/654d8f60-6d02-11f1-aa08-0e6c5445b1d9",
            "cloudFormationRoleArn": "arn:aws:iam::765932874577:role/" + CFN,
            "identities": [{"LogicalResourceId": str(index)} for index in range(8)],
        }
        preflight.verify_stack_identity(snapshot)
        changed = dict(snapshot, cloudFormationRoleArn="arn:aws:iam::765932874577:role/another-role")
        with self.assertRaises(ValueError): preflight.verify_stack_identity(changed)
        changed = dict(snapshot, identities=snapshot["identities"][:-1])
        with self.assertRaises(ValueError): preflight.verify_stack_identity(changed)


if __name__ == "__main__":
    unittest.main()
