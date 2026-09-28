import datetime
import importlib.util
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class NativeAuthorityTests(unittest.TestCase):
 def module(self):
  spec=importlib.util.spec_from_file_location('native_authority',ROOT/'tools/native_release_authority.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_native_creation_time_enforces_closed_24_hour_window(self):
  m=self.module();now=datetime.datetime(2026,9,27,12,tzinfo=datetime.timezone.utc)
  self.assertEqual(m.review_window({'CreationTime':'2026-09-27T11:00:00Z'},now)['expiresAt'],'2026-09-28T11:00:00+00:00')
  for value in (None,'2026-09-26T12:00:00Z','2026-09-28T12:00:00Z','invalid'):
   with self.subTest(value=value),self.assertRaises(ValueError):m.review_window({'CreationTime':value},now)
 def test_live_source_drift_refuses_authority_and_cannot_be_supplied_by_request(self):
  m=self.module();env={'GITHUB_REPOSITORY':'LynxPardelle/zoolanding-config-authoring','GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_SHA':'a'*40}
  def command(args):
   if '/git/commits/' in args[-1]:return json.dumps({'sha':'a'*40,'parents':[{'sha':'c'*40},{'sha':'b'*40}]})
   return json.dumps({'object':{'sha':'b'*40 if args[-1].endswith('/test') else 'a'*40}})
  self.assertEqual(m.source_authority(env,'b'*40,command)['mainSha'],'a'*40)
  with self.assertRaises(ValueError):m.source_authority(env,'c'*40,command)
  with self.assertRaises(ValueError):m.source_authority({**env,'GITHUB_REF':'refs/heads/test'},'b'*40,command)
  def late(args):return json.dumps({'object':{'sha':'c'*40}}) if args[0]=='gh' and args[-1].endswith('/main') else command(args)
  with self.assertRaises(ValueError):m.source_authority(env,'b'*40,late)
 def test_policy_fingerprint_detects_late_permission_change_with_no_raw_policy_output(self):
  m=self.module();role='zoolanding-config-authoring-production-deploy';arn='arn:aws:iam::765932874577:role/'+role;policy={'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':'lambda:GetFunction','Resource':'exact'}]}
  def aws(*args):
   if args[:2]==('sts','get-caller-identity'):return {'Account':'765932874577','Arn':'arn:aws:sts::765932874577:assumed-role/'+role+'/run'}
   if args[:2]==('iam','get-role'):return {'Role':{'Arn':arn,'RoleId':'stable','AssumeRolePolicyDocument':{'Statement':[{'Effect':'Allow'}]}}}
   if args[:2]==('iam','list-role-policies'):return {'PolicyNames':['exact'],'IsTruncated':False}
   if args[:2]==('iam','list-attached-role-policies'):return {'AttachedPolicies':[],'IsTruncated':False}
   if args[:2]==('iam','get-role-policy'):return {'PolicyDocument':policy}
   raise AssertionError(args)
  before=m.permission_authority('LynxPardelle/zoolanding-config-authoring',aws)
  self.assertNotIn('PolicyDocument',json.dumps(before));policy['Statement'][0]['Resource']='changed'
  self.assertNotEqual(before,m.permission_authority('LynxPardelle/zoolanding-config-authoring',aws))

 def test_sealed_runtime_operator_has_all_dependencies_in_isolated_workspace(self):
  import os,re,shutil,subprocess,sys,tempfile
  workflow=(ROOT/'.github/workflows/thn-runtime-production.yml').read_text()
  names=set(re.findall(r'^\s+\.aws-sam/promoted/([A-Za-z0-9_.-]+\.py)$',workflow,re.MULTILINE))
  self.assertEqual(names,{'native-runtime-release.py','native_release_authority.py'})
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for name in names:
    source='native_runtime_release.py' if name=='native-runtime-release.py' else name
    shutil.copy2(ROOT/'tools'/source,root/name)
   env={**os.environ};env.pop('PYTHONPATH',None)
   run=lambda:subprocess.run([sys.executable,str(root/'native-runtime-release.py'),'--help'],cwd=root,env=env,capture_output=True,text=True)
   valid=run();self.assertEqual(valid.returncode,0,valid.stderr)
   (root/'native_release_authority.py').unlink();self.assertNotEqual(run().returncode,0)
