"""Offline release boundary regressions; fixtures are not AWS inventory."""
import copy
import base64
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FUNCTION = "ConfigRuntimeReadFunction"
ALIAS = FUNCTION + "Aliaslive"
OLD_VERSION = FUNCTION + "Version375dd3b296"
NEW_VERSION = FUNCTION + "Version7ec2b2d677"
SOURCE = "a" * 40
ZIP_DIGEST = "b" * 64
CODE = {"S3Bucket": "zoolanding-config-payloads-test",
        "S3Key": f"system/thn-runtime/releases/{SOURCE}/{ZIP_DIGEST}.zip",
        "S3ObjectVersion": "sealed-version"}


def operator():
    spec = importlib.util.spec_from_file_location("identical_operator", ROOT / "tools/native_runtime_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def templates():
    before = {"AWSTemplateFormatVersion": "2010-09-09", "Description": "retained",
              "Parameters": {"EnvironmentName": {"Type": "String"}},
              "Conditions": {"Same": {"Fn::Equals": [{"Ref": "EnvironmentName"}, "test"]}},
              "Outputs": {"Endpoint": {"Value": {"Ref": "RuntimeApi"}}},
              "Resources": {
                  FUNCTION: {"Type": "AWS::Lambda::Function", "Properties": {
                      "Code": {"S3Bucket": "before", "S3Key": "before", "S3ObjectVersion": "old-version"},
                      "Runtime": "python3.13", "Role": {"Ref": "ExistingRole"}}},
                  OLD_VERSION: {"Type": "AWS::Lambda::Version", "DeletionPolicy": "Retain",
                                "Properties": {"FunctionName": {"Ref": FUNCTION}}},
                  ALIAS: {"Type": "AWS::Lambda::Alias", "Properties": {
                      "Name": "live", "FunctionName": {"Ref": FUNCTION},
                      "FunctionVersion": {"Fn::GetAtt": [OLD_VERSION, "Version"]}}},
                  "RuntimeApi": {"Type": "AWS::ApiGateway::RestApi", "Properties": {"Name": "same"}},
                  "ExistingRole": {"Type": "AWS::IAM::Role", "Properties": {"Path": "/"}},
              }}
    projected = copy.deepcopy(before)
    projected["Resources"][FUNCTION]["Properties"]["Code"] = copy.deepcopy(CODE)
    projected["Resources"][NEW_VERSION] = projected["Resources"].pop(OLD_VERSION)
    projected["Resources"][ALIAS]["Properties"]["FunctionVersion"] = {"Fn::GetAtt": [NEW_VERSION, "Version"]}
    return before, projected


def changes():
    return [{"Type": "Resource", "ResourceChange": {
        "LogicalResourceId": FUNCTION, "ResourceType": "AWS::Lambda::Function",
        "Action": "Modify", "Replacement": "False", "Scope": ["Properties"],
        "Details": [{"Target": {"Attribute": "Properties", "Name": "Code", "RequiresRecreation": "Never"}}]}}]


class IdenticalCandidateTests(unittest.TestCase):
    def test_identical_candidate_preserves_entire_version_alias_and_template(self):
        op = operator()
        prepare = getattr(op, "code_pointer_candidate", None)
        self.assertTrue(callable(prepare), "no safe native candidate for identical ZIP/configuration")
        before, projected = templates()
        expected = copy.deepcopy(before)
        expected["Resources"][FUNCTION]["Properties"]["Code"] = copy.deepcopy(CODE)
        self.assertEqual(prepare(before, projected), expected)
        self.assertEqual(before, templates()[0], "candidate generation mutated the native baseline")

    def test_candidate_rejects_hidden_projection_changes_or_unresolved_macros(self):
        op = operator()
        prepare = getattr(op, "code_pointer_candidate", None)
        self.assertTrue(callable(prepare))
        for mutation in ("role", "runtime", "outputs", "conditions", "metadata", "alias", "version",
                         "extra-resource", "transform", "globals", "serverless", "nested-macro"):
            before, projected = templates()
            if mutation in ("role", "runtime"):
                projected["Resources"][FUNCTION]["Properties"][mutation.capitalize()] = "changed"
            if mutation == "outputs": projected["Outputs"]["Endpoint"]["Value"] = "changed"
            if mutation == "conditions": projected["Conditions"]["Same"] = False
            if mutation == "metadata": projected["Metadata"] = {"hidden": "changed"}
            if mutation == "alias": projected["Resources"][ALIAS]["Properties"]["Name"] = "other"
            if mutation == "version": projected["Resources"][NEW_VERSION]["Properties"]["Description"] = "force publish"
            if mutation == "extra-resource": projected["Resources"]["Extra"] = {"Type": "AWS::IAM::Policy"}
            if mutation == "transform": before["Transform"] = "custom"
            if mutation == "globals": before["Globals"] = {}
            if mutation == "serverless": before["Resources"]["RuntimeApi"]["Type"] = "AWS::Serverless::Api"
            if mutation == "nested-macro": before["Resources"][FUNCTION]["Properties"]["Code"] = {"Fn::Transform": {"Name": "custom"}}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): prepare(before, projected)

    def test_normal_projection_preserves_versions_when_logical_id_is_already_same(self):
        op = operator()
        prepare = getattr(op, "code_pointer_candidate", None)
        self.assertTrue(callable(prepare))
        before, _ = templates()
        projected = copy.deepcopy(before)
        projected["Resources"][FUNCTION]["Properties"]["Code"] = copy.deepcopy(CODE)
        self.assertEqual(prepare(before, projected), projected)

    def test_review_rejects_changed_outputs_outside_resource_inventory(self):
        op = operator()
        before, _ = templates()
        candidate = copy.deepcopy(before)
        candidate["Resources"][FUNCTION]["Properties"]["Code"] = copy.deepcopy(CODE)
        candidate["Outputs"]["Endpoint"]["Value"] = "changed"
        with self.assertRaises(ValueError):
            op.review_resources(before, candidate, changes(), "test", SOURCE, ZIP_DIGEST)

    def test_review_blocks_redundant_version_inventory_for_identical_package(self):
        op = operator()
        self.assertIn("identical_package", inspect.signature(op.review_resources).parameters,
                      "native guard cannot distinguish a redundant publication")
        before, projected = templates()
        inventory = changes() + [
            {"Type": "Resource", "ResourceChange": {"LogicalResourceId": NEW_VERSION, "ResourceType": "AWS::Lambda::Version", "Action": "Add"}},
            {"Type": "Resource", "ResourceChange": {"LogicalResourceId": OLD_VERSION, "ResourceType": "AWS::Lambda::Version", "Action": "Remove"}},
            {"Type": "Resource", "ResourceChange": {"LogicalResourceId": ALIAS, "ResourceType": "AWS::Lambda::Alias", "Action": "Modify", "Replacement": "False"}}]
        with self.assertRaises(ValueError): op.review_resources(before, projected, inventory, "test", SOURCE, ZIP_DIGEST, identical_package=True)
        neutral = op.code_pointer_candidate(before, projected)
        op.review_resources(before, neutral, changes(), "test", SOURCE, ZIP_DIGEST, identical_package=True)
        op.review_resources(before, projected, inventory, "test", SOURCE, ZIP_DIGEST, identical_package=False)


class TestBindingTests(unittest.TestCase):
    def fixture(self):
        package = b"sealed real-byte fixture"
        before, _ = templates()
        function = {"FunctionName": "retained", "FunctionArn": "arn:aws:lambda:us-east-1:765932874577:function:retained",
                    "Version": "$LATEST", "RevisionId": "latest-revision", "Runtime": "python3.13", "Role": "same",
                    "Environment": {"Variables": {"ENVIRONMENT_NAME": "test"}}, "State": "Active",
                    "LastUpdateStatus": "Successful", "CodeSha256": base64.b64encode(hashlib.sha256(package).digest()).decode()}
        live = {**copy.deepcopy(function), "Version": "4", "RevisionId": "version-revision",
                "FunctionArn": function["FunctionArn"] + ":4"}
        alias = {"AliasArn": function["FunctionArn"] + ":live", "Name": "live", "FunctionVersion": "4", "RevisionId": "alias-revision"}
        versions = [{"Version": "3", "FunctionArn": function["FunctionArn"] + ":3", "CodeSha256": "retained-old"}, copy.deepcopy(live)]
        snapshot = {"processed": before, "functions": [function], "identities": [
            {"LogicalResourceId": FUNCTION, "PhysicalResourceId": "retained", "ResourceType": "AWS::Lambda::Function"},
            {"LogicalResourceId": ALIAS, "PhysicalResourceId": function["FunctionArn"] + ":live", "ResourceType": "AWS::Lambda::Alias"},
            {"LogicalResourceId": OLD_VERSION, "PhysicalResourceId": function["FunctionArn"] + ":4", "ResourceType": "AWS::Lambda::Version"}]}
        return package, snapshot, live, alias, versions

    def read(self, op, package, snapshot, live, alias, versions):
        def aws(*args):
            if args[:2] == ("lambda", "get-alias"): return copy.deepcopy(alias)
            if args[:2] == ("lambda", "get-function"):
                return {"Configuration": copy.deepcopy(live), "Code": {"Location": "https://awslambda-us-east-1-tasks.s3.us-east-1.amazonaws.com/sealed"}}
            if args[:2] == ("lambda", "list-versions-by-function"): return {"Versions": copy.deepcopy(versions)}
            raise AssertionError(args)
        with patch.object(op, "aws", side_effect=aws), patch.object(op, "urlopen") as download:
            download.return_value.__enter__.return_value.read.return_value = package
            return op.test_release_binding(snapshot, package)

    def test_binding_seals_actual_alias_versions_and_verified_qualified_bytes(self):
        op = operator()
        self.assertTrue(callable(getattr(op, "test_release_binding", None)), "neutral release has no actual alias/version/byte binding")
        package, snapshot, live, alias, versions = self.fixture()
        result = self.read(op, package, snapshot, live, alias, versions)
        self.assertTrue(result["identicalPackage"])
        self.assertEqual(result["alias"], alias)
        self.assertEqual(result["qualifiedConfiguration"], live)
        self.assertEqual(result["publishedVersions"], versions)
        self.assertEqual(result["qualifiedZipSha256"], hashlib.sha256(package).hexdigest())

    def test_binding_rejects_config_routing_identity_health_and_bytes_mismatch(self):
        op = operator()
        self.assertTrue(callable(getattr(op, "test_release_binding", None)))
        for mutation in ("config", "routing", "alias-version", "alias-arn", "version-id", "unknown", "health", "bytes", "versions"):
            package, snapshot, live, alias, versions = self.fixture()
            if mutation == "config": live["Role"] = "different"
            if mutation == "routing": alias["RoutingConfig"] = {"AdditionalVersionWeights": {"3": .1}}
            if mutation == "alias-version": alias["FunctionVersion"] = "$LATEST"
            if mutation == "alias-arn": alias["AliasArn"] += "-wrong"
            if mutation == "version-id": snapshot["identities"][-1]["PhysicalResourceId"] += "-wrong"
            if mutation == "unknown": live["Unexpected"] = True
            if mutation == "health": live["State"] = "Pending"
            if mutation == "bytes": package = b"tampered signed download"
            if mutation == "versions": versions[-1]["Version"] = "8"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.read(op, package, snapshot, live, alias, versions)

    def test_neutral_postguard_keeps_all_versions_and_alias_and_code_coordinates(self):
        op = operator()
        verify = getattr(op, "verify_neutral_state", None)
        self.assertTrue(callable(verify), "TEST postguard excludes version identities")
        package, snapshot, live, alias, versions = self.fixture()
        snapshot["testReleaseBinding"] = self.read(op, package, snapshot, live, alias, versions)
        after = copy.deepcopy(snapshot)
        after["processed"]["Resources"][FUNCTION]["Properties"]["Code"] = copy.deepcopy(CODE)
        verify(snapshot, after, CODE)
        for mutation in ("version-identity", "retained-version", "alias-revision", "code", "metadata", "management"):
            changed = copy.deepcopy(after)
            if mutation == "version-identity": changed["identities"][-1]["PhysicalResourceId"] = "new-version"
            if mutation == "retained-version": changed["testReleaseBinding"]["publishedVersions"][0]["CodeSha256"] = "changed"
            if mutation == "alias-revision": changed["testReleaseBinding"]["alias"]["RevisionId"] = "new-revision"
            if mutation == "code": changed["processed"]["Resources"][FUNCTION]["Properties"]["Code"]["S3ObjectVersion"] = "other"
            if mutation == "metadata": changed["processed"]["Metadata"] = {"unexpected": True}
            if mutation == "management": changed["runtimeManagement"] = {"UpdateRuntimeOn": "Manual"}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): verify(snapshot, changed, CODE)


class LambdaTaskUrlTests(unittest.TestCase):
    def test_verified_regional_lambda_task_hosts_accept_https_only(self):
        op = operator()
        self.assertTrue(callable(getattr(op, "lambda_task_url", None)), "actual AWS task host is incorrectly rejected")
        for host in ("awslambda-us-east-1-tasks.s3.us-east-1.amazonaws.com", "prod-04-2014-tasks.s3.us-east-1.amazonaws.com"):
            for port in ("", ":443"):
                self.assertEqual(op.lambda_task_url(f"https://{host}{port}/fixture?signature=fixture").hostname, host)

    def test_task_urls_reject_arbitrary_hosts_transport_userinfo_and_malformed_port(self):
        op = operator()
        self.assertTrue(callable(getattr(op, "lambda_task_url", None)))
        host = "prod-04-2014-tasks.s3.us-east-1.amazonaws.com"
        for value in (f"http://{host}/fixture", f"https://{host}:80/fixture", f"https://{host}:bad/fixture",
                      f"https://user@{host}/fixture", f"https://user:password@{host}/fixture",
                      f"https://{host}.example.com/fixture", "https://other.s3.us-east-1.amazonaws.com/fixture",
                      "https://prod-04-2014-tasks.s3.eu-west-1.amazonaws.com/fixture", "https://[invalid/fixture"):
            with self.subTest(value=value), self.assertRaises(ValueError): op.lambda_task_url(value)


class ReleaseSnapshotTests(unittest.TestCase):
    fixture = TestBindingTests.fixture
    read = TestBindingTests.read
    def test_test_snapshot_captures_runtime_management_and_complete_live_binding(self):
        op = operator()
        capture = getattr(op, "release_snapshot", None)
        self.assertTrue(callable(capture), "native lifecycle does not bind qualified TEST state")
        package, snapshot, live, alias, versions = self.fixture()
        binding = self.read(op, package, snapshot, live, alias, versions)
        with patch.object(op, "baseline", return_value=copy.deepcopy(snapshot)), \
             patch.object(op, "runtime_management", return_value={"UpdateRuntimeOn": "Auto"}), \
             patch.object(op, "test_release_binding", return_value=binding):
            result = capture(op.PROFILES["test"], package)
        self.assertEqual(result["runtimeManagement"], {"UpdateRuntimeOn": "Auto"})
        self.assertEqual(result["testReleaseBinding"], binding)

    def test_production_snapshot_preserves_existing_live_test_provenance(self):
        op = operator()
        capture = getattr(op, "release_snapshot", None)
        self.assertTrue(callable(capture))
        with patch.object(op, "baseline", return_value={"existing": True}), \
             patch.object(op, "live_test_zip", return_value={"sealed": True}), \
             patch.object(op, "test_release_binding", side_effect=AssertionError("TEST-only change")):
            self.assertEqual(capture(op.PROFILES["production"], b"zip"), {"existing": True, "testBinding": {"sealed": True}})

    def test_review_snapshot_seals_full_source_but_post_snapshot_does_not_revalidate_history(self):
        op = operator()
        self.assertIn("candidate_text", inspect.signature(op.release_snapshot).parameters,
                      "full SAM source authority is not wired into the sealed lifecycle")
        package, snapshot, live, alias, versions = self.fixture()
        binding = self.read(op, package, snapshot, live, alias, versions)
        reference = {"kind": "previous-protected-git-sam", "sourceSha": SOURCE, "samSha256": "d" * 64}
        with patch.object(op, "baseline", side_effect=lambda profile: copy.deepcopy(snapshot)), \
             patch.object(op, "runtime_management", return_value={"UpdateRuntimeOn": "Auto"}), \
             patch.object(op, "test_release_binding", return_value=binding), \
             patch.object(op, "sam_source_reference", return_value=reference) as source:
            reviewed = op.release_snapshot(op.PROFILES["test"], package, "full candidate")
            self.assertEqual(reviewed["sourceReference"], reference)
            self.assertEqual(source.call_args.args[1], "full candidate")
            source.reset_mock()
            post = op.release_snapshot(op.PROFILES["test"], package)
            self.assertNotIn("sourceReference", post)
            source.assert_not_called()


class PreviousExecutionTests(unittest.TestCase):
    def fixture(self):
        run = {"id": 12, "run_attempt": 2, "head_sha": SOURCE, "head_branch": "test",
               "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
               "path": ".github/workflows/deploy-test.yml",
               "repository": {"full_name": "LynxPardelle/zoolanding-config-runtime-read"}}
        job = {"name": "deploy", "run_id": 12, "head_sha": SOURCE, "status": "completed", "conclusion": "success",
               "steps": [{"name": name, "status": "completed", "conclusion": "success"}
                         for name in ("Deploy test", "Verify immutable live alias")]}
        return {"total_count": 1, "workflow_runs": [run]}, {"total_count": 1, "jobs": [job]}

    def invoke(self, response, jobs):
        op = operator()
        with patch.object(op, "_github_read", side_effect=[response, jobs]):
            return op.previous_test_execution(SOURCE)

    def test_exact_successful_execute_is_required(self):
        response, jobs = self.fixture()
        self.assertEqual(self.invoke(response, jobs), {"runId": 12, "runAttempt": 2, "headSha": SOURCE})
        jobs["jobs"][0]["steps"][1]["conclusion"] = "skipped"
        with self.assertRaises(ValueError): self.invoke(response, jobs)

    def test_wrong_context_counts_or_duplicate_authority_reject(self):
        for mutation in ("branch", "event", "repository", "path", "source", "run-id", "attempt", "run-count",
                         "job-count", "duplicate-jobs", "job-source", "job-run", "job-status", "step-status", "duplicate-step"):
            response, jobs = self.fixture()
            run, job = response["workflow_runs"][0], jobs["jobs"][0]
            if mutation == "branch": run["head_branch"] = "main"
            if mutation == "event": run["event"] = "push"
            if mutation == "repository": run["repository"]["full_name"] = "other/repository"
            if mutation == "path": run["path"] = ".github/workflows/other.yml"
            if mutation == "source": run["head_sha"] = "f" * 40
            if mutation == "run-id": run["id"] = True
            if mutation == "attempt": run["run_attempt"] = True
            if mutation == "run-count": response["total_count"] = 2
            if mutation == "job-count": jobs["total_count"] = 2
            if mutation == "duplicate-jobs": jobs["jobs"] *= 2; jobs["total_count"] = 2
            if mutation == "job-source": job["head_sha"] = "f" * 40
            if mutation == "job-run": job["run_id"] = 13
            if mutation == "job-status": job["status"] = "in_progress"
            if mutation == "step-status": job["steps"][0]["status"] = "in_progress"
            if mutation == "duplicate-step": job["steps"].append({**job["steps"][0], "conclusion": "skipped"})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.invoke(response, jobs)

    def test_later_review_only_success_does_not_replace_prior_executed_provenance(self):
        response, jobs = self.fixture()
        review = {**copy.deepcopy(response["workflow_runs"][0]), "id": 13}
        response["workflow_runs"].append(review)
        response["total_count"] = 2
        review_jobs = copy.deepcopy(jobs)
        review_jobs["jobs"][0]["run_id"] = 13
        review_jobs["jobs"][0]["steps"][1]["conclusion"] = "skipped"
        op = operator()
        with patch.object(op, "_github_read", side_effect=[response, review_jobs, jobs]):
            self.assertEqual(op.previous_test_execution(SOURCE), {"runId": 12, "runAttempt": 2, "headSha": SOURCE})


class SamProjectionTests(unittest.TestCase):
    def inputs(self):
        template = {"Transform": ["AWS::LanguageExtensions", "AWS::Serverless-2016-10-31"],
                    "Parameters": {"EnvironmentName": {"Type": "String"}}, "Resources": {
                        FUNCTION: {"Type": "AWS::Serverless::Function", "Properties": {"CodeUri": "runtime-read.zip"}}}}
        snapshot = {"stackId": "arn:aws:cloudformation:us-east-1:765932874577:stack/zoolanding-config-runtime-read-test/verified-id",
                    "parameters": [{"ParameterKey": "EnvironmentName", "ParameterValue": "test"}]}
        return template, snapshot

    def test_full_projection_uses_explicit_live_parameters_and_official_engines(self):
        op = operator()
        project = getattr(op, "project_test_template", None)
        self.assertTrue(callable(project), "candidate lacks full official SAM projection")
        template, snapshot = self.inputs()
        before, projected = templates()
        from unittest.mock import Mock
        parser = Mock(return_value=copy.deepcopy(template))
        expand = Mock(side_effect=lambda value, **kwargs: SimpleNamespace(expanded_template=value))
        translator = Mock(return_value=projected)
        session, sam_parser, resolver = Mock(), Mock(), Mock()
        with patch.object(op, "sam_libraries", return_value=(parser, expand, translator, sam_parser, session, resolver)):
            result, params = project("complete sealed SAM", snapshot, CODE)
        self.assertEqual(result, projected)
        self.assertEqual(params["EnvironmentName"], "test")
        self.assertEqual(params["AWS::StackId"], snapshot["stackId"])
        self.assertEqual(params["AWS::StackName"], "zoolanding-config-runtime-read-test")
        self.assertEqual(params["AWS::Region"], "us-east-1")
        self.assertEqual(params["AWS::AccountId"], "765932874577")
        self.assertEqual(expand.call_args.kwargs, {"parameter_values": params, "enabled": True})
        supplied = expand.call_args.args[0]
        self.assertEqual(supplied["Resources"][FUNCTION]["Properties"]["CodeUri"],
                         {"Bucket": CODE["S3Bucket"], "Key": CODE["S3Key"], "Version": CODE["S3ObjectVersion"]})
        self.assertEqual(translator.call_args.args[1], params)

    def test_sam_source_comparison_rejects_inactive_branch_changes_before_semantics(self):
        op = operator()
        compare = getattr(op, "verify_sam_source", None)
        self.assertTrue(callable(compare), "semantic resolution can hide changed inactive conditional branches")
        source, _ = self.inputs()
        source["Resources"][FUNCTION]["Properties"]["Environment"] = {"Variables": {
            "VALUE": {"Fn::If": ["Inactive", "old-inactive-value", "active-value"]}}}
        candidate = copy.deepcopy(source)
        candidate["Resources"][FUNCTION]["Properties"]["CodeUri"] = {"Bucket": "old", "Key": "old", "Version": "old"}
        from unittest.mock import Mock
        libraries = (lambda text: copy.deepcopy(source if text == "candidate" else candidate), None, None, None, None, None)
        with patch.object(op, "sam_libraries", return_value=libraries): compare("candidate", "original")
        candidate["Resources"][FUNCTION]["Properties"]["Environment"]["Variables"]["VALUE"]["Fn::If"][1] = "tampered-inactive-value"
        with patch.object(op, "sam_libraries", return_value=libraries), self.assertRaises(ValueError): compare("candidate", "original")

    def test_projection_rejects_unknown_macro_missing_or_duplicate_live_parameters(self):
        op = operator()
        project = getattr(op, "project_test_template", None)
        self.assertTrue(callable(project))
        for mutation in ("transform", "nested-macro", "missing", "duplicate", "extra", "wrong-stack", "local-code"):
            template, snapshot = self.inputs()
            if mutation == "transform": template["Transform"].append("custom")
            if mutation == "nested-macro": template["Resources"][FUNCTION]["Metadata"] = {"Fn::Transform": {"Name": "Include"}}
            if mutation == "missing": snapshot["parameters"] = []
            if mutation == "duplicate": snapshot["parameters"] *= 2
            if mutation == "extra": snapshot["parameters"].append({"ParameterKey": "Unknown", "ParameterValue": "hidden"})
            if mutation == "wrong-stack": snapshot["stackId"] = snapshot["stackId"].replace("test/", "production/")
            if mutation == "local-code": template["Resources"][FUNCTION]["Properties"]["CodeUri"] = "other.zip"
            with patch.object(op, "sam_libraries") as libraries:
                libraries.return_value = (lambda text: template, lambda *args, **kw: self.fail("must reject before expansion"), None, None, None, None)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError): project("sealed", snapshot, CODE)


class PreviousSamReferenceTests(unittest.TestCase):
    def raw(self):
        return {"Transform": "AWS::Serverless-2016-10-31", "Parameters": {}, "Resources": {
            "RuntimeApi": {"Type": "AWS::Serverless::Api", "Metadata": {"SamResourceId": "RuntimeApi"}},
            FUNCTION: {"Type": "AWS::Serverless::Function", "Properties": {"CodeUri": ".build/runtime-read", "Runtime": "python3.13"}}}}

    def release(self):
        value = self.raw()
        value["Transform"] = ["AWS::LanguageExtensions", "AWS::Serverless-2016-10-31"]
        value["Resources"][FUNCTION]["Properties"].update(CodeUri="runtime-read.zip", AutoPublishAlias="live",
                                                           AutoPublishAliasAllProperties=True, VersionDeletionPolicy="Retain")
        value["Resources"][FUNCTION]["Metadata"] = {"SamResourceId": FUNCTION}
        return value

    def response(self, template):
        content = json.dumps(template).encode()
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        return {"type": "file", "path": "template.yaml", "encoding": "base64", "size": len(content),
                "sha": blob, "content": base64.b64encode(content).decode()}

    def snapshot(self):
        return {"original": templates()[0], "processed": templates()[0], "testReleaseBinding": {"qualifiedZipSha256": ZIP_DIGEST}}

    def test_future_native_original_reads_and_seals_previous_exact_git_sam_reference(self):
        op = operator()
        capture = getattr(op, "sam_source_reference", None)
        self.assertTrue(callable(capture), "future native Original loses inactive SAM branch authority")
        snapshot = self.snapshot()
        snapshot["processed"]["Resources"][FUNCTION]["Properties"]["Code"] = copy.deepcopy(CODE)
        response = self.response(self.raw())
        with patch.object(op, "sam_libraries", return_value=(json.loads, None, None, None, None, None)), \
             patch.dict(os.environ, {"GITHUB_REPOSITORY": "LynxPardelle/zoolanding-config-runtime-read"}), \
             patch.object(op.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")) as call, \
             patch.object(op, "previous_test_execution", return_value={"headSha": SOURCE, "runId": 1, "runAttempt": 1}):
            reference = capture(snapshot, json.dumps(self.release()))
        self.assertEqual(reference["sourceSha"], SOURCE)
        self.assertEqual(reference["gitBlobSha"], response["sha"])
        self.assertIn(f"?ref={SOURCE}", call.call_args.args[0][-1])

    def test_reference_rejects_wrong_blob_prefix_version_or_inactive_source_changes(self):
        op = operator()
        capture = getattr(op, "sam_source_reference", None)
        self.assertTrue(callable(capture))
        for mutation in ("blob", "bucket", "key", "version", "zip", "metadata", "alias", "inactive", "repo"):
            snapshot = self.snapshot()
            code = copy.deepcopy(CODE)
            snapshot["processed"]["Resources"][FUNCTION]["Properties"]["Code"] = code
            raw = self.raw()
            if mutation == "bucket": code["S3Bucket"] = "foreign"
            if mutation == "key": code["S3Key"] = "foreign"
            if mutation == "version": code["S3ObjectVersion"] = "null"
            if mutation == "zip": snapshot["testReleaseBinding"]["qualifiedZipSha256"] = "c" * 64
            if mutation == "metadata": raw["Resources"][FUNCTION]["Metadata"] = {"extra": True}
            if mutation == "alias": raw["Resources"][FUNCTION]["Properties"]["AutoPublishAlias"] = "other"
            if mutation == "inactive": raw["Resources"][FUNCTION]["Properties"]["Environment"] = {"Variables": {"hidden": {"Fn::If": ["Inactive", "tampered", "same"]}}}
            response = self.response(raw)
            if mutation == "blob": response["sha"] = "f" * 40
            with patch.object(op, "sam_libraries", return_value=(json.loads, None, None, None, None, None)), \
                 patch.dict(os.environ, {"GITHUB_REPOSITORY": "other/repo" if mutation == "repo" else "LynxPardelle/zoolanding-config-runtime-read"}), \
                 patch.object(op.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")), \
                 self.subTest(mutation=mutation), self.assertRaises(ValueError): capture(snapshot, json.dumps(self.release()))


class NativeLifecycleTests(unittest.TestCase):
    def run_cycle(self, identical=True, post_drift=False):
        op = operator()
        self.assertTrue(callable(getattr(op, "project_test_template", None)))
        self.assertTrue(callable(getattr(op, "release_snapshot", None)))
        package, snapshot, live, alias, versions = TestBindingTests().fixture()
        binding = TestBindingTests().read(op, package, snapshot, live, alias, versions)
        if not identical:
            package = b"new publishable package fixture"
            binding["identicalPackage"] = False
        snapshot.update(stackId="stack-arn", parameters=[], outputs=[], runtimeManagement={"UpdateRuntimeOn": "Auto"},
                        testReleaseBinding=binding, sourceReference={"kind": "previous-protected-git-sam", "samSha256": "d" * 64})
        snapshot["original"] = copy.deepcopy(snapshot["processed"])
        before, projected = templates()
        digest = hashlib.sha256(package).hexdigest()
        code = {**CODE, "S3Key": f"system/thn-runtime/releases/{SOURCE}/{digest}.zip"}
        projected["Resources"][FUNCTION]["Properties"]["Code"] = code
        expected = copy.deepcopy(before)
        expected["Resources"][FUNCTION]["Properties"]["Code"] = code
        if not identical: expected = copy.deepcopy(projected)
        change_arn = "arn:aws:cloudformation:us-east-1:765932874577:changeSet/thn-runtime-1-1/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        description = {"ChangeSetId": change_arn, "StackId": "stack-arn", "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE",
                       "Parameters": [], "Changes": changes(), "CreationTime": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
        if not identical:
            description["Changes"] += [
                {"Type": "Resource", "ResourceChange": {"LogicalResourceId": NEW_VERSION, "ResourceType": "AWS::Lambda::Version", "Action": "Add"}},
                {"Type": "Resource", "ResourceChange": {"LogicalResourceId": OLD_VERSION, "ResourceType": "AWS::Lambda::Version", "Action": "Remove"}},
                {"Type": "Resource", "ResourceChange": {"LogicalResourceId": ALIAS, "ResourceType": "AWS::Lambda::Alias", "Action": "Modify", "Replacement": "False"}}]
        sent, executions = [], []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "runtime-read.zip").write_bytes(package)
            (root / "lambda-code-sha256.txt").write_bytes((base64.b64encode(hashlib.sha256(package).digest()).decode() + "\n").encode())
            (root / "template.yaml").write_text("      CodeUri: runtime-read.zip\n")
            def aws(*args):
                if args[:2] == ("s3api", "get-bucket-versioning"): return {"Status": "Enabled"}
                if args[:2] == ("s3api", "head-object"): return {"VersionId": "sealed-version"}
                if args[:2] == ("s3api", "get-object"):
                    Path(args[-1]).write_bytes(package)
                    return {}
                if args[:2] == ("cloudformation", "create-change-set"):
                    body = Path(args[args.index("--template-body") + 1][7:]).read_text()
                    try: sent.append(json.loads(body))
                    except ValueError: sent.append({"unsafeSamBody": body})
                    return {"Id": change_arn}
                if args[:2] == ("cloudformation", "describe-change-set"): return description
                if args[:2] == ("cloudformation", "get-template"): return {"TemplateBody": expected}
                if args[:2] == ("cloudformation", "execute-change-set"):
                    executions.append(args)
                    return {}
                raise AssertionError(args)
            env = {"GITHUB_REF": "refs/heads/test", "GITHUB_SHA": SOURCE, "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
                   "AWS_CLOUDFORMATION_ROLE_ARN": "existing-role", "GITHUB_STEP_SUMMARY": str(root / "summary")}
            arguments = ["operator", "--environment=test", "--execution=review", "--release-root=" + str(root),
                         "--source-sha=" + SOURCE, "--manifest-digest=" + "c" * 64]
            with patch.dict(os.environ, env), patch("sys.argv", arguments), patch.object(op, "baseline", return_value=snapshot), \
                 patch.object(op, "release_snapshot", return_value=copy.deepcopy(snapshot)) as capture, patch.object(op, "aws", side_effect=aws), \
                 patch.object(op, "project_test_template", return_value=(projected, None)) as project, \
                 patch.object(op, "sam_libraries", return_value=(None, None, None, None, None,
                     lambda params: SimpleNamespace(resolve_parameter_refs=lambda value: value))), \
                 patch.object(op.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
                op.main()
            if identical:
                self.assertEqual(sent, [expected], "identical package still creates a SAM version/alias rotation")
            else:
                self.assertEqual(len(sent), 1)
                self.assertIn(code["S3Key"], sent[0]["unsafeSamBody"])
            self.assertTrue(all(len(call.args) == 3 for call in capture.call_args_list), "pre-write source reference was not recaptured")
            self.assertGreaterEqual(project.call_count, 2, "review did not recheck sealed source against retained inventory")
            self.assertEqual(executions, [])
            with patch.dict(os.environ, env):
                review_digest = op.preview_digest(snapshot, description, expected, expected, SOURCE, "c" * 64, digest)
            execute_args = [value.replace("--execution=review", "--execution=execute") for value in arguments] + [
                "--review-digest=" + review_digest, "--review-change-set-arn=" + change_arn]
            after = copy.deepcopy(snapshot)
            after["processed"] = expected
            after["functions"][0]["RevisionId"] = "after-update"
            after["functions"][0]["CodeSha256"] = base64.b64encode(hashlib.sha256(package).digest()).decode()
            if post_drift:
                after["processed"] = copy.deepcopy(after["processed"])
                after["processed"]["Metadata"] = {"unreviewed": True}
            for drift in (False, "alias", "source-reference"):
                fresh = copy.deepcopy(snapshot)
                if drift == "alias": fresh["testReleaseBinding"]["alias"]["RevisionId"] = "unexpected"
                if drift == "source-reference": fresh["sourceReference"]["samSha256"] = "e" * 64
                executions.clear()
                with patch.dict(os.environ, env), patch("sys.argv", execute_args), \
                     patch.object(op, "release_snapshot", side_effect=[copy.deepcopy(snapshot), fresh, copy.deepcopy(snapshot), after]) as capture, \
                     patch.object(op, "aws", side_effect=aws), patch.object(op, "project_test_template", return_value=(projected, None)), \
                     patch.object(op, "sam_libraries", return_value=(None, None, None, None, None,
                         lambda params: SimpleNamespace(resolve_parameter_refs=lambda value: value))), \
                     patch.object(op.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
                    if drift or post_drift:
                        with self.assertRaises(ValueError): op.main()
                    else: op.main()
                self.assertEqual(len(executions), 0 if drift else 1)
                if not drift:
                    self.assertTrue(all(len(call.args) == 3 for call in capture.call_args_list[:-1]))
                    self.assertEqual(len(capture.call_args_list[-1].args), 2, "post-execute incorrectly requires the running workflow to be completed")

    def test_review_sends_code_only_candidate_to_cfn_and_execute_uses_same_guard(self):
        self.run_cycle()

    def test_future_native_original_can_return_to_sam_for_a_different_package(self):
        self.run_cycle(identical=False)

    def test_changed_package_postguard_rejects_unreviewed_native_properties(self):
        self.run_cycle(identical=False, post_drift=True)

    def test_source_rejection_precedes_semantic_projection_or_storage_writes(self):
        op = operator()
        package, snapshot, live, alias, versions = TestBindingTests().fixture()
        binding = TestBindingTests().read(op, package, snapshot, live, alias, versions)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "runtime-read.zip").write_bytes(package)
            (root / "lambda-code-sha256.txt").write_bytes((base64.b64encode(hashlib.sha256(package).digest()).decode() + "\n").encode())
            (root / "template.yaml").write_text("full altered source")
            arguments = ["operator", "--environment=test", "--execution=review", "--release-root=" + str(root),
                         "--source-sha=" + SOURCE, "--manifest-digest=" + "c" * 64]
            with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/test"}), patch("sys.argv", arguments), \
                 patch.object(op, "baseline", return_value=snapshot), patch.object(op, "runtime_management", return_value={"UpdateRuntimeOn": "Auto"}), \
                 patch.object(op, "test_release_binding", return_value=binding), \
                 patch.object(op, "sam_source_reference", side_effect=ValueError("native_runtime_release_rejected")), \
                 patch.object(op, "project_test_template") as project, patch.object(op, "aws") as aws:
                with self.assertRaises(ValueError): op.main()
                project.assert_not_called()
                aws.assert_not_called()

    def test_manual_test_workflow_installs_projection_in_the_operator_python(self):
        text = (ROOT / ".github/workflows/deploy-test.yml").read_text()
        self.assertIn("aws-sam-cli==1.163.0 aws-sam-translator==1.111.0", text,
                      "SAM installer is not an importable dependency of the operator")
        self.assertIn('"$NATIVE_RELEASE_PYTHON" .aws-sam/native-runtime-release.py', text)
        self.assertLess(text.index("Prepare pinned native projection runtime"), text.index("aws-actions/configure-aws-credentials@"))


if __name__ == "__main__":
    unittest.main()
