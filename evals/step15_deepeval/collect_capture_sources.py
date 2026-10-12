"""Read-only collector for unreviewed capture dependencies in the running API."""
import argparse
import base64
import json
from pathlib import Path
import subprocess

REMOTE = '''
import base64,hashlib,io,json,pathlib,sys,zipfile
payload=json.load(sys.stdin)
expected=payload['sources'];dependencies=payload.get('dependencies',{})
changes={}; content={}; actual_hashes={}
def check(name,allowed):
    relative=pathlib.PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='app' or relative.suffix!='.py':
        raise ValueError('Invalid collector path')
    path=pathlib.Path.cwd()/name
    if not path.is_file():
        changes[name]={'missing':True};return
    raw=path.read_bytes()
    actual=hashlib.sha256(raw.decode().replace('\\r\\n','\\n').encode()).hexdigest()
    actual_hashes[name]=actual
    approved=allowed if isinstance(allowed,list) else [allowed]
    if actual not in approved:
        changes[name]={'sha256':actual};content[name]=raw
for name,allowed in expected.items():check(name,allowed)
for parent,variants in dependencies.items():
    for name,allowed in variants.get(actual_hashes.get(parent),{}).items():check(name,allowed)
if not changes:
    print('CAPTURE_SOURCES=compatible')
else:
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for name,raw in content.items():z.writestr(name,raw)
        z.writestr('comparison.json',json.dumps(changes,indent=2))
    print('CAPTURE_SOURCES='+base64.b64encode(buf.getvalue()).decode())
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container', required=True)
    p.add_argument('--out', default='step15_capture_source_review.zip')
    args = p.parse_args()
    if Path(args.out).exists():
        raise SystemExit('Output already exists; choose a new --out filename')
    expected = json.loads(Path(__file__).with_name('compatibility.json').read_text())
    dep = Path(__file__).with_name('compatibility-dependencies.json')
    dependencies = json.loads(dep.read_text()) if dep.exists() else {}
    result = subprocess.run(['docker', 'exec', '-i', args.container, 'python', '-c', REMOTE],
                input=json.dumps({'sources': expected, 'dependencies': dependencies}).encode('utf-8'),
                capture_output=True, timeout=60, check=True)
    line = next((x.removeprefix('CAPTURE_SOURCES=') for x in result.stdout.decode('utf-8').splitlines()
                 if x.startswith('CAPTURE_SOURCES=')), None)
    if line == 'compatible':
        print('All capture dependencies match reviewed versions; no ZIP needed.')
    elif line:
        Path(args.out).write_bytes(base64.b64decode(line, validate=True))
        print('Source-only review bundle saved: ' + args.out)
        print('Includes only mismatched allowlisted Python files; excludes .env, tokens, models and documents.')
    else:
        raise SystemExit('Collector returned no result; check the selected API container')


if __name__ == '__main__':
    main()
