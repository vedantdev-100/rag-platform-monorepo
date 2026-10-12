"""Create a separate AMD/AMEX evaluation subset and retain saved upload IDs."""
import argparse
import hashlib
import json
from pathlib import Path

DOCUMENTS = {'AMD_2022_10K', 'AMERICANEXPRESS_2022_10K'}


def create(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Destination already exists; keep it or choose a new --out directory.')
    rows = [json.loads(line) for line in (source / 'golden.jsonl').read_text(encoding='utf-8').splitlines()
            if line.strip()]
    selected = []
    for row in rows:
        names = {e['document_key'] for e in row['evidence']}
        if names and names <= DOCUMENTS:
            row = dict(row)
            # Freeze a document-disjoint split for this smaller evaluation.
            row['split'] = 'dev' if names == {'AMD_2022_10K'} else 'test'
            selected.append(row)
    found = {e['document_key'] for row in selected for e in row['evidence']}
    if found != DOCUMENTS:
        raise ValueError('The source golden dataset does not contain questions for both PDFs.')
    if len({row['case_id'] for row in selected}) != len(selected):
        raise ValueError('Duplicate case IDs in the source dataset.')
    documents = json.loads((source / 'documents.json').read_text(encoding='utf-8'))
    filtered_documents = {key: documents[key] for key in sorted(DOCUMENTS)}
    mapping_path = source / 'document-map.json'
    mapping = json.loads(mapping_path.read_text(encoding='utf-8')) if mapping_path.exists() else {}
    filtered_mapping = {key: mapping[key] for key in sorted(DOCUMENTS) if key in mapping}
    for key, value in filtered_mapping.items():
        if value['sha256'] != filtered_documents[key]['sha256']:
            raise ValueError('Saved upload hash does not match document: ' + key)
    golden = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in selected)
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    manifest.update(parent_dataset_sha256=hashlib.sha256((source / 'golden.jsonl').read_bytes()).hexdigest(),
                    dataset_sha256=hashlib.sha256(golden.encode()).hexdigest(),
                    count=len(selected),
                    note='Two-PDF smoke subset: AMD development / American Express held-out; all cases answerable.')
    destination.mkdir(parents=True)
    (destination / 'golden.jsonl').write_bytes(golden.encode())
    for name, value in [('documents.json', filtered_documents), ('document-map.json', filtered_mapping),
                        ('manifest.json', manifest)]:
        (destination / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Created {len(selected)} questions across 2 PDFs at {destination}')
    print(f'Retained saved upload IDs for {len(filtered_mapping)} PDF(s).')
    print('Run upload with --data pointing here to verify/resume ingestion.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='evals/step15/data')
    parser.add_argument('--out', default='evals/step15/data-two-pdfs')
    args = parser.parse_args()
    try:
        create(args.source, args.out)
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(str(exc))
