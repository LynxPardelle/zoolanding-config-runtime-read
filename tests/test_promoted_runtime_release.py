import base64
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PromotedRuntimeReleaseTests(unittest.TestCase):
    def test_promoted_zip_is_verified_without_rebuilding_or_extracting(self):
        path = ROOT / "tools/verify_promoted_runtime_release.py"
        self.assertTrue(path.is_file(), "production rebuild has no exact TEST ZIP consumer")
        spec = importlib.util.spec_from_file_location("promoted_release", path)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("lambda_function.py", b"reviewed source")
                package.writestr("zoolanding_lambda_common.py", b"reviewed common")
            root.joinpath("runtime-read.zip").write_bytes(archive.getvalue())
            code = base64.b64encode(hashlib.sha256(archive.getvalue()).digest()).decode()
            root.joinpath("lambda-code-sha256.txt").write_text(code + "\n", newline="\n")
            root.joinpath("template.yaml").write_text("      CodeUri: runtime-read.zip\n")
            rows = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n" for path in sorted(root.iterdir())]
            manifest = "".join(rows).encode()
            root.parent.joinpath(root.name + '-manifest.sha256').write_bytes(manifest)
            self.addCleanup(root.parent.joinpath(root.name + '-manifest.sha256').unlink, missing_ok=True)
            before = root.joinpath("runtime-read.zip").read_bytes()
            self.assertEqual(verifier.verify_release(root, root.parent / (root.name + '-manifest.sha256'), hashlib.sha256(manifest).hexdigest(),
                {"lambda_function.py":b"reviewed source","zoolanding_lambda_common.py":b"reviewed common"}), code)
            self.assertEqual(root.joinpath("runtime-read.zip").read_bytes(), before)
            root.joinpath("runtime-read.zip").write_bytes(before + b"tampered")
            with self.assertRaises(ValueError):
                verifier.verify_release(root, root.parent / (root.name + '-manifest.sha256'), hashlib.sha256(manifest).hexdigest(),
                    {"lambda_function.py":b"reviewed source","zoolanding_lambda_common.py":b"reviewed common"})
