"""Promote one explicitly approved queue entry into the public name index.

Run only after the owner checks the preview, both names, aliases, and sources.
The exact approved names must be supplied on the command line.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve', required=True, help='One drawing code, such as TS_115')
    parser.add_argument('--name-en', required=True, help='Exact reviewed English name')
    parser.add_argument('--name-zh-hant', required=True, help='Exact reviewed Traditional Chinese name')
    parser.add_argument('--reviewer', required=True, help='Person who checked this entry')
    args = parser.parse_args()
    queue_path = ROOT / 'data' / 'sign-review-queue.json'
    metadata_path = ROOT / 'data' / 'sign-metadata.json'
    queue = json.loads(queue_path.read_text(encoding='utf-8'))
    matches = [item for item in queue if item['code'] == args.approve]
    if len(matches) != 1:
        raise SystemExit('Code is not in the frozen review queue')
    item = matches[0]
    if item['name_en'] != args.name_en or item['name_zh_hant'] != args.name_zh_hant:
        raise SystemExit('Approved names must exactly match the reviewed queue entry')
    if not item.get('source', {}).get('url') or not args.reviewer.strip():
        raise SystemExit('Source and reviewer are required')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    metadata = [entry for entry in metadata if entry['code'] != args.approve]
    source = dict(item['source'])
    if item.get('evidence') and 'pdf_page' not in source:
        source['pdf_page'] = item['evidence'][0]['pdf_page']
    metadata.append({'code': args.approve, 'name_en': args.name_en,
                     'name_zh_hant': args.name_zh_hant,
                     'aliases_en': item['aliases_en'],
                     'aliases_zh_hant': item['aliases_zh_hant'],
                     'source': source, 'review_status': 'verified',
                     'review': {'reviewer': args.reviewer.strip(),
                                'approved_at': datetime.now(timezone.utc).isoformat()}})
    metadata.sort(key=lambda entry: entry['code'])
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    item['review_status'] = 'verified'
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Verified {args.approve}. Run the tests and restart the local backend.")


if __name__ == '__main__':
    main()
