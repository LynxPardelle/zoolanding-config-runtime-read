"""Read-only pre-Action check for the protected Runtime Read TEST release."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


ACCOUNT = "765932874577"
REPOSITORY = "LynxPardelle/zoolanding-config-runtime-read"
BUCKET = "zoolanding-config-payloads-test"
PREFIX = f"arn:aws:s3:::{BUCKET}/system/thn-runtime/releases/"
ROLES = ("zoolanding-config-runtime-read-test-github-deploy",
         "zoolanding-config-runtime-read-test-cfn-exec")


def reject(reason):
    raise ValueError("runtime_test_preflight_" + reason)


def failure_message(error):
    message = str(error)
    if isinstance(error, ValueError) and re.fullmatch(r"runtime_test_preflight_[a-z0-9_]{1,80}", message):
        return message
    return "runtime_test_preflight_rejected"


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if result.returncode: reject("command_failed")
    return result.stdout


def aws(*args):
    return json.loads(command("aws", *args, "--region", "us-east-1", "--output", "json", "--no-cli-pager"))


def gh(*args):
    return json.loads(command("gh", *args))


def decision(aws_call, role, action, resource, context=None):
    request = {"PolicySourceArn": f"arn:aws:iam::{ACCOUNT}:role/{role}",
               "ActionNames": [action], "ResourceArns": [resource]}
    if context:
        request["ContextEntries"] = [{"ContextKeyName": key, "ContextKeyValues": [value],
                                      "ContextKeyType": "string"} for key, value in context.items()]
    response = aws_call("iam", "simulate-principal-policy", "--cli-input-json",
                        json.dumps(request, separators=(",", ":")))
    results = response.get("EvaluationResults") if isinstance(response, dict) else None
    if not isinstance(results, list) or len(results) != 1: reject("simulation_shape")
    return results[0].get("EvalDecision")


def verify_role_access(aws_call, source_sha, zip_sha256, version_id):
    if (not re.fullmatch(r"[a-f0-9]{40}", source_sha)
        or not re.fullmatch(r"[a-f0-9]{64}", zip_sha256)
        or not isinstance(version_id, str) or not version_id or version_id == "null"
        or any(ord(char) < 33 or ord(char) > 126 for char in version_id)): reject("coordinates")
    key = f"{source_sha}/{zip_sha256}.zip"
    target = PREFIX + key
    outside = f"arn:aws:s3:::{BUCKET}/system/thn-runtime/outside-releases/{source_sha}/{zip_sha256}.zip"
    tests = (
        (ROLES[0], "s3:GetObject", target, None, "allowed"),
        (ROLES[0], "s3:PutObject", target, {"s3:x-amz-server-side-encryption": "AES256"}, "allowed"),
        (ROLES[0], "s3:GetObjectVersion", target, {"s3:VersionId": version_id}, "allowed"),
        (ROLES[1], "s3:GetObjectVersion", target, {"s3:VersionId": version_id}, "allowed"),
        (ROLES[0], "s3:GetObject", outside, None, "implicitDeny"),
        (ROLES[0], "s3:PutObject", outside, {"s3:x-amz-server-side-encryption": "AES256"}, "implicitDeny"),
        (ROLES[1], "s3:GetObjectVersion", outside, {"s3:VersionId": version_id}, "implicitDeny"),
        (ROLES[0], "s3:PutObject", target, {"s3:x-amz-server-side-encryption": "aws:kms"}, "implicitDeny"),
        (ROLES[0], "s3:GetObjectVersion", target, None, "implicitDeny"),
        (ROLES[1], "s3:GetObjectVersion", target, {"s3:VersionId": "null"}, "implicitDeny"),
    )
    for role, action, resource, context, expected in tests:
        if decision(aws_call, role, action, resource, context) != expected:
            label = "github" if role == ROLES[0] else "cfn"
            reject("role_access_" + label + "_" + action.split(":", 1)[1].lower())


def verify_stack_identity(snapshot):
    if (not re.fullmatch(r"arn:aws:cloudformation:us-east-1:765932874577:stack/zoolanding-config-runtime-read-test/[a-zA-Z0-9-]+", str(snapshot.get("stackId", "")))
        or snapshot.get("cloudFormationRoleArn") != f"arn:aws:iam::{ACCOUNT}:role/{ROLES[1]}"
        or not isinstance(snapshot.get("identities"), list) or len(snapshot["identities"]) != 8):
        reject("stack_identity")


def remote_selection(source_sha):
    branch = gh("api", f"repos/{REPOSITORY}/branches/test")
    commit = branch.get("commit", {})
    if commit.get("sha") != source_sha: reject("test_tip")
    tree = gh("api", f"repos/{REPOSITORY}/git/commits/{source_sha}").get("tree", {}).get("sha")
    selector = json.loads(command("gh", "variable", "get", "RUNTIME_TEST_ACTIVATION_SELECTION_JSON", "-R", REPOSITORY))
    if (not isinstance(selector, dict) or set(selector) != {"schemaVersion", "mode", "sha", "tree", "workflowSha256"}
        or selector.get("schemaVersion") != 1 or selector.get("mode") != "thn-reviewed-activation"
        or selector.get("sha") != source_sha or selector.get("tree") != tree): reject("selection")
    blob = gh("api", f"repos/{REPOSITORY}/contents/.github/workflows/deploy-test.yml?ref={source_sha}")
    if blob.get("encoding") != "base64" or blob.get("type") != "file": reject("workflow_blob")
    raw = base64.b64decode("".join(blob["content"].split()), validate=True)
    if (len(raw) != blob.get("size")
        or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != blob.get("sha")
        or hashlib.sha256(raw).hexdigest() != selector.get("workflowSha256")): reject("workflow_hash")


def existing_object_version(key, package):
    head = subprocess.run(["aws", "s3api", "head-object", "--bucket", BUCKET,
                           "--expected-bucket-owner", ACCOUNT, "--key", key,
                           "--region", "us-east-1", "--output", "json", "--no-cli-pager"],
                          capture_output=True, text=True, timeout=90)
    if head.returncode:
        if "(404)" not in head.stderr and "Not Found" not in head.stderr: reject("object_head")
        return "preflight-unwritten-version"
    metadata = json.loads(head.stdout)
    version = metadata.get("VersionId")
    if (not isinstance(version, str) or not version or version == "null"
        or metadata.get("ContentLength") != len(package) or metadata.get("ServerSideEncryption") != "AES256"):
        reject("object_metadata")
    with tempfile.TemporaryDirectory(prefix="thn-runtime-preflight-") as directory:
        path = Path(directory) / "package.zip"
        aws("s3api", "get-object", "--bucket", BUCKET, "--expected-bucket-owner", ACCOUNT,
            "--key", key, "--version-id", version, str(path))
        if path.read_bytes() != package: reject("object_bytes")
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("AWS_REGION") != "us-east-1" or aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        reject("authority")
    package = (args.release_root / "runtime-read.zip").read_bytes()
    if hashlib.sha256(package).hexdigest() != args.zip_sha256: reject("package_hash")
    if (args.release_root / "lambda-code-sha256.txt").read_bytes() != (base64.b64encode(hashlib.sha256(package).digest()).decode() + "\n").encode():
        reject("lambda_hash")
    remote_selection(args.source_sha)
    import native_runtime_release as release
    release.require_versioned_bucket(release.PROFILES["test"])
    template = (args.release_root / "template.yaml").read_text(encoding="utf-8")
    os.environ["GITHUB_REPOSITORY"] = REPOSITORY
    snapshot = release.release_snapshot(release.PROFILES["test"], package, template)
    verify_stack_identity(snapshot)
    code = release._template(snapshot["processed"])["Resources"]["ConfigRuntimeReadFunction"]["Properties"]["Code"]
    projected, parameters = release.project_test_template(template, snapshot, code)
    release.code_pointer_candidate(snapshot["processed"], projected, parameters)
    key = f"system/thn-runtime/releases/{args.source_sha}/{args.zip_sha256}.zip"
    version = existing_object_version(key, package)
    verify_role_access(aws, args.source_sha, args.zip_sha256, version)
    print(json.dumps({"result": "runtime_test_preflight_passed", "sourceSha": args.source_sha,
                      "zipSha256": args.zip_sha256, "stackStatus": snapshot["stackStatus"],
                      "objectExists": version != "preflight-unwritten-version"}, separators=(",", ":")))


if __name__ == "__main__":
    try: main()
    except Exception as error:
        raise SystemExit(failure_message(error)) from None
