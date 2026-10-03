"""Manual retained native preview; exact ZIP, no storage/IAM/API reconfiguration."""
import argparse
import base64
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen
try:
    from native_release_authority import source_authority, permission_authority, review_window
except ModuleNotFoundError:
    from tools.native_release_authority import source_authority, permission_authority, review_window

PROFILES={"test":{"stack":"zoolanding-config-runtime-read-test","bucket":"zoolanding-config-payloads-test"},
          "production":{"stack":"zoolanding-config-runtime-read","bucket":"zoolanding-config-payloads"}}


def _reject(): raise ValueError("native_runtime_release_rejected")


def _template(value):
    if isinstance(value,str): value=json.loads(value)
    if not isinstance(value,dict) or not isinstance(value.get("Resources"),dict):_reject()
    return value


def production_candidate_source(text):
    """Invert only the TEST packaging grammar before any production write."""
    transform = (
        "Transform:\n"
        "- AWS::LanguageExtensions\n"
        "- AWS::Serverless-2016-10-31\n"
        "Description:"
    )
    function = (
        "  ConfigRuntimeReadFunction:\n"
        "    Type: AWS::Serverless::Function\n"
        "    Properties:\n"
        "      CodeUri: runtime-read.zip\n"
        "      AutoPublishAlias: live\n"
        "      AutoPublishAliasAllProperties: true\n"
        "      VersionDeletionPolicy: Retain\n"
    )
    if (not isinstance(text, str) or "\r" in text
        or not text.startswith("AWSTemplateFormatVersion: '2010-09-09'\n" + transform)
        or text.count(transform) != 1
        or len(re.findall(r"(?m)^\s*Transform\s*:", text)) != 1
        or text.count("AWS::LanguageExtensions") != 1
        or text.count("AWS::Serverless-2016-10-31") != 1
        or text.count(function) != 1
        or text.count("CodeUri: runtime-read.zip") != 1
        or any(text.count(name) != 1 for name in (
            "AutoPublishAlias:", "AutoPublishAliasAllProperties:", "VersionDeletionPolicy:"))
        or any(name in text for name in (
            "Fn::ForEach", "Fn::Length", "Fn::ToJsonString", "Fn::Transform"))): _reject()
    return (text.replace(transform, "Transform: AWS::Serverless-2016-10-31\nDescription:", 1)
                .replace(function, (
                    "  ConfigRuntimeReadFunction:\n"
                    "    Type: AWS::Serverless::Function\n"
                    "    Properties:\n"
                    "      CodeUri: runtime-read.zip\n"), 1))


def native_template(value):
    value = _template(value)
    if "Transform" in value or "Globals" in value: _reject()
    def visit(node):
        if isinstance(node, dict):
            if "Fn::Transform" in node: _reject()
            for child in node.values(): visit(child)
        elif isinstance(node, list):
            for child in node: visit(child)
    visit(value)
    if any(not isinstance(resource, dict) or not isinstance(resource.get("Type"), str)
           or resource["Type"].startswith("AWS::Serverless::") for resource in value["Resources"].values()): _reject()
    return value


def sam_libraries():
    if (importlib.metadata.version("aws-sam-cli") != "1.163.0"
        or importlib.metadata.version("aws-sam-translator") != "1.111.0"): _reject()
    from samcli.yamlhelper import yaml_parse
    from samcli.lib.cfn_language_extensions.sam_integration import expand_language_extensions
    from samtranslator.parser.parser import Parser
    from samtranslator.translator.translator import Translator
    from samtranslator.utils.py27hash_fix import to_py27_compatible_template, undo_mark_unicode_str_in_template
    from samcli.lib.cfn_language_extensions.api import process_template
    from samcli.lib.cfn_language_extensions.models import PseudoParameterValues
    from boto3 import Session
    def translate(fragment, values):
        fragment, values = copy.deepcopy(fragment), copy.deepcopy(values)
        # The official transform entry point includes these compatibility steps.
        # Omitting them changes generated API IDs and tag order under Python 3.
        to_py27_compatible_template(fragment, values)
        translator = Translator(managed_policy_map={}, sam_parser=Parser(), plugins=[], boto_session=Session(region_name="us-east-1"))
        result = translator.translate(fragment, values, get_managed_policy_map=lambda: {}, passthrough_metadata=False)
        return undo_mark_unicode_str_in_template(result)
    class SemanticResolver:
        def __init__(self, values):
            self.values = copy.deepcopy(values)
        def resolve_parameter_refs(self, template):
            pseudos = PseudoParameterValues(region=self.values["AWS::Region"], account_id=self.values["AWS::AccountId"],
                stack_name=self.values["AWS::StackName"], stack_id=self.values["AWS::StackId"],
                partition=self.values["AWS::Partition"], url_suffix=self.values["AWS::URLSuffix"])
            return process_template(copy.deepcopy(template), self.values, pseudos)
    return yaml_parse, expand_language_extensions, translate, None, None, SemanticResolver


def verify_sam_source(candidate_text, original):
    parse = sam_libraries()[0]
    candidate = parse(candidate_text)
    prior = parse(original) if isinstance(original, str) else copy.deepcopy(original)
    for template in (prior, candidate):
        if template.get("Transform") != ["AWS::LanguageExtensions", "AWS::Serverless-2016-10-31"]: _reject()
        template["Resources"]["ConfigRuntimeReadFunction"]["Properties"].pop("CodeUri")
    if _canonical(prior) != _canonical(candidate): _reject()


def _github_read(path):
    result = subprocess.run(["gh", "api", "repos/LynxPardelle/zoolanding-config-runtime-read/" + path],
                            capture_output=True, text=True, timeout=30)
    if result.returncode: _reject()
    return json.loads(result.stdout)


def previous_test_execution(source):
    """A Code pointer is insufficient without its successful protected execution."""
    if not re.fullmatch(r"[a-f0-9]{40}", str(source)): _reject()
    response = _github_read(f"actions/workflows/deploy-test.yml/runs?head_sha={source}&event=workflow_dispatch&status=success&per_page=100")
    runs = response.get("workflow_runs")
    if (not isinstance(runs, list) or type(response.get("total_count")) is not int
        or response["total_count"] != len(runs) or len(runs) > 10
        or any(not isinstance(run, dict) or type(run.get("id")) is not int or run["id"] < 1 for run in runs)
        or len({run["id"] for run in runs}) != len(runs)): _reject()
    for run in sorted(runs, key=lambda item: item["id"], reverse=True):
        if (run.get("head_sha") != source or run.get("head_branch") != "test" or run.get("event") != "workflow_dispatch"
            or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("path") != ".github/workflows/deploy-test.yml"
            or run.get("repository", {}).get("full_name") != "LynxPardelle/zoolanding-config-runtime-read"
            or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1): _reject()
        result = _github_read(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
        jobs = result.get("jobs")
        if (not isinstance(jobs, list) or type(result.get("total_count")) is not int
            or result["total_count"] != len(jobs) or any(not isinstance(job, dict) for job in jobs)): _reject()
        deploys = [job for job in jobs if job.get("name") == "deploy"]
        if len(deploys) != 1: _reject()
        job = deploys[0]
        if (job.get("run_id") != run["id"] or job.get("head_sha") != source
            or job.get("status") != "completed" or not isinstance(job.get("steps"), list)): _reject()
        if job.get("conclusion") != "success": continue
        steps = job["steps"]
        if any(not isinstance(step, dict) for step in steps): _reject()
        required = [ [step for step in steps if step.get("name") == name]
                     for name in ("Deploy test", "Verify immutable live alias")]
        if any(len(matches) != 1 for matches in required): _reject()
        if all(matches[0].get("status") == "completed" and matches[0].get("conclusion") == "success" for matches in required):
            return {"runId": run["id"], "runAttempt": run["run_attempt"], "headSha": source}
    _reject()


def sam_source_reference(snapshot, candidate_text):
    parse = sam_libraries()[0]
    original = parse(snapshot["original"]) if isinstance(snapshot["original"], str) else copy.deepcopy(snapshot["original"])
    if "Transform" in original:
        verify_sam_source(candidate_text, original)
        return {"kind": "cloudformation-original", "samSha256": hashlib.sha256(_canonical(original)).hexdigest()}
    # A native Code-only template has no remaining SAM source. Recover the exact
    # closed build grammar from the immutable Git revision named by its package.
    if os.getenv("GITHUB_REPOSITORY") != "LynxPardelle/zoolanding-config-runtime-read": _reject()
    code = native_template(snapshot["processed"])["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"]
    match = re.fullmatch(r"system/thn-runtime/releases/([a-f0-9]{40})/([a-f0-9]{64})\.zip", str(code.get("S3Key", "")))
    if (not match or code.get("S3Bucket") != PROFILES["test"]["bucket"] or not code.get("S3ObjectVersion")
        or code["S3ObjectVersion"] == "null" or match[2] != snapshot["testReleaseBinding"]["qualifiedZipSha256"]): _reject()
    source = match[1]
    response = _github_read(f"contents/template.yaml?ref={source}")
    if (response.get("type") != "file" or response.get("path") != "template.yaml" or response.get("encoding") != "base64"
        or not isinstance(response.get("size"), int) or not 0 < response["size"] <= 65536): _reject()
    raw = base64.b64decode("".join(response["content"].split()), validate=True)
    blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if len(raw) != response["size"] or blob_sha != response.get("sha"): _reject()
    template = parse(raw.decode("utf-8"))
    function = template["Resources"]["ConfigRuntimeReadFunction"]
    if (template.get("Transform") != "AWS::Serverless-2016-10-31"
        or set(template["Resources"]) != {"RuntimeApi", "ConfigRuntimeReadFunction"}
        or function.get("Type") != "AWS::Serverless::Function" or "Metadata" in function
        or function["Properties"].get("CodeUri") != ".build/runtime-read"
        or any(key in function["Properties"] for key in ("AutoPublishAlias", "AutoPublishAliasAllProperties", "VersionDeletionPolicy"))
        or template["Resources"]["RuntimeApi"].get("Type") != "AWS::Serverless::Api"
        or template["Resources"]["RuntimeApi"].get("Metadata") != {"SamResourceId": "RuntimeApi"}): _reject()
    template["Transform"] = ["AWS::LanguageExtensions", "AWS::Serverless-2016-10-31"]
    function["Metadata"] = {"SamResourceId": "ConfigRuntimeReadFunction"}
    function["Properties"].update(CodeUri="runtime-read.zip", AutoPublishAlias="live", AutoPublishAliasAllProperties=True, VersionDeletionPolicy="Retain")
    verify_sam_source(candidate_text, template)
    execution = previous_test_execution(source)
    return {"kind": "previous-protected-git-sam", "sourceSha": source, "gitBlobSha": blob_sha,
            "rawSha256": hashlib.sha256(raw).hexdigest(), "samSha256": hashlib.sha256(_canonical(template)).hexdigest(),
            "execution": execution}


def project_test_template(text, snapshot, code):
    parse, expand, translate, _, _, _ = sam_libraries()
    template = parse(text)
    if template.get("Transform") != ["AWS::LanguageExtensions", "AWS::Serverless-2016-10-31"]: _reject()
    def reject_external_macro(node):
        if isinstance(node, dict):
            if "Fn::Transform" in node: _reject()
            for child in node.values(): reject_external_macro(child)
        elif isinstance(node, list):
            for child in node: reject_external_macro(child)
    reject_external_macro(template)
    actual = snapshot["parameters"]
    params = {item["ParameterKey"]: item["ParameterValue"] for item in actual}
    if len(params) != len(actual) or set(params) != set(template.get("Parameters", {})): _reject()
    if not all(isinstance(value, str) for value in params.values()): _reject()
    stack = snapshot["stackId"]
    if not re.fullmatch(r"arn:aws:cloudformation:us-east-1:765932874577:stack/zoolanding-config-runtime-read-test/[a-zA-Z0-9-]+", stack): _reject()
    params.update({"AWS::Region": "us-east-1", "AWS::AccountId": "765932874577", "AWS::Partition": "aws",
                   "AWS::URLSuffix": "amazonaws.com", "AWS::StackName": PROFILES["test"]["stack"], "AWS::StackId": stack})
    function = template["Resources"]["ConfigRuntimeReadFunction"]
    if function.get("Type") != "AWS::Serverless::Function" or function["Properties"].get("CodeUri") != "runtime-read.zip": _reject()
    function["Properties"]["CodeUri"] = {"Bucket": code["S3Bucket"], "Key": code["S3Key"], "Version": code["S3ObjectVersion"]}
    expanded = expand(copy.deepcopy(template), parameter_values=copy.deepcopy(params), enabled=True)
    projected = translate(expanded.expanded_template, copy.deepcopy(params))
    return native_template(projected), params


def code_pointer_candidate(before, projected, parameter_values=None):
    """Require the full promoted projection; preserve the original native topology."""
    before = native_template(before)
    projected = copy.deepcopy(native_template(projected))
    function = "ConfigRuntimeReadFunction"
    alias = function + "Aliaslive"
    prior_alias = before["Resources"][alias]
    next_alias = projected["Resources"][alias]
    def version_id(resource):
        reference = resource["Properties"].get("FunctionVersion")
        if (not isinstance(reference, dict) or set(reference) != {"Fn::GetAtt"}
            or not isinstance(reference["Fn::GetAtt"], list) or len(reference["Fn::GetAtt"]) != 2
            or reference["Fn::GetAtt"][1] != "Version"): _reject()
        return reference["Fn::GetAtt"][0]
    old_version, new_version = version_id(prior_alias), version_id(next_alias)
    for template, logical in ((before, old_version), (projected, new_version)):
        resource = template["Resources"].get(logical)
        if (not re.fullmatch(r"ConfigRuntimeReadFunctionVersion[a-zA-Z0-9]+", str(logical))
            or not isinstance(resource, dict) or resource.get("Type") != "AWS::Lambda::Version"
            or resource.get("DeletionPolicy") != "Retain"
            or resource.get("Properties") != {"FunctionName": {"Ref": function}}): _reject()
    if before["Resources"][old_version] != projected["Resources"][new_version]: _reject()
    if new_version != old_version:
        if old_version in projected["Resources"] or new_version in before["Resources"]: _reject()
        projected["Resources"][old_version] = projected["Resources"].pop(new_version)
        next_alias["Properties"]["FunctionVersion"] = copy.deepcopy(prior_alias["Properties"]["FunctionVersion"])
    code = projected["Resources"][function]["Properties"].pop("Code")
    comparable = copy.deepcopy(before)
    comparable["Resources"][function]["Properties"].pop("Code")
    if parameter_values is None:
        if projected != comparable: _reject()
    else:
        resolver = sam_libraries()[-1](parameter_values)
        if resolver.resolve_parameter_refs(copy.deepcopy(projected)) != resolver.resolve_parameter_refs(copy.deepcopy(comparable)): _reject()
    candidate = copy.deepcopy(before)
    candidate["Resources"][function]["Properties"]["Code"] = code
    return candidate


def test_release_binding(snapshot, package):
    """Seal the actual qualified bytes and every published version, never its URL."""
    if len(snapshot["functions"]) != 1: _reject()
    latest = snapshot["functions"][0]
    function = latest.get("FunctionName")
    arn = latest.get("FunctionArn")
    if (not isinstance(function, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", function)
        or arn != f"arn:aws:lambda:us-east-1:765932874577:function:{function}"
        or latest.get("Version") != "$LATEST" or latest.get("State") != "Active"
        or latest.get("LastUpdateStatus") != "Successful"): _reject()
    alias = aws("lambda", "get-alias", "--function-name", function, "--name", "live")
    version = alias.get("FunctionVersion")
    if (not re.fullmatch(r"[1-9][0-9]*", str(version)) or alias.get("Name") != "live"
        or alias.get("AliasArn") != arn + ":live" or not alias.get("RevisionId")
        or alias.get("RoutingConfig", {}) not in ({}, {"AdditionalVersionWeights": {}})): _reject()
    resources = native_template(snapshot["processed"])["Resources"]
    reference = resources["ConfigRuntimeReadFunctionAliaslive"]["Properties"]
    if reference.get("Name") != "live" or reference.get("FunctionName") != {"Ref": "ConfigRuntimeReadFunction"}: _reject()
    version_ref = reference.get("FunctionVersion", {}).get("Fn::GetAtt")
    if not isinstance(version_ref, list) or len(version_ref) != 2 or version_ref[1] != "Version": _reject()
    identities = {item["LogicalResourceId"]: item for item in snapshot["identities"]}
    if (identities.get("ConfigRuntimeReadFunction", {}).get("PhysicalResourceId") != function
        or identities.get("ConfigRuntimeReadFunctionAliaslive", {}).get("PhysicalResourceId") != arn + ":live"
        or identities.get(version_ref[0], {}).get("PhysicalResourceId") != arn + ":" + version): _reject()
    result = aws("lambda", "get-function", "--function-name", function, "--qualifier", version)
    qualified = result["Configuration"]
    if qualified.get("FunctionArn") != arn + ":" + version or qualified.get("Version") != version: _reject()
    identity_fields = {"FunctionArn", "RevisionId", "Version", "LastModified"}
    if {k:v for k,v in latest.items() if k not in identity_fields} != {k:v for k,v in qualified.items() if k not in identity_fields}: _reject()
    location = result["Code"]["Location"]
    lambda_task_url(location)
    with urlopen(location, timeout=20) as response:
        content = response.read(10 * 1024 * 1024 + 1)
    digest = hashlib.sha256(content).digest()
    if base64.b64encode(digest).decode() != qualified.get("CodeSha256"): _reject()
    versions = aws("lambda", "list-versions-by-function", "--function-name", function)
    if set(versions) - {"Versions", "NextMarker", "ResponseMetadata"} or versions.get("NextMarker"): _reject()
    published = sorted([item for item in versions["Versions"] if item.get("Version") != "$LATEST"], key=lambda item: item["Version"])
    if len({item["Version"] for item in published}) != len(published): _reject()
    if any(not re.fullmatch(r"[1-9][0-9]*", str(item.get("Version")))
           or item.get("FunctionArn") != arn + ":" + item["Version"] for item in published): _reject()
    matches = [item for item in published if item["Version"] == version]
    if len(matches) != 1 or matches[0].get("CodeSha256") != qualified["CodeSha256"]: _reject()
    return {"alias": alias, "qualifiedConfiguration": qualified, "publishedVersions": published,
            "qualifiedZipSha256": digest.hex(), "identicalPackage": content == package}


def verify_neutral_state(before, after, code):
    if (before.get("testReleaseBinding", {}).get("identicalPackage") is not True
        or before["testReleaseBinding"] != after.get("testReleaseBinding")
        or before["identities"] != after["identities"]
        or before.get("runtimeManagement") != after.get("runtimeManagement")): _reject()
    expected = copy.deepcopy(native_template(before["processed"]))
    expected["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"] = code
    if expected != native_template(after["processed"]): _reject()


def review_resources(before,candidate,changes,environment,source_sha,zip_digest,*,identical_package=False):
    if environment not in PROFILES or not re.fullmatch(r"[a-f0-9]{40}",source_sha) or not re.fullmatch(r"[a-f0-9]{64}",zip_digest):_reject()
    before = _template(before); candidate = _template(candidate)
    if {k:v for k,v in before.items() if k != "Resources"} != {k:v for k,v in candidate.items() if k != "Resources"}: _reject()
    prior=before["Resources"]; current=candidate["Resources"]
    if identical_package:
        if environment != "test" or code_pointer_candidate(before, candidate) != candidate: _reject()
        if len(changes) != 1 or changes[0].get("ResourceChange", {}).get("LogicalResourceId") != "ConfigRuntimeReadFunction": _reject()
    function="ConfigRuntimeReadFunction"
    old=copy.deepcopy(prior[function]);new=copy.deepcopy(current[function])
    old["Properties"].pop("Code",None);code=new["Properties"].pop("Code",None)
    expected_key=f"system/thn-runtime/releases/{source_sha}/{zip_digest}.zip"
    if (old!=new or not isinstance(code,dict) or set(code)!={"S3Bucket","S3Key","S3ObjectVersion"}
        or code["S3Bucket"]!=PROFILES[environment]["bucket"] or code["S3Key"]!=expected_key
        or not isinstance(code["S3ObjectVersion"],str) or not code["S3ObjectVersion"] or code["S3ObjectVersion"]=="null"):_reject()
    if not isinstance(changes,list) or not changes:_reject()
    seen=set()
    for entry in changes:
        if not isinstance(entry,dict) or entry.get("Type")!="Resource":_reject()
        resource=entry.get("ResourceChange",{});logical=resource.get("LogicalResourceId");kind=resource.get("ResourceType");action=resource.get("Action")
        if logical in seen or resource.get("Replacement") not in (None,"False"):_reject()
        seen.add(logical)
        if logical==function and kind=="AWS::Lambda::Function" and action=="Modify":
            details=resource.get("Details",[])
            if not details or any(detail.get("Target",{}).get("Attribute")!="Properties" or detail.get("Target",{}).get("Name")!="Code" for detail in details):_reject()
        elif environment=="test" and kind=="AWS::Lambda::Version" and re.fullmatch(r"ConfigRuntimeReadFunctionVersion[a-zA-Z0-9]+",str(logical)):
            if action=="Remove" and prior.get(logical,{}).get("DeletionPolicy")!="Retain":_reject()
            if action not in {"Add","Remove"}:_reject()
            if action=="Add" and (current.get(logical,{}).get("DeletionPolicy")!="Retain" or current[logical]["Properties"].get("FunctionName")!={"Ref":function}):_reject()
        elif environment=="test" and logical=="ConfigRuntimeReadFunctionAliaslive" and kind=="AWS::Lambda::Alias" and action=="Modify":
            a=copy.deepcopy(prior[logical]);b=copy.deepcopy(current[logical]);a["Properties"].pop("FunctionVersion",None);b["Properties"].pop("FunctionVersion",None)
            if a!=b or b["Properties"].get("Name")!="live":_reject()
        else:_reject()
    for logical in set(prior)|set(current):
        if prior.get(logical)!=current.get(logical) and logical not in seen:_reject()


def aws(*args):
    response=subprocess.run(["aws",*args,"--output","json","--no-cli-pager"],capture_output=True,text=True)
    if response.returncode:_reject()
    return json.loads(response.stdout) if response.stdout.strip() else {}


def require_versioned_bucket(profile):
    state=aws("s3api","get-bucket-versioning","--bucket",profile["bucket"],"--expected-bucket-owner","765932874577")
    if state.get("Status")!="Enabled":_reject()


def require_stable_stack(profile, stack, resources=None, expected_change_set_arn=None):
    status = stack.get("StackStatus")
    if status in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}: return
    if profile["stack"] != PROFILES["test"]["stack"] or status != "UPDATE_ROLLBACK_COMPLETE": _reject()
    if (stack.get("RoleARN") != "arn:aws:iam::765932874577:role/zoolanding-config-runtime-read-test-cfn-exec"
        or not re.fullmatch(r"arn:aws:cloudformation:us-east-1:765932874577:stack/zoolanding-config-runtime-read-test/[a-zA-Z0-9-]+", str(stack.get("StackId", "")))): _reject()
    if resources is None:
        resources = aws("cloudformation", "list-stack-resources", "--stack-name", profile["stack"])["StackResourceSummaries"]
    if not isinstance(resources, list) or len(resources) != 8: _reject()
    logical = [item.get("LogicalResourceId") for item in resources if isinstance(item, dict)]
    fixed = {"ConfigRuntimeReadFunction", "ConfigRuntimeReadFunctionAliaslive",
             "ConfigRuntimeReadFunctionRole", "ConfigRuntimeReadFunctionRuntimeBundleGetPermissionProd",
             "RuntimeApi", "RuntimeApiProdStage"}
    if (len(logical) != 8 or len(set(logical)) != 8 or not fixed.issubset(logical)
        or len([item for item in logical if re.fullmatch(r"ConfigRuntimeReadFunctionVersion[a-zA-Z0-9]+", str(item))]) != 1
        or len([item for item in logical if re.fullmatch(r"RuntimeApiDeployment[a-zA-Z0-9]+", str(item))]) != 1
        or any(item.get("ResourceStatus") not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
               or not isinstance(item.get("PhysicalResourceId"), str) or not item["PhysicalResourceId"]
               for item in resources)): _reject()
    changes = aws("cloudformation", "list-change-sets", "--stack-name", profile["stack"])
    if not isinstance(changes, dict) or changes.get("NextToken") or not isinstance(changes.get("Summaries"), list): _reject()
    if expected_change_set_arn is None:
        if changes["Summaries"] != []: _reject()
    else:
        if (not re.fullmatch(r"arn:aws:cloudformation:us-east-1:765932874577:changeSet/thn-runtime-[1-9][0-9]*-[1-9][0-9]*/[a-f0-9-]+", expected_change_set_arn)
            or len(changes["Summaries"]) != 1): _reject()
        owned = changes["Summaries"][0]
        if (not isinstance(owned, dict) or owned.get("ChangeSetId") != expected_change_set_arn
            or owned.get("StackId") != stack["StackId"] or owned.get("StackName") != profile["stack"]
            or owned.get("Status") != "CREATE_COMPLETE" or owned.get("ExecutionStatus") != "AVAILABLE"
            or not re.fullmatch(r"thn-runtime-[1-9][0-9]*-[1-9][0-9]*", str(owned.get("ChangeSetName", "")))): _reject()


def lambda_task_url(location):
    """Only regional Lambda-owned task buckets; signed coordinates stay in memory."""
    if not isinstance(location, str) or any(ord(char) < 32 for char in location): _reject()
    try:
        url = urlsplit(location)
        port = url.port
    except ValueError:
        _reject()
    if (url.scheme != "https" or port not in (None, 443) or url.username is not None or url.password is not None
        or url.fragment or not re.fullmatch(
            r"(?:awslambda-us-east-1|prod-[0-9]{2}-[0-9]{4})-tasks\.s3\.us-east-1\.amazonaws\.com", str(url.hostname))): _reject()
    return url


def live_test_zip(expected):
    stack=aws("cloudformation","describe-stacks","--stack-name",PROFILES["test"]["stack"])["Stacks"]
    if len(stack)!=1:_reject()
    require_stable_stack(PROFILES["test"], stack[0])
    mapping=aws("cloudformation","describe-stack-resource","--stack-name",PROFILES["test"]["stack"],"--logical-resource-id","ConfigRuntimeReadFunction")["StackResourceDetail"]
    function=mapping["PhysicalResourceId"]
    alias=aws("lambda","get-alias","--function-name",function,"--name","live")
    if not re.fullmatch(r"[1-9][0-9]*",alias.get("FunctionVersion","")):_reject()
    result=aws("lambda","get-function","--function-name",function,"--qualifier",alias["FunctionVersion"])
    config=result["Configuration"];location=result["Code"]["Location"];lambda_task_url(location)
    if (config.get("State")!="Active" or config.get("LastUpdateStatus")!="Successful"
        or config.get("CodeSha256")!=base64.b64encode(hashlib.sha256(expected).digest()).decode()):_reject()
    # The signed URL stays in memory and is never an argument, log or artifact.
    with urlopen(location,timeout=20) as response:
        content=response.read(10*1024*1024+1)
    if content!=expected:_reject()
    return {"stackId":stack[0]["StackId"],"function":function,"version":alias["FunctionVersion"],
        "aliasRevision":alias.get("RevisionId"),"codeSha256":config["CodeSha256"],"revision":config.get("RevisionId")}


def runtime_management(function,processed):
    if not re.fullmatch(r"arn:aws:lambda:us-east-1:765932874577:function:[a-zA-Z0-9_-]+",str(function.get("FunctionArn",""))):_reject()
    response=aws("lambda","get-runtime-management-config","--function-name",function["FunctionName"])
    if (not isinstance(response,dict) or set(response)-{"FunctionArn","UpdateRuntimeOn","RuntimeVersionArn","ResponseMetadata"}
        or response.get("FunctionArn")!=function.get("FunctionArn")):_reject()
    mode=response.get("UpdateRuntimeOn");arn=response.get("RuntimeVersionArn")
    if mode not in {"Auto","FunctionUpdate","Manual"}:_reject()
    patch=function.get("RuntimeVersionConfig")
    if (not isinstance(patch,dict) or set(patch)!={"RuntimeVersionArn"}
        or not isinstance(patch["RuntimeVersionArn"],str)
        or not re.fullmatch(r"arn:aws:lambda:us-east-1::runtime:[a-f0-9]{64}",patch["RuntimeVersionArn"])):_reject()
    if mode=="Manual":
        if arn!=patch["RuntimeVersionArn"]:_reject()
    elif arn is not None:_reject()
    result={"UpdateRuntimeOn":mode,**({"RuntimeVersionArn":arn} if mode=="Manual" else {})}
    expected=_template(processed)["Resources"]["ConfigRuntimeReadFunction"]["Properties"].get("RuntimeManagementConfig",{"UpdateRuntimeOn":"Auto"})
    if result!=expected:_reject()
    return result


def same_managed_patch_configuration(left,right,management):
    if management not in ({"UpdateRuntimeOn":"Auto"},{"UpdateRuntimeOn":"FunctionUpdate"}):return False
    normalized=[]
    for function in (left,right):
        patch=function.get("RuntimeVersionConfig")
        if (not isinstance(patch,dict) or set(patch)!={"RuntimeVersionArn"}
            or not isinstance(patch["RuntimeVersionArn"],str)
            or not re.fullmatch(r"arn:aws:lambda:us-east-1::runtime:[a-f0-9]{64}",patch["RuntimeVersionArn"])
            or function.get("Runtime")!="python3.13" or function.get("PackageType")!="Zip"
            or function.get("Architectures") not in (["x86_64"],["arm64"])):return False
        normalized.append({**function,"RuntimeVersionConfig":{"RuntimeVersionArn":"aws-managed-patch"}})
    return normalized[0]==normalized[1]


def baseline(profile, expected_change_set_arn=None):
    if os.getenv("AWS_REGION")!="us-east-1" or aws("sts","get-caller-identity").get("Account")!="765932874577":_reject()
    stacks=aws("cloudformation","describe-stacks","--stack-name",profile["stack"])["Stacks"]
    if len(stacks)!=1:_reject()
    stack=stacks[0]
    if profile["stack"]==PROFILES["production"]["stack"] and stack.get("RoleARN")!="arn:aws:iam::765932874577:role/zoolanding-config-runtime-read-production-cfn-exec":_reject()
    resources=aws("cloudformation","list-stack-resources","--stack-name",profile["stack"])["StackResourceSummaries"]
    require_stable_stack(profile, stack, resources, expected_change_set_arn)
    identities=sorted([{key:item.get(key) for key in ("LogicalResourceId","PhysicalResourceId","ResourceType")} for item in resources],key=lambda item:item["LogicalResourceId"])
    functions=[aws("lambda","get-function-configuration","--function-name",item["PhysicalResourceId"]) for item in identities if item["ResourceType"]=="AWS::Lambda::Function"]
    authority={}
    if profile["stack"]==PROFILES["production"]["stack"]:
        authority={"sourceAuthority":source_authority(os.environ),"permissionAuthority":permission_authority(os.environ.get("GITHUB_REPOSITORY"),aws)}
    result={**authority,"cloudFormationRoleArn":stack.get("RoleARN"),"stackStatus":stack["StackStatus"],"stackId":stack["StackId"],"parameters":sorted(stack.get("Parameters",[]),key=lambda item:item["ParameterKey"]),
        "outputs":sorted(stack.get("Outputs",[]),key=lambda item:item["OutputKey"]),"identities":identities,"functions":functions,
        "original":aws("cloudformation","get-template","--stack-name",profile["stack"],"--template-stage","Original")["TemplateBody"],
        "processed":aws("cloudformation","get-template","--stack-name",profile["stack"],"--template-stage","Processed")["TemplateBody"]}
    if profile["stack"]==PROFILES["production"]["stack"]:
        if len(functions)!=1:_reject()
        result["runtimeManagement"]=runtime_management(functions[0],result["processed"])
    return result


def release_snapshot(profile, package, candidate_text=None, expected_change_set_arn=None):
    snapshot = baseline(profile) if expected_change_set_arn is None else baseline(profile, expected_change_set_arn)
    if profile == PROFILES["test"]:
        if len(snapshot["functions"]) != 1: _reject()
        snapshot["runtimeManagement"] = runtime_management(snapshot["functions"][0], snapshot["processed"])
        snapshot["testReleaseBinding"] = test_release_binding(snapshot, package)
        if candidate_text is not None:
            snapshot["sourceReference"] = sam_source_reference(snapshot, candidate_text)
    else:
        snapshot["testBinding"] = live_test_zip(package)
    return snapshot


def _canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()


def preview_digest(snapshot,description,original,processed,source_sha,manifest_digest,zip_digest):
    operation_sha=os.getenv("GITHUB_SHA", "")
    if not re.fullmatch(r"[a-f0-9]{40}",operation_sha):_reject()
    operator_digest=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return hashlib.sha256(_canonical({"baseline":snapshot,"changeSetId":description["ChangeSetId"],"stackId":description["StackId"],
        "parameters":description["Parameters"],"changes":description["Changes"],"original":original,"processed":processed,
        "sourceSha":source_sha,"manifestSha256":manifest_digest,"zipSha256":zip_digest,
        "operationSha":operation_sha,"operatorSha256":operator_digest,
        "authorityHelperSha256":hashlib.sha256(Path(__file__).with_name("native_release_authority.py").read_bytes()).hexdigest(),
        "reviewWindow":review_window(description)})).hexdigest()


def verify_preserved_state(before,after,environment,code_sha):
    for key in ("stackId","parameters","outputs","sourceAuthority","permissionAuthority","cloudFormationRoleArn","runtimeManagement"):
        if before.get(key)!=after.get(key):_reject()
    def stable_identities(snapshot):
        return [item for item in snapshot["identities"] if environment!="test" or item["ResourceType"]!="AWS::Lambda::Version"]
    if stable_identities(before)!=stable_identities(after):_reject()
    if len(before["functions"])!=1 or len(after["functions"])!=1 or after["functions"][0].get("CodeSha256")!=code_sha:_reject()
    left=copy.deepcopy(before["functions"][0]);right=copy.deepcopy(after["functions"][0])
    for key in ("CodeSha256","CodeSize","LastModified","RevisionId","LastUpdateStatus","LastUpdateStatusReason","LastUpdateStatusReasonCode"):
        left.pop(key,None);right.pop(key,None)
    if left!=right and (environment!="production" or not same_managed_patch_configuration(left,right,before.get("runtimeManagement"))):_reject()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment",required=True,choices=tuple(PROFILES))
    parser.add_argument("--execution",required=True,choices=("review","execute"))
    parser.add_argument("--release-root",type=Path,required=True)
    parser.add_argument("--manifest-digest",required=True)
    parser.add_argument("--source-sha",required=True)
    parser.add_argument("--review-digest",default="")
    parser.add_argument("--review-change-set-arn",default="")
    args=parser.parse_args();profile=PROFILES[args.environment]
    if not re.fullmatch(r"[a-f0-9]{40}",args.source_sha) or not re.fullmatch(r"[a-f0-9]{64}",args.manifest_digest):_reject()
    if os.getenv("GITHUB_REF")!=("refs/heads/test" if args.environment=="test" else "refs/heads/main"):_reject()
    package=(args.release_root/"runtime-read.zip").read_bytes();zip_digest=hashlib.sha256(package).hexdigest()
    code_sha=base64.b64encode(bytes.fromhex(zip_digest)).decode()
    if (args.release_root/"lambda-code-sha256.txt").read_bytes()!=(code_sha+"\n").encode():_reject()
    text=(args.release_root/"template.yaml").read_text(encoding="utf-8")
    production_text=production_candidate_source(text) if args.environment=="production" else None
    snapshot=release_snapshot(profile, package, text,
        expected_change_set_arn=args.review_change_set_arn if args.execution=="execute" else None)
    identical = args.environment == "test" and snapshot["testReleaseBinding"]["identicalPackage"]
    if args.environment == "test":
        # Validate the complete promoted source before any package or preview write.
        current_code = _template(snapshot["processed"])["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"]
        projected, params = project_test_template(text, snapshot, current_code)
        code_pointer_candidate(snapshot["processed"], projected, params)
    with tempfile.TemporaryDirectory(prefix="thn-native-release-") as temp:
        tmp=Path(temp)
        if args.execution=="review":
            if args.review_digest or args.review_change_set_arn:_reject()
            require_versioned_bucket(profile)
            key=f"system/thn-runtime/releases/{args.source_sha}/{zip_digest}.zip"
            # Immutable content key: an existing version is reused only after byte readback.
            head=subprocess.run(["aws","s3api","head-object","--bucket",profile["bucket"],"--expected-bucket-owner","765932874577","--key",key,"--output","json","--no-cli-pager"],capture_output=True,text=True)
            if head.returncode:
                aws("s3api","put-object","--bucket",profile["bucket"],"--expected-bucket-owner","765932874577","--key",key,"--body",str(args.release_root/"runtime-read.zip"),"--if-none-match","*","--server-side-encryption","AES256")
            version=aws("s3api","head-object","--bucket",profile["bucket"],"--expected-bucket-owner","765932874577","--key",key).get("VersionId")
            if not isinstance(version,str) or not version or version=="null":_reject()
            aws("s3api","get-object","--bucket",profile["bucket"],"--expected-bucket-owner","765932874577","--key",key,"--version-id",version,str(tmp/"sealed.zip"))
            if (tmp/"sealed.zip").read_bytes()!=package:_reject()
            anchor="      CodeUri: runtime-read.zip\n"
            if text.count(anchor)!=1:_reject()
            if args.environment=="production":
                # Preserve the existing production API/function topology. TEST's
                # immutable alias remains TEST-only; the ZIP bytes are unchanged.
                text=production_text
            uri="      CodeUri:\n"+"".join(f"        {k}: {json.dumps(v)}\n" for k,v in (("Bucket",profile["bucket"]),("Key",key),("Version",version)))
            candidate=tmp/"candidate.yaml"
            if args.environment == "test":
                code = {"S3Bucket": profile["bucket"], "S3Key": key, "S3ObjectVersion": version}
                projected, params = project_test_template(text, snapshot, code)
                neutral_candidate = code_pointer_candidate(snapshot["processed"], projected, params)
                if identical:
                    candidate.write_bytes(_canonical(neutral_candidate))
                else:
                    candidate.write_text(text.replace(anchor,uri),encoding="utf-8",newline="\n")
            else:
                candidate.write_text(text.replace(anchor,uri),encoding="utf-8",newline="\n")
            run=os.getenv("GITHUB_RUN_ID","");attempt=os.getenv("GITHUB_RUN_ATTEMPT","")
            if not re.fullmatch(r"[1-9][0-9]*",run) or not re.fullmatch(r"[1-9][0-9]*",attempt):_reject()
            parameters=tmp/"parameters.json";parameters.write_bytes(_canonical([{"ParameterKey":item["ParameterKey"],"UsePreviousValue":True} for item in snapshot["parameters"]]))
            immediate=release_snapshot(profile, package, text)
            if immediate!=snapshot:_reject()
            change=aws("cloudformation","create-change-set","--stack-name",profile["stack"],"--change-set-name",f"thn-runtime-{run}-{attempt}",
                "--change-set-type","UPDATE","--template-body","file://"+str(candidate),"--parameters","file://"+str(parameters),
                "--capabilities","CAPABILITY_IAM","--role-arn",os.environ["AWS_CLOUDFORMATION_ROLE_ARN"])["Id"]
            wait=subprocess.run(["aws","cloudformation","wait","change-set-create-complete","--stack-name",profile["stack"],"--change-set-name",change],capture_output=True)
            if wait.returncode:_reject()
        else:
            change=args.review_change_set_arn
            if not re.fullmatch(r"arn:aws:cloudformation:us-east-1:765932874577:changeSet/thn-runtime-[1-9][0-9]*-[1-9][0-9]*/[a-f0-9-]+",change) or not re.fullmatch(r"[a-f0-9]{64}",args.review_digest):_reject()
        description=aws("cloudformation","describe-change-set","--stack-name",profile["stack"],"--change-set-name",change,"--include-property-values")
        if description.get("ChangeSetId")!=change or description.get("StackId")!=snapshot["stackId"] or description.get("Status")!="CREATE_COMPLETE" or description.get("ExecutionStatus")!="AVAILABLE":_reject()
        original=aws("cloudformation","get-template","--stack-name",profile["stack"],"--change-set-name",change,"--template-stage","Original")["TemplateBody"]
        processed=aws("cloudformation","get-template","--stack-name",profile["stack"],"--change-set-name",change,"--template-stage","Processed")["TemplateBody"]
        review_resources(snapshot["processed"],processed,description["Changes"],args.environment,args.source_sha,zip_digest,identical_package=identical)
        code=_template(processed)["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"]
        if args.environment == "test":
            projected, params = project_test_template(text, snapshot, code)
            expected = code_pointer_candidate(snapshot["processed"], projected, params)
            if identical:
                if expected != _template(processed) or _template(original) != expected: _reject()
            else:
                resolver = sam_libraries()[-1](params)
                if resolver.resolve_parameter_refs(copy.deepcopy(projected)) != resolver.resolve_parameter_refs(copy.deepcopy(_template(processed))): _reject()
        aws("s3api","get-object","--bucket",code["S3Bucket"],"--expected-bucket-owner","765932874577","--key",code["S3Key"],"--version-id",code["S3ObjectVersion"],str(tmp/"reviewed.zip"))
        if (tmp/"reviewed.zip").read_bytes()!=package:_reject()
        digest=preview_digest(snapshot,description,original,processed,args.source_sha,args.manifest_digest,zip_digest)
        fresh=release_snapshot(profile, package, text, expected_change_set_arn=change)
        if fresh!=snapshot:_reject()
        if args.execution=="execute":
            if digest!=args.review_digest:_reject()
            review_window(description)
            immediate=release_snapshot(profile, package, text, expected_change_set_arn=change)
            if immediate!=snapshot:_reject()
            aws("cloudformation","execute-change-set","--stack-name",profile["stack"],"--change-set-name",change)
            wait=subprocess.run(["aws","cloudformation","wait","stack-update-complete","--stack-name",profile["stack"]],capture_output=True)
            if wait.returncode:_reject()
            after=release_snapshot(profile, package)
            verify_preserved_state(snapshot,after,args.environment,code_sha)
            if args.environment == "test" and _canonical(_template(after["processed"])) != _canonical(_template(processed)): _reject()
            if identical: verify_neutral_state(snapshot, after, code)
            if args.environment=="production" and live_test_zip(package)!=snapshot["testBinding"]:_reject()
        else:
            with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as summary:
                summary.write(f"review_inventory_digest={digest}\nreview_change_set_arn={change}\n")
                for entry in description["Changes"]:
                    resource=entry["ResourceChange"];summary.write(f"- {resource['Action']} {resource['LogicalResourceId']} {resource['ResourceType']} replacement={resource.get('Replacement')}\n")
        print("native_runtime_release_verified")


if __name__=="__main__":
    try:main()
    except Exception:raise SystemExit("native_runtime_release_rejected") from None
