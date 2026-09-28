"""Resolve one actual successful Deploy Test artifact using read-only GitHub API."""
import argparse
import json
import os
import re
import subprocess


def _reject():
    raise ValueError("promoted_runtime_provenance_rejected")


def validate_test_release(run,workflow,jobs,artifact,repository,run_id,artifact_id,sha):
    if (not re.fullmatch(r"[a-f0-9]{40}",str(sha)) or type(run_id) is not int or type(artifact_id) is not int or min(run_id,artifact_id)<1
        or not all(isinstance(value,dict) for value in (run,workflow,jobs,artifact))
        or run.get("id")!=run_id or type(run.get("run_attempt")) is not int or run["run_attempt"]<1
        or run.get("head_sha")!=sha or run.get("head_branch")!="test" or run.get("event") not in {"push","workflow_dispatch"}
        or run.get("status")!="completed" or run.get("conclusion")!="success" or run.get("name")!="Deploy Test"
        or run.get("path")!=".github/workflows/deploy-test.yml" or run.get("repository",{}).get("full_name")!=repository
        or workflow.get("id")!=run.get("workflow_id") or workflow.get("name")!="Deploy Test" or workflow.get("state")!="active"
        or workflow.get("path")!=".github/workflows/deploy-test.yml"
        or artifact.get("id")!=artifact_id or artifact.get("expired") is not False or type(artifact.get("size_in_bytes")) is not int or artifact["size_in_bytes"]<1
        or artifact.get("name")!=f"runtime-read-test-build-{run_id}-{run['run_attempt']}-{sha}"
        or artifact.get("workflow_run",{}).get("id")!=run_id or artifact.get("workflow_run",{}).get("head_sha")!=sha
        or artifact.get("workflow_run",{}).get("head_branch")!="test"):
        _reject()
    entries=jobs.get("jobs")
    if not isinstance(entries,list) or jobs.get("total_count")!=len(entries):
        _reject()
    deployed=[job for job in entries if job.get("name")=="deploy" and job.get("run_id")==run_id and job.get("head_sha")==sha
        and job.get("status")=="completed" and job.get("conclusion")=="success" and isinstance(job.get("steps"),list)
        and all(any(step.get("name")==name and step.get("status")=="completed" and step.get("conclusion")=="success"
          for step in job["steps"]) for name in ("Deploy test","Verify immutable live alias"))]
    if len(deployed)!=1:
        _reject()


def _api(path):
    response=subprocess.run(["gh","api",path,"--method","GET"],capture_output=True,text=True)
    if response.returncode:_reject()
    return json.loads(response.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id",type=int,required=True)
    parser.add_argument("--artifact-id",type=int,required=True)
    parser.add_argument("--source-sha",required=True)
    args=parser.parse_args()
    repository=os.getenv("GITHUB_REPOSITORY","")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repository) or not re.fullmatch(r"[a-f0-9]{40}",args.source_sha):_reject()
    run=_api(f"repos/{repository}/actions/runs/{args.run_id}")
    workflow=_api(f"repos/{repository}/actions/workflows/deploy-test.yml")
    jobs=_api(f"repos/{repository}/actions/runs/{args.run_id}/attempts/{run.get('run_attempt')}/jobs?per_page=100")
    artifact=_api(f"repos/{repository}/actions/artifacts/{args.artifact_id}")
    current=_api(f"repos/{repository}/git/ref/heads/test")
    if current.get("object",{}).get("sha")!=args.source_sha:_reject()
    validate_test_release(run,workflow,jobs,artifact,repository,args.run_id,args.artifact_id,args.source_sha)
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as stream:
        stream.write(f"source_run_attempt={run['run_attempt']}\nsource_artifact_name={artifact['name']}\n")


if __name__=="__main__":
    try:main()
    except Exception:raise SystemExit("promoted_runtime_provenance_rejected") from None
