"""Guarded source-only overlay. Run from repository root; no DB/env changes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path.cwd())
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--check',action='store_true')
    mode.add_argument('--rollback',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    stage=root/'refactor/chat_backend'
    manifest=json.loads((stage/'patch-manifest.json').read_text())
    actions=[];conflicts=[]
    for item in manifest['files']:
        rel=Path(item['path']);target=root/rel
        if not target.resolve().is_relative_to(root):raise SystemExit('Unsafe target path')
        installed=digest(target.read_bytes()) if target.exists() else None
        if installed not in {item['before'],item['after']}:
            conflicts.append(str(rel));continue
        patch=stage/'patches'/rel
        if digest(patch.read_bytes())!=item['after']:raise SystemExit(f'Patch checksum mismatch: {rel}')
        if item['before'] is not None:
            original=stage/'originals'/rel
            if digest(original.read_bytes())!=item['before']:raise SystemExit(f'Original checksum mismatch: {rel}')
        if args.rollback and item.get('keep_on_rollback'):continue
        desired=item['before'] if args.rollback else item['after']
        if installed!=desired:actions.append((item,target))
    if conflicts:
        print('Preflight refused unexpected source changes; no files changed:')
        print('\n'.join(conflicts));return 2
    if args.check:
        print(f'Preflight PASSED: {len(actions)} files would change. No files changed.');return 0
    # Snapshot every changed target before any mutation; rollback can restore CRLF exactly.
    backups=stage/'backups'
    for item,target in actions:
        backup=backups/item['path']
        if not args.rollback and target.exists() and item['before'] is not None and not backup.exists():
            backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(target,backup)
    for item,target in actions:
        if args.rollback:
            if item['before'] is None:
                target.unlink(missing_ok=True);continue
            backup=backups/item['path']
            source=backup if backup.exists() else stage/'originals'/item['path']
            if digest(source.read_bytes())!=item['before']:raise SystemExit(f'Backup checksum mismatch: {item["path"]}')
        else:source=stage/'patches'/item['path']
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_name(target.name+'.chat-install-tmp')
        shutil.copyfile(source,temp);temp.replace(target)
    print(f'{"Rollback" if args.rollback else "Application"} PASSED: {len(actions)} files changed.')
    if args.rollback:print('Database schema retained. Chat migration and lifecycle cleanup files retained for schema tracking and deletion handling.')
    return 0

if __name__=='__main__':sys.exit(run())
