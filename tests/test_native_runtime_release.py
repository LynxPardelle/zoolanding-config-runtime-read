import datetime
import copy
import base64
import hashlib
import importlib.util
import inspect
import io
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


class NativeReleaseReviewTests(unittest.TestCase):
    def test_rollback_snapshot_accepts_only_its_reviewed_change_set(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("runtime_owned_preview", ROOT / "tools/native_runtime_release.py")
        op = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(op)
        self.assertIn("expected_change_set_arn", inspect.signature(op.require_stable_stack).parameters)
        stack_id = ("arn:aws:cloudformation:us-east-1:765932874577:stack/"
                    "zoolanding-config-runtime-read-test/654d8f60-6d02-11f1-aa08-0e6c5445b1d9")
        change = ("arn:aws:cloudformation:us-east-1:765932874577:changeSet/"
                  "thn-runtime-37081251335-1/18af46a4-c001-448c-b64d-4f46b8361341")
        stack = {"StackId": stack_id, "StackStatus": "UPDATE_ROLLBACK_COMPLETE",
                 "RoleARN": "arn:aws:iam::765932874577:role/zoolanding-config-runtime-read-test-cfn-exec"}
        names = ("ConfigRuntimeReadFunction", "ConfigRuntimeReadFunctionAliaslive",
                 "ConfigRuntimeReadFunctionRole", "ConfigRuntimeReadFunctionRuntimeBundleGetPermissionProd",
                 "ConfigRuntimeReadFunctionVersion375dd3b296", "RuntimeApi",
                 "RuntimeApiDeploymentda724c766a", "RuntimeApiProdStage")
        resources = [{"LogicalResourceId": name, "PhysicalResourceId": name,
                      "ResourceStatus": "UPDATE_COMPLETE"} for name in names]
        owned = {"StackId": stack_id, "StackName": "zoolanding-config-runtime-read-test",
                 "ChangeSetId": change, "ChangeSetName": "thn-runtime-37081251335-1",
                 "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE"}
        for summaries, allowed in (([owned], True), ([], False),
                                   ([owned, dict(owned, ChangeSetId=change + "-other")], False),
                                   ([dict(owned, Status="FAILED")], False),
                                   ([dict(owned, StackId=stack_id + "-other")], False)):
            with self.subTest(summaries=summaries):
                with patch.object(op, "aws", return_value={"Summaries": summaries}):
                    if allowed:
                        op.require_stable_stack(op.PROFILES["test"], stack, resources,
                                                expected_change_set_arn=change)
                    else:
                        with self.assertRaises(ValueError):
                            op.require_stable_stack(op.PROFILES["test"], stack, resources,
                                                    expected_change_set_arn=change)

    def test_stable_test_rollback_can_be_read_but_unsafe_states_cannot(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("runtime_rollback_guard", ROOT / "tools/native_runtime_release.py")
        op = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(op)
        role = "arn:aws:iam::765932874577:role/zoolanding-config-runtime-read-test-cfn-exec"
        names = ("ConfigRuntimeReadFunction", "ConfigRuntimeReadFunctionAliaslive",
                 "ConfigRuntimeReadFunctionRole", "ConfigRuntimeReadFunctionRuntimeBundleGetPermissionProd",
                 "ConfigRuntimeReadFunctionVersion375dd3b296", "RuntimeApi",
                 "RuntimeApiDeploymentda724c766a", "RuntimeApiProdStage")
        resources = [{"LogicalResourceId": name, "PhysicalResourceId": name,
                      "ResourceType": "AWS::Lambda::Function" if name == names[0] else "AWS::CloudFormation::CustomResource",
                      "ResourceStatus": "CREATE_COMPLETE" if "Version" in name or "Deployment" in name else "UPDATE_COMPLETE"}
                     for name in names]
        stack = {"StackId": "arn:aws:cloudformation:us-east-1:765932874577:stack/zoolanding-config-runtime-read-test/654d8f60-6d02-11f1-aa08-0e6c5445b1d9",
                 "StackStatus": "UPDATE_ROLLBACK_COMPLETE", "RoleARN": role, "Parameters": [], "Outputs": []}

        def read(*args):
            if args[:2] == ("sts", "get-caller-identity"): return {"Account": "765932874577"}
            if args[:2] == ("cloudformation", "describe-stacks"): return {"Stacks": [stack]}
            if args[:2] == ("cloudformation", "list-stack-resources"): return {"StackResourceSummaries": resources}
            if args[:2] == ("cloudformation", "list-change-sets"): return {"Summaries": []}
            if args[:2] == ("lambda", "get-function-configuration"): return {"FunctionName": names[0]}
            if args[:2] == ("cloudformation", "get-template"): return {"TemplateBody": {"Resources": {}}}
            raise AssertionError(args)

        with patch.dict("os.environ", {"AWS_REGION": "us-east-1"}), patch.object(op, "aws", side_effect=read):
            snapshot = op.baseline(op.PROFILES["test"])
        self.assertEqual(snapshot["stackId"], stack["StackId"])
        self.assertEqual(len(snapshot["identities"]), 8)
        self.assertEqual(snapshot["stackStatus"], "UPDATE_ROLLBACK_COMPLETE")

        invalid = (
            ("status", "UPDATE_ROLLBACK_IN_PROGRESS"),
            ("status", "UPDATE_ROLLBACK_FAILED"),
            ("role", "arn:aws:iam::765932874577:role/another-role"),
            ("resources", resources[:-1]),
            ("resource_status", "UPDATE_FAILED"),
            ("changes", [{"Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE"}]),
        )
        for mutation, value in invalid:
            with self.subTest(mutation=mutation):
                current_stack = copy.deepcopy(stack)
                current_resources = copy.deepcopy(resources)
                changes = []
                if mutation == "status": current_stack["StackStatus"] = value
                if mutation == "role": current_stack["RoleARN"] = value
                if mutation == "resources": current_resources = value
                if mutation == "resource_status": current_resources[0]["ResourceStatus"] = value
                if mutation == "changes": changes = value

                def unsafe(*args):
                    if args[:2] == ("cloudformation", "describe-stacks"): return {"Stacks": [current_stack]}
                    if args[:2] == ("cloudformation", "list-stack-resources"): return {"StackResourceSummaries": current_resources}
                    if args[:2] == ("cloudformation", "list-change-sets"): return {"Summaries": changes}
                    return read(*args)

                with patch.dict("os.environ", {"AWS_REGION": "us-east-1"}), patch.object(op, "aws", side_effect=unsafe), self.assertRaises(ValueError):
                    op.baseline(op.PROFILES["test"])
        with patch.dict("os.environ", {"AWS_REGION": "us-east-1"}), patch.object(op, "aws", side_effect=read), self.assertRaises(ValueError):
            op.baseline(op.PROFILES["production"])

    def test_live_test_zip_accepts_only_complete_test_rollback(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("runtime_rollback_zip", ROOT / "tools/native_runtime_release.py")
        op = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(op)
        package = b"same-retained-zip"
        function = "zoolanding-config-runtime-ConfigRuntimeReadFunctio-h2B86UU86X18"
        role = "arn:aws:iam::765932874577:role/zoolanding-config-runtime-read-test-cfn-exec"
        names = ("ConfigRuntimeReadFunction", "ConfigRuntimeReadFunctionAliaslive",
                 "ConfigRuntimeReadFunctionRole", "ConfigRuntimeReadFunctionRuntimeBundleGetPermissionProd",
                 "ConfigRuntimeReadFunctionVersion375dd3b296", "RuntimeApi",
                 "RuntimeApiDeploymentda724c766a", "RuntimeApiProdStage")
        resources = [{"LogicalResourceId": name, "PhysicalResourceId": function if name == names[0] else name,
                      "ResourceType": "AWS::Lambda::Function" if name == names[0] else "AWS::CloudFormation::CustomResource",
                      "ResourceStatus": "CREATE_COMPLETE" if "Version" in name or "Deployment" in name else "UPDATE_COMPLETE"}
                     for name in names]
        stack = {"StackId": "arn:aws:cloudformation:us-east-1:765932874577:stack/zoolanding-config-runtime-read-test/654d8f60-6d02-11f1-aa08-0e6c5445b1d9",
                 "StackStatus": "UPDATE_ROLLBACK_COMPLETE", "RoleARN": role}

        def read(*args):
            if args[:2] == ("cloudformation", "describe-stacks"): return {"Stacks": [stack]}
            if args[:2] == ("cloudformation", "list-stack-resources"): return {"StackResourceSummaries": resources}
            if args[:2] == ("cloudformation", "list-change-sets"): return {"Summaries": []}
            if args[:2] == ("cloudformation", "describe-stack-resource"): return {"StackResourceDetail": {"PhysicalResourceId": function}}
            if args[:2] == ("lambda", "get-alias"): return {"FunctionVersion": "4", "RevisionId": "same"}
            if args[:2] == ("lambda", "get-function"):
                return {"Configuration": {"State": "Active", "LastUpdateStatus": "Successful",
                                          "CodeSha256": base64.b64encode(hashlib.sha256(package).digest()).decode(),
                                          "RevisionId": "same"},
                        "Code": {"Location": "https://awslambda-us-east-1-tasks.s3.us-east-1.amazonaws.com/same"}}
            raise AssertionError(args)

        with patch.object(op, "aws", side_effect=read), patch.object(op, "urlopen", return_value=io.BytesIO(package)):
            result = op.live_test_zip(package)
        self.assertEqual(result["version"], "4")

    def test_source_built_release_preserves_live_api_metadata_at_native_guard(self):
        builder_spec = importlib.util.spec_from_file_location("runtime_builder", ROOT / "tools/build_lambda_artifact.py")
        builder = importlib.util.module_from_spec(builder_spec)
        builder_spec.loader.exec_module(builder)
        source = (ROOT / "template.yaml").read_text(encoding="utf-8")
        # SAM build relocates this single local CodeUri; execute the real sealed
        # release-template assembler without introducing undeclared YAML packages.
        anchor = "      CodeUri: .build/runtime-read\n"
        self.assertEqual(source.count(anchor), 1)
        built = source.replace(anchor, "      CodeUri: ConfigRuntimeReadFunction\n")
        release = builder._build_test_release_template(built)
        blocks = re.findall(r"(?ms)^  RuntimeApi:\n(.*?)(?=^  [A-Za-z]|\Z)", release)
        self.assertEqual(len(blocks), 1)
        ids = re.findall(r"(?m)^    Metadata:\n      SamResourceId: ([A-Za-z0-9]+)\n", blocks[0])
        self.assertLessEqual(len(ids), 1)
        operator_spec = importlib.util.spec_from_file_location("runtime_native_guard", ROOT / "tools/native_runtime_release.py")
        operator = importlib.util.module_from_spec(operator_spec)
        operator_spec.loader.exec_module(operator)
        function = {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": "before", "S3Key": "before"}, "Role": {"Ref": "ExistingRole"}}}
        api = {"Type": "AWS::ApiGateway::RestApi", "Properties": {"Name": {"Ref": "AWS::StackName"}}, "Metadata": {"SamResourceId": "RuntimeApi"}}
        before = {"Resources": {"ConfigRuntimeReadFunction": function, "RuntimeApi": api}}
        candidate = copy.deepcopy(before)
        candidate["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"] = {"S3Bucket": "zoolanding-config-payloads-test", "S3Key": "system/thn-runtime/releases/" + "a" * 40 + "/" + "b" * 64 + ".zip", "S3ObjectVersion": "sealed-version"}
        candidate["Resources"]["RuntimeApi"].pop("Metadata")
        if ids:
            candidate["Resources"]["RuntimeApi"]["Metadata"] = {"SamResourceId": ids[0]}
        changes = [{"Type": "Resource", "ResourceChange": {"LogicalResourceId": "ConfigRuntimeReadFunction", "ResourceType": "AWS::Lambda::Function", "Action": "Modify", "Replacement": "False", "Details": [{"Target": {"Attribute": "Properties", "Name": "Code"}}]}}]
        try:
            operator.review_resources(before, candidate, changes, "test", "a" * 40, "b" * 64)
        except ValueError:
            self.fail("Source-built release drops existing RuntimeApi metadata and the real native guard rejects it")
        for mutation in ("missing", "different"):
            altered = copy.deepcopy(candidate)
            if mutation == "missing":
                altered["Resources"]["RuntimeApi"].pop("Metadata")
            else:
                altered["Resources"]["RuntimeApi"]["Metadata"]["SamResourceId"] = "AnotherApi"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                operator.review_resources(before, altered, changes, "test", "a" * 40, "b" * 64)

    def test_real_native_resource_shapes_reject_configuration_or_iam_scope_expansion(self):
        path=ROOT/"tools/native_runtime_release.py"
        self.assertTrue(path.is_file(), "runtime has no native review/execute boundary")
        spec=importlib.util.spec_from_file_location("native_release",path); op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
        before={"Resources":{"ConfigRuntimeReadFunction":{"Type":"AWS::Lambda::Function","Properties":{
            "Code":{"S3Bucket":"before","S3Key":"before"},"Environment":{"Variables":{"ENVIRONMENT_NAME":"prod"}},"Role":{"Ref":"ExistingRole"}}}}}
        candidate=copy.deepcopy(before); candidate["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"]={"S3Bucket":"zoolanding-config-payloads","S3Key":"system/thn-runtime/releases/"+"a"*40+"/"+"b"*64+".zip","S3ObjectVersion":"sealed-version"}
        changes=[{"Type":"Resource","ResourceChange":{"LogicalResourceId":"ConfigRuntimeReadFunction","ResourceType":"AWS::Lambda::Function","Action":"Modify","Replacement":"False","Scope":["Properties"],"Details":[{"Target":{"Attribute":"Properties","Name":"Code","RequiresRecreation":"Never"}}]}}]
        op.review_resources(before,candidate,changes,"production","a"*40,"b"*64)
        for mutation in ("environment","role","bucket","replacement","iam"):
            prior,current,inventory=map(copy.deepcopy,(before,candidate,changes))
            if mutation=="environment": current["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Environment"]["Variables"]["ENVIRONMENT_NAME"]="test"
            if mutation=="role": current["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Role"]={"Ref":"NewRole"}
            if mutation=="bucket": current["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"]["S3Bucket"]="test-bucket"
            if mutation=="replacement": inventory[0]["ResourceChange"]["Replacement"]="Conditional"
            if mutation=="iam": inventory.append({"Type":"Resource","ResourceChange":{"LogicalResourceId":"NewPolicy","ResourceType":"AWS::IAM::Policy","Action":"Add","Replacement":"False"}})
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):op.review_resources(prior,current,inventory,"production","a"*40,"b"*64)


    def test_unversioned_bucket_is_rejected_before_any_write(self):
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location("native_release",ROOT/"tools/native_runtime_release.py")
        op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
        check=getattr(op,"require_versioned_bucket",None)
        self.assertTrue(callable(check), "operator may write before bucket versioning is checked")
        for response in ({}, {"Status":"Suspended"}):
            with patch.object(op,"aws",return_value=response) as call, self.assertRaises(ValueError):
                check(op.PROFILES["production"])
            call.assert_called_once_with("s3api","get-bucket-versioning","--bucket","zoolanding-config-payloads","--expected-bucket-owner","765932874577")
        with patch.object(op,"aws",return_value={"Status":"Enabled"}):
            check(op.PROFILES["production"])

    def test_digest_freezes_operation_and_full_native_coordinates(self):
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location("native_release",ROOT/"tools/native_runtime_release.py")
        op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
        description={"CreationTime":datetime.datetime.now(datetime.timezone.utc).isoformat(),"ChangeSetId":"retained-arn","StackId":"stack-arn","Parameters":[{"ParameterKey":"EnvironmentName","ParameterValue":"prod"}],"Changes":[{"Type":"Resource","ResourceChange":{"Action":"Modify","PhysicalResourceId":"same-function","Details":[{"Target":{"Name":"Code"}}]}}]}
        def digest(value):return op.preview_digest({},value,{"Code":{"S3ObjectVersion":"v1"}},{"Code":{"S3ObjectVersion":"v1"}},"a"*40,"b"*64,"c"*64)
        with patch.dict("os.environ",{"GITHUB_SHA":"d"*40},clear=True):initial=digest(description)
        with patch.dict("os.environ",{"GITHUB_SHA":"e"*40},clear=True):self.assertNotEqual(initial,digest(description))
        altered=copy.deepcopy(description);altered["Changes"][0]["ResourceChange"]["PhysicalResourceId"]="changed"
        with patch.dict("os.environ",{"GITHUB_SHA":"d"*40},clear=True):self.assertNotEqual(initial,digest(altered))

    def test_post_execution_preserves_noncode_configuration_and_identities(self):
        spec=importlib.util.spec_from_file_location("native_release",ROOT/"tools/native_runtime_release.py")
        op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
        check=getattr(op,"verify_preserved_state",None)
        self.assertTrue(callable(check), "postflight checks only the Lambda identity")
        before={"stackId":"stack", "parameters":[],"outputs":[],"identities":[{"LogicalResourceId":"RuntimeApi","PhysicalResourceId":"api","ResourceType":"AWS::ApiGateway::RestApi"},{"LogicalResourceId":"ConfigRuntimeReadFunction","PhysicalResourceId":"function","ResourceType":"AWS::Lambda::Function"}],"functions":[{"FunctionName":"function","Role":"existing","Environment":{"Variables":{"ENVIRONMENT_NAME":"prod"}},"CodeSha256":"old","RevisionId":"old"}]}
        after=copy.deepcopy(before);after["functions"][0].update(CodeSha256="new",RevisionId="new")
        check(before,after,"production","new")
        for part in ("identity","role","environment","parameters"):
            changed=copy.deepcopy(after)
            if part=="identity":changed["identities"][0]["PhysicalResourceId"]="different-api"
            if part=="role":changed["functions"][0]["Role"]="new-role"
            if part=="environment":changed["functions"][0]["Environment"]["Variables"]["ENVIRONMENT_NAME"]="test"
            if part=="parameters":changed["parameters"]=[{"ParameterKey":"unexpected","ParameterValue":"new"}]
            with self.subTest(part=part),self.assertRaises(ValueError):check(before,changed,"production","new")


class ManagedProductionRuntimeTests(unittest.TestCase):
    def operator(self):
        spec=importlib.util.spec_from_file_location("managed_runtime_operator",ROOT/"tools/native_runtime_release.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def snapshots(self,mode="Auto"):
        function={"FunctionName":"existing","FunctionArn":"arn:aws:lambda:us-east-1:765932874577:function:existing",
                  "Runtime":"python3.13","PackageType":"Zip","Architectures":["x86_64"],"Role":"existing-role",
                  "Environment":{"Variables":{"ENVIRONMENT_NAME":"prod"}},"Handler":"lambda_function.lambda_handler",
                  "RuntimeVersionConfig":{"RuntimeVersionArn":"arn:aws:lambda:us-east-1::runtime:"+"1"*64},"CodeSha256":"old"}
        before={"stackId":"same-stack","parameters":[],"outputs":[],"identities":[],"functions":[function],
                "runtimeManagement":{"UpdateRuntimeOn":mode}}
        after=copy.deepcopy(before);after["functions"][0]["CodeSha256"]="new"
        after["functions"][0]["RuntimeVersionConfig"]["RuntimeVersionArn"]="arn:aws:lambda:us-east-1::runtime:"+"2"*64
        return before,after

    def test_production_managed_patch_postflight_accepts_only_verified_automatic_modes(self):
        op=self.operator()
        for mode in ("Auto","FunctionUpdate"):
            before,after=self.snapshots(mode)
            with self.subTest(mode=mode):op.verify_preserved_state(before,after,"production","new")
        for mode in ("Manual",None,"unknown"):
            before,after=self.snapshots(mode)
            with self.subTest(mode=mode),self.assertRaises(ValueError):op.verify_preserved_state(before,after,"production","new")
        before,after=self.snapshots();after["runtimeManagement"]["UpdateRuntimeOn"]="FunctionUpdate"
        with self.assertRaises(ValueError):op.verify_preserved_state(before,after,"production","new")
        before,after=self.snapshots()
        for value in ({},None,{"UpdateRuntimeOn":"Auto","Unknown":"unexpected"}):
            changed=copy.deepcopy(after);changed["runtimeManagement"]=value
            with self.subTest(value=value),self.assertRaises(ValueError):op.verify_preserved_state(before,changed,"production","new")

    def test_production_patch_exception_rejects_other_configuration_and_invalid_metadata(self):
        op=self.operator();before,after=self.snapshots()
        for key,value in (("Runtime","python3.14"),("Architectures",["arm64"]),("PackageType","Image"),
                          ("Role","changed"),("Environment",{"Variables":{"ENVIRONMENT_NAME":"test"}}),
                          ("Handler","changed.handler"),("Unknown",True),
                          ("RuntimeVersionConfig",{}),("RuntimeVersionConfig",None),
                          ("RuntimeVersionConfig",{"RuntimeVersionArn":"arn:aws:lambda:us-west-2::runtime:"+"2"*64}),
                          ("RuntimeVersionConfig",{"RuntimeVersionArn":"arn:aws:lambda:us-east-1::runtime:"+"2"*64,"Error":{"ErrorCode":"InvalidRuntime"}})):
            changed=copy.deepcopy(after);changed["functions"][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):op.verify_preserved_state(before,changed,"production","new")
        with self.assertRaises(ValueError):op.verify_preserved_state(before,after,"test","new")

    def test_runtime_management_reads_exact_function_and_matches_native_template(self):
        from unittest.mock import patch
        op=self.operator();before,_=self.snapshots();function=before["functions"][0]
        template={"Resources":{"ConfigRuntimeReadFunction":{"Properties":{}}}}
        read=getattr(op,"runtime_management",None)
        self.assertTrue(callable(read),"production baseline has no verified runtime management mode")
        for mode in ("Auto","FunctionUpdate","Manual"):
            current=copy.deepcopy(template);setting={"UpdateRuntimeOn":mode}
            if mode=="Manual":setting["RuntimeVersionArn"]=function["RuntimeVersionConfig"]["RuntimeVersionArn"]
            if mode!="Auto":current["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["RuntimeManagementConfig"]=setting
            response={"FunctionArn":function["FunctionArn"],"UpdateRuntimeOn":mode,
                      "RuntimeVersionArn":setting.get("RuntimeVersionArn")}
            with patch.object(op,"aws",return_value=response) as call:
                self.assertEqual(read(function,current),setting)
                call.assert_called_once_with("lambda","get-runtime-management-config","--function-name",function["FunctionName"])
        valid={"FunctionArn":function["FunctionArn"],"UpdateRuntimeOn":"Auto","RuntimeVersionArn":None}
        for mutation in ({"FunctionArn":function["FunctionArn"]+":1"},{"UpdateRuntimeOn":"Manual"},
                         {"UpdateRuntimeOn":"unexpected"},{"RuntimeVersionArn":"unexpected"},{"Unexpected":"extra"}):
            with patch.object(op,"aws",return_value={**valid,**mutation}),self.subTest(mutation=mutation),self.assertRaises(ValueError):read(function,template)
        for missing in ("FunctionArn","UpdateRuntimeOn"):
            response=copy.deepcopy(valid);response.pop(missing)
            with patch.object(op,"aws",return_value=response),self.assertRaises(ValueError):read(function,template)
        with patch.object(op,"aws",side_effect=ValueError("read unavailable")),self.assertRaises(ValueError):read(function,template)

    def test_digest_keeps_exact_patch_and_mode_before_execution(self):
        from unittest.mock import patch
        op=self.operator();before,after=self.snapshots()
        description={"CreationTime":datetime.datetime.now(datetime.timezone.utc).isoformat(),"ChangeSetId":"retained-arn","StackId":"stack-arn","Parameters":[],"Changes":[]}
        with patch.dict("os.environ",{"GITHUB_SHA":"d"*40},clear=True):
            digest=lambda snapshot:op.preview_digest(snapshot,description,{}, {},"a"*40,"b"*64,"c"*64)
            initial=digest(before)
            modified=copy.deepcopy(before);modified["functions"][0]["RuntimeVersionConfig"]=after["functions"][0]["RuntimeVersionConfig"]
            self.assertNotEqual(initial,digest(modified))
            modified=copy.deepcopy(before);modified["runtimeManagement"]["UpdateRuntimeOn"]="FunctionUpdate"
            self.assertNotEqual(initial,digest(modified))


    def test_baseline_seals_management_and_raw_patch_only_in_production(self):
        from unittest.mock import patch
        op=self.operator();before,_=self.snapshots();function=before["functions"][0]
        template={"Resources":{"ConfigRuntimeReadFunction":{"Properties":{}}}}
        for environment in ("test","production"):
            profile=op.PROFILES[environment]
            def read(*args):
                if args[:2]==("sts","get-caller-identity"):return {"Account":"765932874577"}
                if args[:2]==("cloudformation","describe-stacks"):
                    return {"Stacks":[{"StackId":"same-stack","StackStatus":"UPDATE_COMPLETE","RoleARN":"arn:aws:iam::765932874577:role/zoolanding-config-runtime-read-production-cfn-exec"}]}
                if args[:2]==("cloudformation","list-stack-resources"):
                    return {"StackResourceSummaries":[{"LogicalResourceId":"ConfigRuntimeReadFunction","PhysicalResourceId":"existing","ResourceType":"AWS::Lambda::Function"}]}
                if args[:2]==("lambda","get-function-configuration"):return copy.deepcopy(function)
                if args[:2]==("cloudformation","get-template"):return {"TemplateBody":copy.deepcopy(template)}
                if args[:2]==("lambda","get-runtime-management-config"):
                    return {"FunctionArn":function["FunctionArn"],"UpdateRuntimeOn":"Auto","RuntimeVersionArn":None}
                raise AssertionError("unexpected read")
            with patch.dict("os.environ",{"AWS_REGION":"us-east-1"}),patch.object(op,"aws",side_effect=read) as calls, \
                 patch.object(op,"source_authority",return_value={}),patch.object(op,"permission_authority",return_value={}):
                snapshot=op.baseline(profile)
            self.assertEqual(snapshot["functions"][0]["RuntimeVersionConfig"],function["RuntimeVersionConfig"])
            management=[call for call in calls.call_args_list if call.args[:2]==("lambda","get-runtime-management-config")]
            if environment=="production":
                self.assertEqual(snapshot["runtimeManagement"],{"UpdateRuntimeOn":"Auto"})
                self.assertEqual(len(management),1)
            else:
                self.assertNotIn("runtimeManagement",snapshot)
                self.assertEqual(management,[])
