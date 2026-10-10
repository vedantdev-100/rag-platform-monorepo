"""Step 15 DeepEval harness. Run from app repository root in its isolated uv environment."""
import os

# Set before importing DeepEval, including before its dotenv/settings initialization.
os.environ['DEEPEVAL_TELEMETRY_OPT_OUT'] = '1'
os.environ['DEEPEVAL_FILE_SYSTEM'] = 'READ_ONLY'
os.environ['DEEPEVAL_EVAL_MODE'] = 'llm'
os.environ['CONFIDENT_API_KEY'] = ''

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel, ConfigDict, Field

import capture_tools as tools
from lmstudio_judge import LMStudioJudge, ADAPTER_VERSION
from metrics_backend import score_case, METRIC_DEFINITION_VERSION, CUSTOM_STEPS


def validate_captures(data, captures):
    cases = {r['case_id']: r for r in tools.load_rows(Path(data) / 'golden.jsonl')}
    rows = tools.load_rows(captures)
    if not rows or len({r['case_id'] for r in rows}) != len(rows):
        raise ValueError('Empty or duplicate captures')
    expected = tools.sha((Path(data) / 'golden.jsonl').read_bytes())
    for row in rows:
        if row['case_id'] not in cases or row['run_identity']['dataset_sha256'] != expected:
            raise ValueError('Captured cases do not match this golden dataset')
        if row['run_identity'] != rows[0]['run_identity'] or row['settings'] != rows[0]['settings']:
            raise ValueError('Mixed capture configuration')
    return cases, rows


def report(results, judge, captures, out, profile):
    out = Path(out)
    groups = {}
    for split in ('all', 'dev', 'test'):
        rows = [r for r in results if split == 'all' or r['split'] == split]
        if not rows:
            continue
        groups[split] = {}
        for key in sorted({k for r in rows for k in r['metrics']}):
            values = [r['metrics'][key] for r in rows if r['metrics'].get(key) is not None]
            groups[split][key] = {'mean': sum(values) / len(values) if values else None,
                'scored_cases': len(values), 'total_cases': len(rows)}
    summary = {'backend': 'deepeval', 'deepeval_version': version('deepeval'),
        'metric_definition_version': METRIC_DEFINITION_VERSION, 'adapter_version': ADAPTER_VERSION,
        'profile': profile, 'judge_model': judge.model_id, 'judge_revision': judge.revision,
        'judge_configuration': judge.configuration_identity(),
        'judge_requests_this_run': judge.requests, 'judge_cache_hits_this_run': judge.cache_hits,
        'capture_sha256': tools.sha(Path(captures).read_bytes()), 'case_count': len(results),
        'cases_with_judge_errors': sum(bool(r['judge_errors']) for r in results), 'groups': groups,
        'geval_steps': CUSTOM_STEPS,
        'triad_metrics': ['deepeval_context_relevancy', 'deepeval_faithfulness', 'deepeval_answer_relevancy'],
        'limits': [
            'Built-in contextual precision is rank-sensitive LLM contextual precision, not classical Precision@5.',
            'Contextual recall attributes reference-answer statements to evidence; it is not corpus-wide chunk Recall@5.',
            'GEval metrics use our fixed task-specific steps through DeepEval; they are not built-in citation precision/coverage ratios.',
            'All FinanceBench cases in this subset are answerable; abstention precision/recall is not measured.',
            'Skipped/failed evaluations have N/A scores and explicit denominators; generation failures remain application failures.',
            'Local judge quality requires human calibration; scores are not directly comparable to the previous custom baseline.',
            'The graph capture does not exercise generation endpoint middleware, generation SSE or operations/load behavior.']}
    tools.write_json(out / 'summary.json', summary)
    tools.write_json(out / 'per-case.json', results)
    lines = ['# Step 15 DeepEval report', '',
        f'DeepEval {version("deepeval")}; profile: {profile}; judge: {judge.get_model_name()}', '',
        f'Cases: {len(results)}; cases with evaluator errors: {summary["cases_with_judge_errors"]}', '']
    for split, metrics in groups.items():
        lines.extend(['## ' + split, '', '| Metric | Mean | Scored / total |', '| --- | --- | --- |'])
        for key, value in metrics.items():
            mean = 'N/A' if value['mean'] is None else f'{value["mean"]:.3f}'
            lines.append(f'| {key} | {mean} | {value["scored_cases"]} / {value["total_cases"]} |')
        lines.append('')
    lines += ['## Limits', ''] + ['- ' + s for s in summary['limits']]
    (out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def judge_runs(args, cfg):
    cases, rows = validate_captures(args.data, args.captures)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError('Use a positive --limit')
        rows = rows[:args.limit]
    judge = LMStudioJudge(cfg)
    labels = json.loads(Path(args.labels).read_text()) if args.labels else {}
    out = Path(args.out)
    if (out / 'summary.json').exists():
        previous = json.loads((out / 'summary.json').read_text())
        if any(previous.get(key) != value for key, value in {
            'backend': 'deepeval', 'deepeval_version': version('deepeval'), 'profile': args.profile,
            'judge_model': judge.model_id, 'judge_revision': judge.revision,
            'judge_configuration': judge.configuration_identity(),
            'metric_definition_version': METRIC_DEFINITION_VERSION}.items()):
            raise ValueError('Report belongs to another evaluator configuration; use a new --out')
    results = []
    for row in rows:
        result = score_case(cases[row['case_id']], row, judge, args.profile, labels.get(row['case_id']))
        results.append(result)
        print(row['case_id'] + ': ' + str(len(result['judge_errors'])) + ' evaluator errors')
        report(results, judge, args.captures, out, args.profile)
    print('Report: ' + str(out / 'report.md'))


def doctor(cfg):
    judge = LMStudioJudge(cfg)
    models = tools.request(judge.base_url + '/models', bearer=judge.key)
    if judge.model_id not in {m['id'] for m in models['data']}:
        raise ValueError('EVAL_JUDGE_MODEL is absent from /v1/models')
    class Probe(BaseModel):
        model_config = ConfigDict(extra='forbid')
        grade: int = Field(ge=0, le=4)
        reason: str
    result = judge.generate('Return grade 4 and reason "connectivity test".', Probe)
    if result.grade != 4:
        raise ValueError('Structured-output probe failed')
    print('DeepEval ' + version('deepeval') + ' + LM Studio schema adapter: PASSED')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    s = commands.add_parser('prepare')
    s.add_argument('--financebench', required=True)
    s.add_argument('--count', type=int, default=25)
    s.add_argument('--seed', type=int, default=15)
    s.add_argument('--out', default='evals/step15/data')
    s = commands.add_parser('upload')
    s.add_argument('--data', default='evals/step15/data')
    s = commands.add_parser('capture')
    s.add_argument('--data', default='evals/step15/data')
    s.add_argument('--container', required=True)
    s.add_argument('--mode', choices=['retriever', 'pipeline', 'oracle'], default='pipeline')
    s.add_argument('--split', choices=['dev', 'test', 'all'], default='all')
    s.add_argument('--top-k', type=int, choices=[5], default=5)
    s.add_argument('--limit', type=int)
    s.add_argument('--revision', required=True)
    s.add_argument('--out', required=True)
    s = commands.add_parser('judge')
    s.add_argument('--data', default='evals/step15/data')
    s.add_argument('--captures', required=True)
    s.add_argument('--out', required=True)
    s.add_argument('--labels')
    s.add_argument('--profile', choices=['core', 'full'], default='full')
    s.add_argument('--limit', type=int, help='Score the first N captured cases for a smoke run')
    commands.add_parser('doctor')
    s = commands.add_parser('labels-template')
    s.add_argument('--captures', required=True)
    s.add_argument('--out', required=True)
    args = p.parse_args()
    cfg = tools.config()
    if args.command == 'prepare':
        tools.prepare(args.financebench, args.count, args.seed, args.out)
    elif args.command == 'upload':
        tools.upload(args.data, cfg)
    elif args.command == 'capture':
        tools.do_capture(args, cfg)
    elif args.command == 'judge':
        judge_runs(args, cfg)
    elif args.command == 'doctor':
        doctor(cfg)
    else:
        tools.write_json(args.out, {r['case_id']: {c['chunk_id']: None for c in r['retrieved']}
                                   for r in tools.load_rows(args.captures)})
        print('Review null grades as 0/1/2 and add known relevant missed chunks.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, tools.HttpFailure, OSError, subprocess.SubprocessError, KeyError) as exc:
        # No raw provider response / pydantic validation values in CLI failures.
        safe = str(exc) if isinstance(exc, tools.HttpFailure) or str(exc).startswith((
            'Container preflight failed:', 'Set exact EVAL_', 'Report belongs to another',
            'Captured cases do not match', 'Empty or duplicate captures', 'Mixed capture configuration',
            'EVAL_JUDGE_MODEL is absent')) else type(exc).__name__ + ' (check configuration or input files)'
        print('STOP: ' + safe, file=sys.stderr)
        sys.exit(1)
