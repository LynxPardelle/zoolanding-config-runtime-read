"""Manual retained native preview; exact ZIP, no storage/IAM/API reconfiguration."""
import argparse
import base64
import copy
import hashlib
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


def review_resources(before,candidate,changes,environment,source_sha,zip_digest):
    if environment not in PROFILES or not re.fullmatch(r"[a-f0-9]{40}",source_sha) or not re.fullmatch(r"[a-f0-9]{64}",zip_digest):_reject()
    prior=_template(before)["Resources"]; current=_template(candidate)["Resources"]
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


def live_test_zip(expected):
    stack=aws("cloudformation","describe-stacks","--stack-name",PROFILES["test"]["stack"])["Stacks"]
    if len(stack)!=1 or stack[0].get("StackStatus") not in {"CREATE_COMPLETE","UPDATE_COMPLETE"}:_reject()
    mapping=aws("cloudformation","describe-stack-resource","--stack-name",PROFILES["test"]["stack"],"--logical-resource-id","ConfigRuntimeReadFunction")["StackResourceDetail"]
    function=mapping["PhysicalResourceId"]
    alias=aws("lambda","get-alias","--function-name",function,"--name","live")
    if not re.fullmatch(r"[1-9][0-9]*",alias.get("FunctionVersion","")):_reject()
    result=aws("lambda","get-function","--function-name",function,"--qualifier",alias["FunctionVersion"])
    config=result["Configuration"];location=result["Code"]["Location"];url=urlsplit(location)
    if (url.scheme!="https" or url.hostname!="awslambda-us-east-1-tasks.s3.us-east-1.amazonaws.com" or url.username or url.password
        or config.get("State")!="Active" or config.get("LastUpdateStatus")!="Successful"
        or config.get("CodeSha256")!=base64.b64encode(hashlib.sha256(expected).digest()).decode()):_reject()
    # The signed URL stays in memory and is never an argument, log or artifact.
    with urlopen(location,timeout=20) as response:
        content=response.read(10*1024*1024+1)
    if content!=expected:_reject()
    return {"stackId":stack[0]["StackId"],"function":function,"version":alias["FunctionVersion"],
        "aliasRevision":alias.get("RevisionId"),"codeSha256":config["CodeSha256"],"revision":config.get("RevisionId")}


def baseline(profile):
    if os.getenv("AWS_REGION")!="us-east-1" or aws("sts","get-caller-identity").get("Account")!="765932874577":_reject()
    stacks=aws("cloudformation","describe-stacks","--stack-name",profile["stack"])["Stacks"]
    if len(stacks)!=1 or stacks[0].get("StackStatus") not in {"CREATE_COMPLETE","UPDATE_COMPLETE"}:_reject()
    stack=stacks[0]
    if profile["stack"]==PROFILES["production"]["stack"] and stack.get("RoleARN")!="arn:aws:iam::765932874577:role/zoolanding-config-runtime-read-production-cfn-exec":_reject()
    resources=aws("cloudformation","list-stack-resources","--stack-name",profile["stack"])["StackResourceSummaries"]
    identities=sorted([{key:item.get(key) for key in ("LogicalResourceId","PhysicalResourceId","ResourceType")} for item in resources],key=lambda item:item["LogicalResourceId"])
    functions=[aws("lambda","get-function-configuration","--function-name",item["PhysicalResourceId"]) for item in identities if item["ResourceType"]=="AWS::Lambda::Function"]
    authority={}
    if profile["stack"]==PROFILES["production"]["stack"]:
        authority={"sourceAuthority":source_authority(os.environ),"permissionAuthority":permission_authority(os.environ.get("GITHUB_REPOSITORY"),aws)}
    return {**authority,"cloudFormationRoleArn":stack.get("RoleARN"),"stackId":stack["StackId"],"parameters":sorted(stack.get("Parameters",[]),key=lambda item:item["ParameterKey"]),
        "outputs":sorted(stack.get("Outputs",[]),key=lambda item:item["OutputKey"]),"identities":identities,"functions":functions,
        "original":aws("cloudformation","get-template","--stack-name",profile["stack"],"--template-stage","Original")["TemplateBody"],
        "processed":aws("cloudformation","get-template","--stack-name",profile["stack"],"--template-stage","Processed")["TemplateBody"]}


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
    for key in ("stackId","parameters","outputs","sourceAuthority","permissionAuthority","cloudFormationRoleArn"):
        if before.get(key)!=after.get(key):_reject()
    def stable_identities(snapshot):
        return [item for item in snapshot["identities"] if environment!="test" or item["ResourceType"]!="AWS::Lambda::Version"]
    if stable_identities(before)!=stable_identities(after):_reject()
    if len(before["functions"])!=1 or len(after["functions"])!=1 or after["functions"][0].get("CodeSha256")!=code_sha:_reject()
    left=copy.deepcopy(before["functions"][0]);right=copy.deepcopy(after["functions"][0])
    for key in ("CodeSha256","CodeSize","LastModified","RevisionId","LastUpdateStatus","LastUpdateStatusReason","LastUpdateStatusReasonCode"):
        left.pop(key,None);right.pop(key,None)
    if left!=right:_reject()


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
    snapshot=baseline(profile)
    if args.environment=="production":snapshot["testBinding"]=live_test_zip(package)
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
            text=(args.release_root/"template.yaml").read_text(encoding="utf-8")
            anchor="      CodeUri: runtime-read.zip\n"
            if text.count(anchor)!=1:_reject()
            if args.environment=="production":
                # Preserve the existing production API/function topology. TEST's
                # immutable alias remains TEST-only; the ZIP bytes are unchanged.
                for line in ("      AutoPublishAlias: live\n","      AutoPublishAliasAllProperties: true\n","      VersionDeletionPolicy: Retain\n"):
                    if text.count(line)!=1:_reject()
                    text=text.replace(line,"")
            uri="      CodeUri:\n"+"".join(f"        {k}: {json.dumps(v)}\n" for k,v in (("Bucket",profile["bucket"]),("Key",key),("Version",version)))
            candidate=tmp/"candidate.yaml";candidate.write_text(text.replace(anchor,uri),encoding="utf-8",newline="\n")
            run=os.getenv("GITHUB_RUN_ID","");attempt=os.getenv("GITHUB_RUN_ATTEMPT","")
            if not re.fullmatch(r"[1-9][0-9]*",run) or not re.fullmatch(r"[1-9][0-9]*",attempt):_reject()
            parameters=tmp/"parameters.json";parameters.write_bytes(_canonical([{"ParameterKey":item["ParameterKey"],"UsePreviousValue":True} for item in snapshot["parameters"]]))
            immediate=baseline(profile)
            if args.environment=="production":immediate["testBinding"]=live_test_zip(package)
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
        review_resources(snapshot["processed"],processed,description["Changes"],args.environment,args.source_sha,zip_digest)
        code=_template(processed)["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"]
        aws("s3api","get-object","--bucket",code["S3Bucket"],"--expected-bucket-owner","765932874577","--key",code["S3Key"],"--version-id",code["S3ObjectVersion"],str(tmp/"reviewed.zip"))
        if (tmp/"reviewed.zip").read_bytes()!=package:_reject()
        digest=preview_digest(snapshot,description,original,processed,args.source_sha,args.manifest_digest,zip_digest)
        fresh=baseline(profile)
        if args.environment=="production":fresh["testBinding"]=live_test_zip(package)
        if fresh!=snapshot:_reject()
        if args.execution=="execute":
            if digest!=args.review_digest:_reject()
            review_window(description)
            immediate=baseline(profile)
            if args.environment=="production":immediate["testBinding"]=live_test_zip(package)
            if immediate!=snapshot:_reject()
            aws("cloudformation","execute-change-set","--stack-name",profile["stack"],"--change-set-name",change)
            wait=subprocess.run(["aws","cloudformation","wait","stack-update-complete","--stack-name",profile["stack"]],capture_output=True)
            if wait.returncode:_reject()
            after=baseline(profile)
            verify_preserved_state(snapshot,after,args.environment,code_sha)
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
