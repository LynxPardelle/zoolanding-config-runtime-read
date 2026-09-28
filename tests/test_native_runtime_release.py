import datetime
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class NativeReleaseReviewTests(unittest.TestCase):
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
