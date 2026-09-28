import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RuntimeReleaseProvenanceTests(unittest.TestCase):
    def test_only_successful_deployed_exact_test_artifact_is_selected(self):
        path=ROOT/"tools/resolve_promoted_runtime_release.py"
        self.assertTrue(path.is_file(), "production has no deployed TEST artifact resolver")
        spec=importlib.util.spec_from_file_location("resolver",path); resolver=importlib.util.module_from_spec(spec);spec.loader.exec_module(resolver)
        sha="a"*40; repo="example/runtime"
        run={"id":42,"run_attempt":1,"head_sha":sha,"head_branch":"test","event":"workflow_dispatch","status":"completed","conclusion":"success",
             "path":".github/workflows/deploy-test.yml","name":"Deploy Test","workflow_id":7,"repository":{"full_name":repo}}
        workflow={"id":7,"name":"Deploy Test","path":".github/workflows/deploy-test.yml","state":"active"}
        jobs={"total_count":1,"jobs":[{"name":"deploy","run_id":42,"head_sha":sha,"status":"completed","conclusion":"success",
            "steps":[{"name":"Deploy test","status":"completed","conclusion":"success"},{"name":"Verify immutable live alias","status":"completed","conclusion":"success"}]}]}
        artifact={"id":9,"name":"runtime-read-test-build-42-1-"+sha,"expired":False,"size_in_bytes":100,"workflow_run":{"id":42,"head_sha":sha,"head_branch":"test"}}
        resolver.validate_test_release(run,workflow,jobs,artifact,repo,42,9,sha)
        for location,field,value in (("run","head_sha","b"*40),("run","event","pull_request"),("artifact","expired",True),("artifact","id",10),
                                     ("job","conclusion","skipped"),("step","conclusion","skipped")):
            r,w,j,a=map(copy.deepcopy,(run,workflow,jobs,artifact))
            obj={"run":r,"artifact":a,"job":j["jobs"][0],"step":j["jobs"][0]["steps"][1]}[location];obj[field]=value
            with self.subTest(location=location,field=field),self.assertRaises(ValueError):
                resolver.validate_test_release(r,w,j,a,repo,42,9,sha)
