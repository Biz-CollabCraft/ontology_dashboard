#!/usr/bin/env python3
"""Offline draft validation and reviewed-only export. Never calls a model or approves labels."""
import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

MEANINGS = {'record_review','new_measurement','ambiguous_request','ambiguous_other','clear_other'}
STATUSES = {'required','not_required','optional','not_stated','unclear'}
LABELS = {'meaning','measurement_status','information_missing','unresolved_conflict','uncertain','measurement_required'}
PROFILES = {
    'warning_no_inspection': {'MONITOR','REQUEST_ADDITIONAL_DIAGNOSIS','REQUEST_INSPECTION'},
    'maintenance_review': {'REQUEST_MAINTENANCE','REVIEW_PLANNED_MAINTENANCE'},
}


def content_hash(case):
    content = {k:v for k,v in case.items() if k not in {'review','content_sha256'}}
    return sha256(json.dumps(content,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def validate(data, *, require_review=False):
    errors=[];ids=set();texts={};families={}
    if data.get('schema_version') != 'decision-gold-draft-v1': errors.append('unsupported schema')
    cases=data.get('cases',[])
    if not cases: errors.append('empty dataset')
    for c in cases:
        id=c.get('id','<missing>');prefix=f'{id}: '
        if id in ids:errors.append(prefix+'duplicate id')
        ids.add(id)
        split=c.get('split');family=c.get('family_id')
        if split not in {'development','evaluation'}:errors.append(prefix+'invalid split')
        if not family:errors.append(prefix+'missing family')
        if family in families and families[family]!=split:errors.append(prefix+'family crosses splits')
        families[family]=split
        source=c.get('source',{});text=source.get('text','')
        if not text.strip():errors.append(prefix+'empty source')
        if source.get('kind')!='authored_synthetic' or source.get('real_world_validated') is not False:
            errors.append(prefix+'this draft must not claim real-world provenance')
        if not source.get('source_ref'):errors.append(prefix+'missing source_ref')
        normalized=re.sub(r'\W+','',text).casefold()
        if normalized in texts:errors.append(prefix+'duplicate normalized text')
        texts[normalized]=id
        if c.get('content_sha256')!=content_hash(c):errors.append(prefix+'content hash mismatch')
        context=c.get('context',{});profile=context.get('profile')
        if set(context.get('policy_allowed_actions',[]))!=PROFILES.get(profile):errors.append(prefix+'policy profile/action mismatch')
        if context.get('risk_status')!='warning' or context.get('maintenance_recommended')!=(profile=='maintenance_review') or context.get('inspection_result_available')!=(profile=='maintenance_review'):
            errors.append(prefix+'policy facts/profile mismatch')
        a=c.get('annotation',{});labels=a.get('labels');review=c.get('review',{})
        if a.get('status') not in {'proposed','unresolved'}:errors.append(prefix+'invalid annotation status')
        if not a.get('rationale') or not a.get('supporting_quote') or a['supporting_quote'] not in text:errors.append(prefix+'missing or ungrounded annotation explanation')
        if a.get('status')=='unresolved':
            if labels is not None or a.get('action_constraint') is not None or not a.get('reviewer_questions'):errors.append(prefix+'unresolved annotation must retain questions without scored gold')
        elif not isinstance(labels,dict) or set(labels)!=LABELS:
            errors.append(prefix+'incomplete labels')
        else:
            if labels['meaning'] not in MEANINGS or labels['measurement_status'] not in STATUSES:errors.append(prefix+'unknown label value')
            if any(type(labels[f]) is not bool for f in LABELS-{'meaning','measurement_status'}):errors.append(prefix+'non-boolean flag')
            if labels['measurement_required'] and (labels['meaning']!='new_measurement' or labels['measurement_status']!='required'):errors.append(prefix+'measurement requirement inconsistent with semantic labels')
            if labels['meaning'] in {'ambiguous_request','ambiguous_other'} and not labels['uncertain']:errors.append(prefix+'ambiguous meaning must remain uncertain')
            expected={'text_hold_required':labels['uncertain'] or labels['unresolved_conflict'],
                'diagnosis_required_if_policy_allows':labels['measurement_required'],'exact_action_ranking_scored':False}
            if a.get('action_constraint')!=expected:errors.append(prefix+'action constraint mismatch')
        if review.get('status') not in {'pending','approved','changes_requested'}:errors.append(prefix+'invalid review status')
        if review.get('status')=='approved':
            if not review.get('reviewer') or review.get('reviewer')=='assistant':errors.append(prefix+'human reviewer identification required')
            try:
                stamp=datetime.fromisoformat(review.get('reviewed_at') or '')
                if stamp.tzinfo is None:raise ValueError()
            except (ValueError,TypeError):errors.append(prefix+'valid timezone-aware review timestamp required')
            if review.get('approved_content_sha256')!=content_hash(c):errors.append(prefix+'review does not bind current content')
        if require_review and (a.get('status')=='unresolved' or review.get('status')!='approved'):
            errors.append(prefix+'not ready: unresolved or pending human review')
    return errors


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('dataset',type=Path)
    parser.add_argument('--release-check',action='store_true')
    parser.add_argument('--export-dir',type=Path)
    args=parser.parse_args()
    data=json.loads(args.dataset.read_text())
    errors=validate(data,require_review=args.release_check or bool(args.export_dir))
    summary={'cases':len(data.get('cases',[])),'splits':dict(Counter(c['split'] for c in data.get('cases',[]))),
             'annotations':dict(Counter(c['annotation']['status'] for c in data.get('cases',[]))),
             'reviews':dict(Counter(c['review']['status'] for c in data.get('cases',[]))), 'errors':errors}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if errors:sys.exit(1)
    if args.export_dir:
        if args.export_dir.exists():raise SystemExit('Export directory exists; refusing to overwrite a release')
        args.export_dir.mkdir(parents=True)
        for split in ('development','evaluation'):
            rows=[{'id':c['id'],'family_id':c['family_id'],'category':c['scenario_family'],
                'text':c['source']['text'],'gold':c['annotation']['labels'],'context':c['context'],
                'action_constraint':c['annotation']['action_constraint']} for c in data['cases'] if c['split']==split]
            exported={'dataset_id':data['dataset_id'],'source_sha256':sha256(args.dataset.read_bytes()).hexdigest(),
                'split':split,'reviewed':True,'cases':rows}
            (args.export_dir/f'{split}.json').write_text(json.dumps(exported,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
