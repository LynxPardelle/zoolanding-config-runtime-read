"""Verify immutable TEST transport and ZIP bytes; never rebuild or extract code."""
import argparse
import base64
import hashlib
import io
from pathlib import Path
import re
import stat
import subprocess
import zipfile

FILES = {"template.yaml", "runtime-read.zip", "lambda-code-sha256.txt"}
RUNTIME = {"lambda_function.py", "zoolanding_lambda_common.py"}


def _reject():
    raise ValueError("promoted_runtime_release_rejected")


def _link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def verify_release(root, manifest_path, expected_digest, expected_sources):
    if (not root.is_dir() or _link(root) or not manifest_path.is_file() or _link(manifest_path)
        or not re.fullmatch(r"[a-f0-9]{64}", expected_digest or "")
        or set(expected_sources) != RUNTIME):
        _reject()
    manifest = manifest_path.read_bytes()
    if hashlib.sha256(manifest).hexdigest() != expected_digest:
        _reject()
    actual = set()
    for path in root.iterdir():
        if not path.is_file() or _link(path):
            _reject()
        actual.add(path.name)
    if actual != FILES:
        _reject()
    rows = manifest.decode("ascii").splitlines()
    inventory = {}
    for row in rows:
        match = re.fullmatch(r"([a-f0-9]{64})  \./([A-Za-z0-9_.-]+)", row)
        if not match or match[2] not in FILES or match[2] in inventory:
            _reject()
        inventory[match[2]] = match[1]
    if set(inventory) != FILES or any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest for name,digest in inventory.items()):
        _reject()
    package = (root / "runtime-read.zip").read_bytes()
    if not 0 < len(package) <= 10 * 1024 * 1024:
        _reject()
    code_sha = base64.b64encode(hashlib.sha256(package).digest()).decode("ascii")
    if (root / "lambda-code-sha256.txt").read_bytes() != (code_sha + "\n").encode("ascii"):
        _reject()
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        entries = archive.infolist()
        if len(entries) != len(RUNTIME) or {entry.filename for entry in entries} != RUNTIME:
            _reject()
        for entry in entries:
            if (entry.is_dir() or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16)
                or not 0 < entry.file_size <= 5 * 1024 * 1024
                or archive.read(entry) != expected_sources[entry.filename]):
                _reject()
    template = (root / "template.yaml").read_text(encoding="utf-8")
    if template.count("      CodeUri: runtime-read.zip\n") != 1:
        _reject()
    return code_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--source-sha", required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.source_sha):
        _reject()
    sources={}
    for name in RUNTIME:
        result=subprocess.run(["git","show",f"{args.source_sha}:{name}"],capture_output=True,check=False)
        if result.returncode: _reject()
        sources[name]=result.stdout
    verify_release(args.root,args.manifest,args.expected_digest,sources)
    print("promoted_runtime_release_verified")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("promoted_runtime_release_rejected") from None
