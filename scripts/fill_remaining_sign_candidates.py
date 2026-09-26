"""Add manually read, review-only labels from the drawing previews.

These are editorial proposals. No entry is promoted to verified here.
"""

import json

from suggest_sign_labels import QUEUE, save


PROPOSALS = {
    'TS_414': ('Left-pointing chevron', '向左箭紋標誌'),
    'TS_322': ('Green minibus stand', '綠色小巴站'),
    'TS_175': ('70 km/h speed limit', '時速七十公里限制'),
    'TS_2238': ('Two-hour parking meters', '兩小時停車收費錶'),
    'TS_2239': ('Two-hour parking meters', '兩小時停車收費錶'),
    'TS_581': ('Traffic enforcement camera', '交通執法攝影機'),
    'TS_410': ('Bend to the left ahead', '前方道路向左彎曲'),
    'TS_411': ('Bend to the right ahead', '前方道路向右彎曲'),
    'TS_712': ('Except with permit', '持有許可證者不在此限'),
    'TS_176': ('80 km/h speed limit', '時速八十公里限制'),
    'TS_198': ('End of no stopping restriction', '禁止停車限制終止'),
    'TS_282': ('Parking for buses only', '巴士專用泊車位'),
    'TS_586': ('Beware of Reversing Vehicles', '小心倒車車輛'),
    'TS_852': ('Except public light buses (scheduled services)', '專線小巴例外'),
    'TS_2702': ('Vehicle waiting will be prosecuted without warning', '停車等候會被檢控而不予警告'),
    'TS_347': ('Disabled person permit parking only (left arrow)', '殘疾人士泊車許可證車輛專用（向左）'),
    'TS_348': ('Disabled person permit parking only (right arrow)', '殘疾人士泊車許可證車輛專用（向右）'),
    'TS_483': ('Cyclists dismount', '騎單車者下車'),
    'TS_570': ('50 km/h speed limit ahead', '前方時速五十公里限制'),
    'TS_2235': ('Two-hour parking meters', '兩小時停車收費錶'),
    'TS_2234': ('Two-hour parking meters', '兩小時停車收費錶'),
    'TS_191': ('Keep left unless overtaking', '除越過前車外靠左駛'),
    'TS_177': ('100 km/h speed limit', '時速一百公里限制'),
    'TS_711': ('Except for access', '前往此區者不在此限'),
    'TS_173': ('30 km/h speed limit', '時速三十公里限制'),
}


def main():
    queue = json.loads(QUEUE.read_text(encoding='utf-8'))
    for item in queue:
        if item['code'] not in PROPOSALS or item['review_status'] == 'verified':
            continue
        en, zh = PROPOSALS[item['code']]
        item['name_en'], item['name_zh_hant'] = en, zh
        item['aliases_en'], item['aliases_zh_hant'] = [], []
        item['proposal_method'] = 'Draft read from drawing preview and, where available, official manual; human check required'
        item['candidate_source'] = '../../site/' + item['preview']
        item['review_status'] = 'pending_review'
        if item['code'] in ('TS_2238', 'TS_2239', 'TS_2235', 'TS_2234'):
            item['review_note'] = 'Check the exact meter restriction and arrow direction; the draft name is generic.'
        if item['code'] in ('TS_347', 'TS_348'):
            item['review_note'] = 'Check the full permit wording against the bilingual drawing.'
    save(queue)
    print(f"{sum(bool(item['name_en'] and item['name_zh_hant']) for item in queue)}/100 have draft bilingual names")


if __name__ == '__main__':
    main()
