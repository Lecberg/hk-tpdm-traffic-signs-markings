"""Add review-only names from downloaded Wikimedia Commons file descriptions.

The descriptions are secondary evidence. They may show older artwork, so the
queue remains pending until a person compares each name with the local drawing
and the current official manual.
"""

import glob
import json
import re
from pathlib import Path

from suggest_sign_labels import QUEUE, save


def main():
    queue = json.loads(QUEUE.read_text(encoding='utf-8'))
    pages = []
    for path in glob.glob('tmp/commons-*.json'):
        pages.extend(page for page in json.loads(Path(path).read_text(encoding='utf-8'))['query']['pages'].values()
                     if 'missing' not in page and page.get('revisions'))
    by_code = {}
    english_only = {}
    for page in pages:
        match = re.search(r'(\d+)\.svg$', page['title'])
        if not match:
            continue
        source = page['revisions'][0]['slots']['main'].get('*', '')
        en = re.search(r'\{\{en\|([^{}]+)\}\}', source)
        zh = re.search(r'\{\{zh-hant\|([^{}]+)\}\}', source)
        if en and zh:
            by_code[match.group(1)] = (en.group(1).strip(), zh.group(1).strip(), page['title'])
        elif en:
            english_only[match.group(1)] = (en.group(1).strip(), page['title'])
    updated = 0
    for item in queue:
        if item['review_status'] == 'verified':
            continue
        record = by_code.get(item['code'][3:])
        if not record and not item['name_en'] and item['code'][3:] in english_only:
            en, title = english_only[item['code'][3:]]
            item['name_en'] = en.removeprefix('1=').strip()
            item['candidate_source'] = 'https://commons.wikimedia.org/wiki/' + title.replace(' ', '_')
            item['proposal_method'] = 'Historic Commons English file description; Chinese translation needed'
        if not record or item['code'] in ('TS_101', 'TS_102'):
            continue
        en, zh, title = record
        en, zh = en.removeprefix('1=').strip(), zh.removeprefix('1=').strip()
        if not en or not zh or len(en) > 100 or len(zh) > 100:
            continue
        item['name_en'], item['name_zh_hant'] = en, zh
        item['aliases_en'], item['aliases_zh_hant'] = [], []
        item['candidate_source'] = 'https://commons.wikimedia.org/wiki/' + title.replace(' ', '_')
        item['proposal_method'] = ('Historic Commons bilingual file description; '
                                   'compare with current drawing and official manual before approval')
        item['review_status'] = 'pending_review'
        updated += 1
    save(queue)
    print(f'Added bilingual Commons proposals for {updated} codes. '
          f"{sum(bool(item['name_en'] and item['name_zh_hant']) for item in queue)}/100 now have draft names.")


if __name__ == '__main__':
    main()
