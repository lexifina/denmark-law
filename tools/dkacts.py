"""The acts in the record: every statute in force in Retsinformation, as the site's own search lists them.

    python -X utf8 scripts/denmark-law/dkacts.py [--offline]      # writes acts.json next to this file

Retsinformation's search (`/api/documentsearch`, document types 10 = LOV and 30 = LBK; 20 = amending acts, not asked, `h=false` = in force only) lists
each statute in force once, by its current document: the act as passed (LOVH) when it was never consolidated, else its
latest consolidation (LBKH). Amending acts (LOVC) are listed too; they are not acts of their own here. Each act's
timeline (`/api/document/<id>/timeline`) lists the act as passed (`isMainLaw`), its consolidations and its amending
acts. An act whose original text Retsinformation does not hold starts from its first consolidation.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from dkfetch import fetch

HERE = Path(__file__).resolve().parent
OUT = HERE / 'acts.json'
MAIN_TYPES = ('LOVH', 'LBKH')
SLUG_MAX = 60


def search_pages(offline: bool) -> list[dict]:
    docs, page = [], 1
    while True:
        d = json.loads(fetch(f'/api/documentsearch?dt=10&dt=30&h=false&ps=100&page={page}', offline=offline, kind='json'))
        docs += d['documents']
        if page >= d['pageCount']:
            return docs
        page += 1


def ascii_slug(text: str) -> str:
    t = text.lower().replace('æ', 'ae').replace('ø', 'oe').replace('å', 'aa')
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    t = re.sub(r'\([^)]*\)', ' ', t)
    words = re.findall(r'[a-z0-9]+', t)
    out = ''
    for w in words:
        if len(out) + len(w) + 1 > SLUG_MAX:
            break
        out = f'{out}-{w}' if out else w
    return out or 'lov'


def key_of(path: str) -> str:
    return re.sub(r'^/eli/lta/', '', path)


def select(offline: bool) -> dict:
    found = search_pages(offline)
    kinds: dict[str, int] = {}
    for d in found:
        kinds[d['documentTypeEliCode']] = kinds.get(d['documentTypeEliCode'], 0) + 1
    current = sorted((d for d in found if d['documentTypeEliCode'] in MAIN_TYPES and d['retsinfoLink'].startswith('/eli/lta/')),
                     key=lambda d: tuple(int(x) for x in key_of(d['retsinfoLink']).split('/')))
    acts, seen, skipped = [], {}, []
    for d in current:
        tl = json.loads(fetch(f'/api/document/{d["id"]}/timeline', offline=offline, kind='json'))
        mains = [x for x in tl if x.get('isMainLaw') and x['href'].startswith('/eli/lta/')]
        lbks = [key_of(x['href']) for x in tl if x['documentType'].startswith('LBK') and x['href'].startswith('/eli/lta/')]
        cur = key_of(d['retsinfoLink'])
        if mains:
            first, start = key_of(mains[0]['href']), 'LOV'
        elif lbks:
            first, start = sorted(lbks, key=lambda k: tuple(int(x) for x in k.split('/')))[0], 'LBK'
        else:
            first, start = cur, 'LBK' if d['documentTypeEliCode'] == 'LBKH' else 'LOV'
        if first in seen:
            skipped.append({'current': cur, 'reason': f'same act as {seen[first]}'})
            continue
        seen[first] = cur
        title = re.sub(r'^(Bekendtgørelse af|Lovbekendtgørelse af)\s+', '', d['title'].strip(), flags=re.I)
        popular = (d.get('popularTitle') or '').strip()
        law_word = (popular or title).lower()
        law_word = re.sub(r'\s*\(.*$', '', law_word).strip()
        acts.append({'id': first, 'current': cur, 'current_kind': d['documentTypeEliCode'], 'start': start,
                     'timeline': d['id'], 'popular': popular, 'title': d['title'].strip(), 'law': law_word,
                     'short': popular or title[:1].upper() + title[1:]})
    # Folder names: the popular title (or the title) in ASCII, unique; a clash takes the act's year and number.
    base = {}
    for a in acts:
        base.setdefault(ascii_slug(a['popular'] or re.sub(r'^(Bekendtgørelse af)\s+', '', a['title'], flags=re.I)), []).append(a)
    for s, group in base.items():
        for a in group:
            y, n = a['id'].split('/')
            a['slug'] = s if len(group) == 1 else f'{s}-{y}-{n}'
            if a['slug'] in ('lov', 'lbk', 'data', 'tools'):
                a['slug'] = f'{a["slug"]}-{y}-{n}'
    acts.sort(key=lambda a: tuple(int(x) for x in a['id'].split('/')))
    return {'listed': len(found), 'kinds': dict(sorted(kinds.items())), 'acts': acts, 'skipped': skipped}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline', action='store_true')
    a = ap.parse_args()
    r = select(a.offline)
    OUT.write_text(json.dumps(r, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'{r["listed"]} documents listed {r["kinds"]}; {len(r["acts"])} acts; {len(r["skipped"])} skipped')


if __name__ == '__main__':
    main()
