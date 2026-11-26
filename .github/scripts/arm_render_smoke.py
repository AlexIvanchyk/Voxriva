"""One fictional Northstar render in the exact native ARM image, with release limits."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/demo"))
from fixtures import email_draft  # noqa: E402

CAPTURE = '''import asyncio,hashlib,json,pathlib,platform,signal,sys,time
from backend.app.features.templates import rendering
async def main():
    assert platform.machine() == 'aarch64'
    assert hashlib.sha256(pathlib.Path(rendering.__file__).read_bytes()).hexdigest() == sys.argv[1]
    data=json.load(sys.stdin)
    data['draft']=rendering.DraftContent.model_validate(data['draft']).model_dump()
    start=time.monotonic()
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','backend.app.features.templates.rendering',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        output,errors=await asyncio.wait_for(process.communicate(json.dumps(data,ensure_ascii=False).encode()),timeout=3)
    except TimeoutError:
        process.kill();await process.wait()
        print(json.dumps({'worker_returncode':process.returncode,'parent_timeout':True}));sys.exit(1)
    report={'worker_returncode':process.returncode,'signal':signal.Signals(-process.returncode).name if process.returncode<0 else None,'elapsed_seconds':round(time.monotonic()-start,4),'machine':platform.machine(),'stderr':errors.decode(errors='replace')[:2000]}
    if process.returncode:
        print(json.dumps(report));sys.exit(1)
    result=rendering.RenderResult.model_validate_json(output)
    report['render_errors']=[issue.model_dump() for issue in result.errors]
    assert not result.errors and result.rendered is not None,report
    assert 'Sofia' in result.rendered['subject'] and len(result.rendered['images'])==2
    assert '{{' not in result.rendered['html'] and 'voxriva-image:' not in result.rendered['html']
    report['inline_images']=2;report['original_limits_unchanged']=True
    print(json.dumps(report))
asyncio.run(main())
'''

draft = email_draft("en")
payload = {"channel": "email", "draft": draft, "context": draft["preview_context"],
           "authoring": True, "generate_example": False}
expected = hashlib.sha256((ROOT / "backend/app/features/templates/rendering.py").read_bytes()).hexdigest()
assert expected == "8f06809d6338cd16971dd98295683f1b77fe96161c4f99491fc3af1b7985a615"
result = subprocess.run(
    ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--tmpfs", "/tmp",
     "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--entrypoint", "python",
     sys.argv[1], "-c", CAPTURE, expected],
    input=json.dumps(payload).encode(), capture_output=True, timeout=12,
)
if result.returncode:
    raise SystemExit(f"Native ARM render failed: {result.stdout.decode()} {result.stderr.decode()[:2000]}")
Path(sys.argv[2]).write_bytes(result.stdout)
print(result.stdout.decode())
