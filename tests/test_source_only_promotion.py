import json
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourceOnlyPromotionTests(unittest.TestCase):
    def test_raw_selection_rejects_duplicates_before_last_value_can_authorize(self):
        spec=importlib.util.spec_from_file_location("source_only_duplicate",ROOT/"tools/verify_source_only_promotion.py")
        verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
        valid={"schemaVersion":1,"mode":"thn-source-only","sourceSha":"a"*40,"sourceTree":"b"*40,"targetBaseSha":"c"*40,"mergeTree":"d"*40}
        activation={"schemaVersion":1,"mode":"thn-reviewed-activation","sha":"a"*40,"tree":"b"*40,"workflowSha256":"c"*64}
        for value in (valid,activation):
            raw=json.dumps(value);self.assertEqual(verifier.parse_selection(raw),value)
            for key in value:
                duplicate='{'+json.dumps(key)+':"wrong",'+raw[1:]
                with self.subTest(key=key),self.assertRaises(ValueError):verifier.parse_selection(duplicate)
            escaped='{"\\u0073chemaVersion":2,'+raw[1:]
            with self.assertRaises(ValueError):verifier.parse_selection(escaped)
        for bad in ("NaN",'[]','{"outer":{"x":1,"x":2}}',' '*4097):
            with self.assertRaises(ValueError):verifier.parse_selection(bad)

    def test_exact_selector_and_reviewed_activation_are_closed(self):
        path = ROOT / "tools" / "verify_source_only_promotion.py"
        self.assertTrue(path.is_file(), "source-only promotion has no fail-closed verifier")
        spec = importlib.util.spec_from_file_location("source_only", path)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        selection = {"schemaVersion": 1, "mode": "thn-source-only", "sourceSha": "a" * 40,
                     "sourceTree": "b" * 40, "targetBaseSha": "c" * 40, "mergeTree": "d" * 40}
        context = {"target": "main", "eventName": "push", "ref": "refs/heads/main", "sha": "e" * 40,
                   "sourceSha": "a" * 40, "sourceTree": "b" * 40, "mergeTree": "d" * 40,
                   "nativeMergeTree": "d" * 40, "parents": ["c" * 40, "a" * 40],
                   "event": {"before": "c" * 40, "after": "e" * 40, "forced": False, "created": False, "deleted": False}}
        self.assertTrue(verifier.verify_source_only(selection, context))
        for field in selection:
            broken = copy.deepcopy(selection)
            broken[field] = "invalid"
            with self.subTest(field=field), self.assertRaises(ValueError):
                verifier.verify_source_only(broken, context)
        for field in ("sourceSha", "sourceTree", "mergeTree", "nativeMergeTree", "ref", "eventName", "parents", "event"):
            broken = copy.deepcopy(context)
            broken[field] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                verifier.verify_source_only(selection, broken)
        self.assertRaises(ValueError, verifier.verify_source_only, {**selection, "extra": True}, context)
        activation = {"schemaVersion": 1, "mode": "thn-reviewed-activation", "sha": "e" * 40,
                      "tree": "d" * 40, "workflowSha256": "f" * 64}
        verifier.verify_activation(activation, "e" * 40, "d" * 40, "f" * 64)
        for field in activation:
            broken = {**activation, field: "invalid"}
            with self.subTest(activation=field), self.assertRaises(ValueError):
                verifier.verify_activation(broken, "e" * 40, "d" * 40, "f" * 64)
        self.assertRaises(ValueError, verifier.verify_activation, {**activation, "extra": True}, "e" * 40, "d" * 40, "f" * 64)


    def test_manual_activation_requires_current_source_and_exact_native_merge(self):
        spec=importlib.util.spec_from_file_location("source_only",ROOT/"tools/verify_source_only_promotion.py")
        op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
        check=getattr(op,"verify_manual_merge",None)
        self.assertTrue(callable(check), "manual activation does not prove the native merged source")
        context={"parents":["a"*40,"b"*40],"sourceSha":"b"*40,"tree":"c"*40,"nativeMergeTree":"c"*40}
        check(context)
        for mutation in ({"parents":["a"*40]}, {"sourceSha":"d"*40},{"tree":"d"*40},{"nativeMergeTree":"d"*40}):
            with self.assertRaises(ValueError):check({**context,**mutation})
