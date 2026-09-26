"""Draft review-only sign labels from local excerpts of the official TPDM PDF.

No output from this script becomes verified or enters the public catalog.
Usage: python scripts/suggest_sign_labels.py tmp/pdfs/TPDM_V3_2026.txt --live
"""

import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / 'data' / 'sign-review-queue.json'


def excerpt(text, code):
    number = code[3:]
    matches = list(re.finditer(r'T\.S\.\s*' + re.escape(number) + r'\b', text))
    snippets = []
    for match in matches:
        raw = text[max(0, match.start()-270):match.end()+300]
        clean = re.sub(r'\s+', ' ', raw)
        score = clean.count('"') + clean.count('“') + clean.count('”')
        snippets.append((score, text[:match.start()].count('\f') + 1, clean))
    snippets.sort(key=lambda item: -item[0])
    return [{'pdf_page': page, 'text': snippet} for _, page, snippet in snippets[:2]]


def save(queue):
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    folder = ROOT / 'docs' / 'sign-review-batches'
    for batch in range(5):
        lines = [f'# Sign review batch {batch+1} of 5', '',
                 'These are proposals. Approve the code, English name, Traditional Chinese name, and aliases before verification.',
                 'A draft translation or a nearby PDF passage is not proof of a code-name match.', '']
        for item in queue[batch*20:(batch+1)*20]:
            code = item['code']
            page = (item.get('evidence') or [{}])[0].get('pdf_page')
            source = item['source']['url'] + (f'#page={page}' if page else '')
            lines += [f"## {item['rank']}. {code} — {item['survey_count']} map records", '',
                      f"![{code}](../../site/{item['preview']})", '',
                      f"- Proposed English: {item['name_en'] or 'Needs source research'}",
                      f"- 建議繁體中文：{item['name_zh_hant'] or '待核對來源'}",
                      f"- Proposed aliases: {', '.join(item['aliases_en'] + item['aliases_zh_hant']) or 'None'}",
                      f"- [Official manual]({source}) · [SVG](../../site/{item['downloads']['svg']}) · [DXF](../../site/{item['downloads']['dxf']})",
                      f"- Candidate source: " + (f"[Open source]({item['candidate_source']})" if item.get('candidate_source') else 'None'),
                      f"- Review note: {item.get('review_note', 'Check the exact name, translation, and code.')}",
                      f"- Review state: {item['review_status']}", '']
        (folder / f'batch-{batch+1:02}.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    if len(sys.argv) != 3 or sys.argv[2] != '--live':
        raise SystemExit('Pass PDF text path and --live to draft proposals')
    text = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace')
    queue = json.loads(QUEUE.read_text(encoding='utf-8'))
    for item in queue:
        item['evidence'] = excerpt(text, item['code'])
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
            if line.startswith('DEEPSEEK_API_KEY='):
                key = line.split('=', 1)[1].strip()
                break
    if not key:
        raise SystemExit('DeepSeek key absent; no candidate generation')
    client = OpenAI(api_key=key, base_url='https://api.deepseek.com', max_retries=0)
    for start in range(0, 100, 10):
        subset = queue[start:start+10]
        payload = [{'code': item['code'], 'evidence': item['evidence'],
                    'existing_en': item['name_en'], 'existing_zh': item['name_zh_hant']}
                   for item in subset]
        response = client.chat.completions.create(
            model='deepseek-flash', max_tokens=3000, temperature=0,
            extra_body={'thinking': {'type': 'disabled'}},
            response_format={'type': 'json_object'},
            messages=[{'role': 'system', 'content':
                'Draft editorial traffic-sign label proposals from supplied excerpts of the official Hong Kong TPDM. '
                'These will require human approval. Match each code only to its own evidence. '
                'Return JSON object with a labels array. Each entry: code, name_en, name_zh_hant, aliases_en, aliases_zh_hant. '
                'Use empty strings or arrays when evidence does not support a name. '
                'Do not overwrite existing names. Chinese may be a clearly draft translation. '
                'Avoid generic names such as traffic sign or supplementary plate when a specific name is unknown.'},
                {'role': 'user', 'content': json.dumps({'labels': payload}, ensure_ascii=False)}])
        result = json.loads(response.choices[0].message.content)
        suggestions = {entry['code']: entry for entry in result['labels']
                       if isinstance(entry, dict) and entry.get('code') in {item['code'] for item in subset}}
        for item in subset:
            if item['review_status'] == 'verified':
                continue
            suggestion = suggestions.get(item['code'], {})
            for field in ('name_en', 'name_zh_hant'):
                value = suggestion.get(field)
                if not item[field] and isinstance(value, str) and len(value) <= 100:
                    item[field] = value.strip()
            for field in ('aliases_en', 'aliases_zh_hant'):
                value = suggestion.get(field)
                if isinstance(value, list) and all(isinstance(name, str) and len(name) <= 60 for name in value):
                    item[field] = value[:5]
            item['review_status'] = 'pending_review'
            item['proposal_method'] = 'AI draft from official manual excerpts; requires human code and translation check'
        save(queue)
        print(f'batch {start//20+1}, entries {start+1}-{start+10}: '
              f"{sum(bool(item['name_en'] and item['name_zh_hant']) for item in subset)}/10 with draft names", flush=True)


if __name__ == '__main__':
    main()
