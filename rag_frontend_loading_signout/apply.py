import argparse
from datetime import datetime,timezone
from pathlib import Path
import shutil
parser=argparse.ArgumentParser(description='Preview or apply the frontend update with backups.')
a=parser.add_mutually_exclusive_group(required=True);a.add_argument('--check',action='store_true');a.add_argument('--apply',action='store_true');parser.add_argument('--root',type=Path)
args=parser.parse_args();base=Path(__file__).resolve().parent;root=(args.root or base.parent).resolve();payload=base/'payload'
if not (root/'services').is_dir():parser.error('No services directory. Extract at repo root or pass --root PATH.')
changes=[]
for src in sorted(f for f in payload.rglob('*') if f.is_file()):
 rel=src.relative_to(payload);dst=root/rel
 if dst.is_symlink() or any(p.is_symlink() for p in dst.parents):parser.error(f'Symlink target refused: {rel}')
 if dst.exists() and not dst.is_file():parser.error(f'Not a file: {rel}')
 if not dst.exists() or src.read_bytes()!=dst.read_bytes():
  print(('REPLACE ' if dst.exists() else 'ADD ')+str(rel));changes.append((src,dst,rel))
print(f'{len(changes)} changes; .env.local and unrelated files are preserved.')
if args.check:raise SystemExit(0)
if not changes:print('Already applied.');raise SystemExit(0)
backup=root/'frontend-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');backup.mkdir(parents=True);manifest=[]
for src,dst,rel in changes:
 existed=dst.exists()
 if existed:
  saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,saved)
 manifest.append(('REPLACED ' if existed else 'ADDED ')+str(rel));dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
(backup/'manifest.txt').write_text('\n'.join(manifest)+'\n');print(f'Applied. Backup: {backup}')
