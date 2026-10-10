"""FinanceBench smoke evaluation. Host runtime: Python 3.12 standard library only."""
import argparse
import csv
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
RUBRIC_VERSION = 'step15-v1'


def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(value).hexdigest()


def load_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def append_row(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False) + '\n')


def config():
    values = {}
    p = Path('.env.evals')
    if p.exists():
        for line in p.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k.startswith('EVAL_')})
    return values


def token():
    value = os.environ.get('EVAL_ACCESS_TOKEN') or getpass.getpass('Test-account Bearer access token: ')
    if not value.strip():
        raise ValueError('A test-account token is required')
    return value.strip()


class HttpFailure(Exception):
    def __init__(self, status, retry_after=None):
        self.status, self.retry_after = status, retry_after
        super().__init__('HTTP ' + str(status))


def request(url, *, data=None, bearer=None, headers=None, method=None, timeout=180):
    headers = dict(headers or {})
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    # Keep tokens out of redirects and error bodies.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise HttpFailure(exc.code, exc.headers.get('Retry-After')) from None


def prepare(financebench, count, seed, destination):
    if not 20 <= count <= 30:
        raise ValueError('Choose 20–30 cases')
    source = Path(financebench).resolve()
    rows = load_rows(source / 'data/financebench_open_source.jsonl')
    groups = {}
    for row in rows:
        evidence = row.get('evidence') or []
        names = {e.get('evidence_doc_name', e.get('doc_name', row['doc_name'])) for e in evidence}
        names.add(row['doc_name'])
        if len(names) != 1 or not evidence:
            continue  # This starter selects single-document cases to freeze a clean split.
        pdf = source / 'pdfs' / (row['doc_name'] + '.pdf')
        if not pdf.is_file():
            continue
        groups.setdefault(row['doc_name'], []).append(row)
    rng = random.Random(seed)
    names = sorted(groups, key=lambda n: (-len(groups[n]), n))
    dev, test, dev_names = [], [], set()
    for name in names:
        if len(dev) >= count - 5:
            break
        members = sorted(groups[name], key=lambda x: x['financebench_id'])
        rng.shuffle(members)
        take = min(len(members), count - 5 - len(dev))
        dev.extend(members[:take])
        dev_names.add(name)
    for name in names:
        if name in dev_names:
            continue
        members = sorted(groups[name], key=lambda x: x['financebench_id'])
        rng.shuffle(members)
        test.extend(members[:5 - len(test)])
        if len(test) == 5:
            break
    if len(dev) != count - 5 or len(test) != 5:
        raise ValueError('Not enough matching PDFs/cases for a document-disjoint split')
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / 'golden.jsonl').exists():
        raise ValueError('Golden dataset already exists; use a new --out to create another version')
    selected = []
    for split, members in [('dev', dev), ('test', test)]:
        for row in members:
            selected.append({'case_id': row['financebench_id'], 'query': row['question'],
                'reference_answer': row['answer'], 'answerable': True, 'split': split,
                'tags': [str(row.get('question_reasoning') or 'unspecified'),
                         str(row.get('question_type') or 'unspecified')],
                'evidence': [{'document_key': row['doc_name'],
                             'page_index': e['evidence_page_num'], 'text': e['evidence_text']}
                             for e in row['evidence']]})
    for row in selected:
        append_row(dest / 'golden.jsonl', row)
    docs = {r['doc_name'] for r in dev + test}
    mapping = {name: {'pdf': str(source / 'pdfs' / (name + '.pdf')),
                     'sha256': sha((source / 'pdfs' / (name + '.pdf')).read_bytes())}
               for name in sorted(docs)}
    write_json(dest / 'documents.json', mapping)
    with (dest / 'questions.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['case_id', 'split', 'query', 'reference_answer', 'tags'])
        writer.writeheader()
        for row in selected:
            writer.writerow({k: '; '.join(row[k]) if k == 'tags' else row[k] for k in writer.fieldnames})
    try:
        commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    write_json(dest / 'manifest.json', {'source_commit': commit, 'seed': seed,
              'source_sha256': sha((source / 'data/financebench_open_source.jsonl').read_bytes()),
              'dataset_sha256': sha((dest / 'golden.jsonl').read_bytes()), 'count': count,
              'note': 'All FinanceBench cases are treated as answerable; no abstention benchmark.'})
    print(f'Prepared {count} questions and {len(docs)} PDFs. Review {dest / "questions.csv"}.')


def upload(dataset_dir, cfg):
    data = Path(dataset_dir)
    docs = json.loads((data / 'documents.json').read_text())
    path = data / 'document-map.json'
    mapping = json.loads(path.read_text()) if path.exists() else {}
    access = token()
    base = cfg.get('EVAL_RAG_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    interval = float(cfg.get('EVAL_POLL_SECONDS', '5'))
    ttl = float(cfg.get('EVAL_INGEST_TIMEOUT_SECONDS', '1800'))
    for name, doc in docs.items():
        pdf = Path(doc['pdf'])
        content = pdf.read_bytes()
        if sha(content) != doc['sha256']:
            raise ValueError('PDF changed: ' + name)
        saved = mapping.get(name)
        if saved and saved['sha256'] != doc['sha256']:
            raise ValueError('Mapping hash mismatch: ' + name)
        if not saved:
            boundary = 'step15-' + uuid.uuid4().hex
            head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                    f'filename="{pdf.name}"\r\nContent-Type: application/pdf\r\n\r\n').encode()
            body = head + content + f'\r\n--{boundary}--\r\n'.encode()
            result = request(base + '/api/v1/documents', data=body, bearer=access,
                             headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
            saved = {'id': result['id'], 'sha256': doc['sha256']}
            mapping[name] = saved
            # Save accepted upload before polling so reruns do not upload it again.
            write_json(path, mapping)
        start = time.monotonic()
        while True:
            result = request(base + '/api/v1/documents/' + saved['id'], bearer=access)
            if result['status'] == 'ingested':
                print(name + ': ingested')
                break
            if result['status'] == 'failed':
                raise ValueError('Ingestion failed: ' + name + '; inspect worker logs')
            if time.monotonic() - start > ttl:
                raise ValueError('Polling timed out; rerun upload to resume: ' + name)
            time.sleep(interval)


def do_capture(args, cfg):
    data = Path(args.data)
    cases = load_rows(data / 'golden.jsonl')
    if args.split != 'all':
        cases = [c for c in cases if c['split'] == args.split]
    if args.limit:
        cases = cases[:args.limit]
    manifest = json.loads((data / 'manifest.json').read_text())
    if sha((data / 'golden.jsonl').read_bytes()) != manifest['dataset_sha256']:
        raise ValueError('Dataset changed; create a new version instead')
    mapping = json.loads((data / 'document-map.json').read_text())
    docs = json.loads((data / 'documents.json').read_text())
    if set(docs) != set(mapping) or any(mapping[k]['sha256'] != docs[k]['sha256'] for k in docs):
        raise ValueError('Run upload for every selected document first')
    access = token()
    output = Path(args.out)
    recorded = load_rows(output) if output.exists() else []
    run_identity = {'dataset_sha256': manifest['dataset_sha256'],
                    'document_map_sha256': sha(mapping), 'mode': args.mode, 'top_k': args.top_k,
                    'revision_label': args.revision}
    if any(r.get('run_identity') != run_identity for r in recorded):
        raise ValueError('Output belongs to another configuration; choose a new --out')
    done = {r['case_id'] for r in recorded}
    expected_settings = recorded[0]['settings'] if recorded else None
    expected = json.loads((ROOT / 'compatibility.json').read_text())
    remote = '/tmp/step15-' + uuid.uuid4().hex + '.py'
    subprocess.run(['docker', 'cp', str(ROOT / 'container_capture.py'), args.container + ':' + remote], check=True)
    interval = float(cfg.get('EVAL_GENERATION_INTERVAL_SECONDS', '15'))
    try:
        for case in cases:
            if case['case_id'] in done:
                continue
            payload = dict(case=case, token=access, mode=args.mode, top_k=args.top_k,
                           document_map=mapping, expected_hashes=expected,
                           expected_settings=expected_settings)
            started = time.monotonic()
            result = subprocess.run(['docker', 'exec', '-i', args.container, 'python', remote],
                    input=json.dumps(payload), capture_output=True, text=True,
                    timeout=int(cfg.get('EVAL_CAPTURE_TIMEOUT_SECONDS', '420')))
            lines = [line.removeprefix('STEP15_RESULT=') for line in result.stdout.splitlines()
                     if line.startswith('STEP15_RESULT=')]
            if not lines:
                raise ValueError('Container capture failed; no result. Verify the API image and Python runtime.')
            record = json.loads(lines[-1])
            if 'fatal' in record:
                raise ValueError('Container preflight failed: ' + record['fatal'])
            record['elapsed_seconds'] = round(time.monotonic() - started, 3)
            record['run_identity'] = run_identity
            record['document_map'] = {k: {'id': v['id'], 'sha256': v['sha256']} for k, v in mapping.items()}
            expected_settings = record['settings']
            append_row(output, record)
            print(case['case_id'] + ': ' + (record.get('error') or
                  (record.get('answer') or {}).get('status', 'retrieved')))
            # Stop, retain failure, refresh token or resolve quota before resuming.
            if record.get('error') and any(word in record['error'] for word in ('authorization', 'rate_limited', 'http_401', 'http_403', 'http_429')):
                raise ValueError('Stopped on auth/quota error. Failure was saved; use a new output for an explicit retry.')
            # Host-side waits are local; no API worker or DB connection is retained.
            time.sleep(interval)
    finally:
        subprocess.run(['docker', 'exec', args.container, 'python', '-c',
                        'import pathlib; pathlib.Path(' + repr(remote) + ').unlink(missing_ok=True)'],
                       capture_output=True)


def exact_context(record):
    messages = record.get('messages') or []
    if not messages:
        return []
    marker = '\nEvidence (JSON records):\n'
    content = messages[-1]['content']
    if marker not in content:
        raise ValueError('Unknown context format')
    blocks = [json.loads(line) for line in content.split(marker, 1)[1].splitlines() if line.strip()]
    if len({b['label'] for b in blocks}) != len(blocks):
        raise ValueError('Duplicate context labels')
    return blocks


def ranked_metrics(ids, labels, k=5):
    """Reviewed labels keyed by chunk ID. Incomplete labels yield labeled recall."""
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate retrieval IDs')
    if any(i not in labels for i in ids[:k]):
        raise ValueError('Missing relevance grade for a returned chunk')
    if any(isinstance(v, bool) or not isinstance(v, int) or v not in (0, 1, 2) for v in labels.values()):
        raise ValueError('Labels must be integer 0/1/2')
    relevant = {key for key, grade in labels.items() if grade > 0}
    hit = len(set(ids[:k]) & relevant)
    ideal = sorted(labels.values(), reverse=True)[:k]
    dcg = lambda grades: sum((2 ** grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades))
    denominator = dcg(ideal)
    return {'precision_at_5': hit / k, 'labeled_recall_at_5': hit / len(relevant) if relevant else None,
            'ndcg_at_5': dcg([labels[i] for i in ids[:k]]) / denominator if denominator else None,
            'mrr_at_5': next((1 / (i + 1) for i, key in enumerate(ids[:k]) if key in relevant), 0.0)
                          if relevant else None}

