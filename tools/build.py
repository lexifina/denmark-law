"""Builds a git repository of Danish law from Retsinformation (www.retsinformation.dk), in which every amending act is one
commit, dated the day it took effect.

    python -X utf8 scripts/denmark-law/build.py [--repo ../denmark-law] [--today 2026-10-28] [--offline]
                                               [--verify-rebuild]

Retsinformation, the official legal database of Denmark (Civilstyrelsen), publishes each statute as passed (LOV) and
each consolidation (lovbekendtgørelse, LBK) as a document of its own. A consolidation says which amending acts it
incorporates (its list of "indarbejdede forskrifter" and its opening words: "med de ændringer, der følger af § 2 i lov
nr. 905 ...") and the valid-from day of the consolidated text. We take the act as passed and every later consolidation,
compare consecutive versions provision by provision, and credit each changed provision to the amending act among
those the consolidation incorporates whose amending article names that provision ("1. I § 5, stk. 2, ændres ..."). The
day a change took effect is read from the amending act's own commencement clause ("Loven træder i kraft den ...",
"§ 1, nr. 3, træder i kraft den ..."). A change nothing explains is never credited to an act: it is committed by
Retsinformation, labelled.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import dkfetch
import dkparse as P
from dkfetch import fetch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMMITTER = ('Lexifina', 'denmark-law@lexifina.com')
PUBLISHER = ('Retsinformation (Civilstyrelsen)', 'retsinformation@retsinformation.invalid')
SITE = 'https://www.retsinformation.dk'

# The acts in the record: every statute in force, as dkacts.py lists them from Retsinformation's own search (acts.json).
# `id` is the first document of the act (the act as passed, or its first consolidation when Retsinformation does not hold
# the act as passed), `timeline` Retsinformation's numeric id of the current document (its timeline lists the act, its
# amending acts and its consolidations), `law` the name an amending act's article uses for it ("skatteforvaltningsloven").
def load_acts() -> list[dict]:
    p = HERE / 'acts.json'
    if not p.exists():
        raise SystemExit('acts.json missing: run dkacts.py first')
    return json.loads(p.read_text(encoding='utf-8'))['acts']


TODAY: str | None = None   # versions valid from a later day are left out (set by main)
EDITORIAL = ('indledning', 'ikraft', 'slut', 'noter')
# A consolidation published before LOAD_ERA whose valid-from day is more than LOAD_GAP days after its publication carries
# the day Retsinformation loaded it, not a legal day: its publication day is used instead (Date-note: load-day).
LOAD_ERA = '1999-01-01'
LOAD_GAP = 60
# The days of the big loads; on these a gap of more than LOAD_GAP_SHORT days is enough (no consolidation of that era waits
# weeks after its publication to take effect). 1997-10-01 is not among them: it can be a real commencement day.
LOAD_DAYS = ('1997-09-24', '1997-09-25', '1998-03-15')
LOAD_GAP_SHORT = 14


# ---------------------------------------------------------------- Retsinformation documents

def eli(key: str) -> str:
    return f'{SITE}/eli/lta/{key}'


def iso(d: str) -> str | None:
    m = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})', (d or '').strip())
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def label_of(short: str) -> str:
    """'LOV nr 427 af 06/06/2005 ' -> 'LOV nr 427 af 06/06/2005'."""
    return P.clean(short)


def document(key: str, offline: bool) -> dict:
    """A document by its ELI path ('2005/427'): text as HTML plus its record (title, kind, ministry, days)."""
    d = json.loads(fetch(f'/api/document/eli/lta/{key}', post={'isRawHtml': False}, offline=offline, kind='json'))[0]
    meta = {m['displayName']: m['displayValue'] for m in d['metadata']}
    short = label_of(d['shortName'])
    m = re.match(r'(LOV|LBK|BEK)\b', short)
    return {'key': key, 'html': d['documentHtml'], 'short': short, 'kind': m.group(1) if m else '', 'title': P.clean(d['title']),
            'ministry': P.clean(d.get('ressort') or ''), 'published': iso(meta.get('Offentliggørelsesdato', '')),
            'enacted': iso(short.rsplit(' af ', 1)[-1]), 'accn': d['accessionNumber'], 'url': eli(key),
            'sha256': hashlib.sha256(d['documentHtml'].encode('utf-8')).hexdigest(), 'uid': d['id']}


def valid_from(key: str, offline: bool) -> str | None:
    """The day Retsinformation says a consolidation's text is valid from (StartDate in the document's XML metadata), or
    None when the XML gives none."""
    try:
        xml = fetch(f'/eli/lta/{key}/dan/xml', offline=offline).decode('utf-8')
    except dkfetch.Missing:   # the site cannot serve this document's XML: no valid-from day (the publication day is used)
        return None
    m = re.search(r'<StartDate[^>]*>(\d{4}-\d{2}-\d{2})', xml)
    return m.group(1) if m else None


def key_of(path: str) -> str:
    return re.sub(r'^/eli/lta/', '', path)


def key_order(k: str) -> tuple:
    y, n = k.split('/')
    return (int(y), int(n))


# ---------------------------------------------------------------- one act: versions, changes, causes

def removal_only(a, b) -> bool:
    if a and b is None:
        return True
    if not a or not b:
        return False
    old, new = a.rstrip('\n').split('\n\n'), b.rstrip('\n').split('\n\n')
    it = iter(old)
    return len(new) < len(old) and all(l in it for l in new)


def heads_split(t: str | None) -> tuple[list[str], set[str]]:
    lines = (t or '').rstrip('\n').split('\n\n') if t else []
    return [l for l in lines if not l.startswith('## ')], {l for l in lines if l.startswith('## ')}


def intro_map(indledning: str) -> dict[str, list[int]]:
    """Which article of which act a consolidation says it incorporates: '§ 2 i lov nr. 905 af 21. juni 2022' -> 905: [2].
    Only the first paragraph counts (a later one names changes that are not incorporated)."""
    first = indledning.split('\n\n')
    text = ''
    for line in first:
        if line.startswith(('Hermed bekendtgøres', 'Herved bekendtgøres')):
            text = line
            break
    out: dict[str, list[int]] = {}
    for art, num in re.findall(P.SECT + r'\s*(\d+)(?:,\s*stk\.\s*\d+)?\s*(?:i\s+)?lov\s+nr\.\s*(\d+)\s+af', text):
        out.setdefault(num, []).append(int(art))
    return out


def not_incorporated(indledning: str) -> dict[str, str]:
    """Acts the consolidation says it did not incorporate because they take effect later: 'year/number' -> that day."""
    out = {}
    for line in indledning.split('\n\n'):
        if 'ikke indarbejdet' in line:
            for num, year in re.findall(r'lov nr\.\s*(\d+)\s+af\s+\d{1,2}\.\s*\w+\s+(\d{4})', line):
                out[f'{year}/{int(num)}'] = P.danish_day(line.split('træder i kraft', 1)[-1]) or ''
    return out


NORM = re.compile(r'\W+')


def act_norm(doc: dict) -> str:
    return NORM.sub('', ' '.join(t for _, t in P.lines_of(doc['html'])).lower())


def added_lines(p: dict | None, c: dict) -> list[str]:
    old = set(NORM.sub('', l.lower()) for l in (p['lines'] if p else []))
    return [NORM.sub('', l.lower()) for l in c['lines'] if len(l) >= 40 and not l.startswith('## ')
            and NORM.sub('', l.lower()) not in old]


def read_act(act: dict, offline: bool) -> dict:
    key0 = act['id']
    tl = json.loads(fetch(f'/api/document/{act["timeline"]}/timeline', offline=offline, kind='json'))
    lbk_keys, seen = [], set()
    for x in tl:
        if x['documentType'].startswith('LBK') and x['href'] not in seen:
            seen.add(x['href'])
            lbk_keys.append(key_of(x['href']))
    versions = []
    docs = {}

    def add(key: str, start: str | None, kind: str):
        d = document(key, offline)
        if kind == 'LBK' and not start:
            start = d['published'] or d['enacted']
            d['from_note'] = 'no valid-from day in the XML; the day of publication is used'
        elif kind == 'LBK' and d['published'] and d['published'] < LOAD_ERA and \
                (dt.date.fromisoformat(start) - dt.date.fromisoformat(d['published'])).days > (
                    LOAD_GAP_SHORT if start in LOAD_DAYS else LOAD_GAP):
            # Documents from before Retsinformation existed carry the day they were loaded into it (1997-09-24/25,
            # 1997-10-01, 1998-03-15, 1999-07-27, ...) as their valid-from day, years after publication.
            d['from_note'] = 'load-day'
            d['load_day'] = start
            start = d['published']

        docs[key] = d
        parsed = P.read_units(d['html'])
        v = {'key': key, 'kind': kind, 'doc': d, 'from': start, 'units': parsed['units'], 'sha256': d['sha256'],
             'url': d['url'], 'page': d['url'], 'laws': [], 'incorporated': []}
        versions.append(v)
        return v
    start = act.get('start', 'LOV')
    add(key0, valid_from(key0, offline) if start == 'LBK' else None, start)
    for k in lbk_keys:
        if k != key0:
            add(k, valid_from(k, offline), 'LBK')
    versions[1:] = sorted(versions[1:], key=lambda v: (v['from'], key_order(v['key'])))
    if TODAY:
        versions[1:] = [v for v in versions[1:] if v['from'] <= TODAY]
    if start == 'LBK':   # a consolidation earlier than the first one we start from is not in the timeline order
        versions[1:] = [v for v in versions[1:] if v['from'] >= versions[0]['from']]
    # Each consolidation's incorporated acts: its own reference list.
    for v in versions:
        if v['kind'] != 'LBK':
            continue
        uid = v['doc']['uid']   # the document's id in the JSON, the same as <UniqueDocumentId> in its XML
        ref = json.loads(fetch(f'/api/document/{uid}/references/1', offline=offline, kind='json'))
        for g in ref['referenceGroups']:
            if g['header'] == 'Dokumentets indarbejdede forskrifter':
                v['incorporated'] = [(key_of(r['eliPath']), P.clean(r['shortName'])) for r in g['references']]
    return {'act': act, 'versions': versions, 'docs': docs}


def analyse_act(doc: dict, article_hint: list[int], law_word: str, offline: bool) -> dict:
    """What an amending act amends and when: the article(s) that amend our law, the provisions each item names, and the
    commencement of each."""
    lines = P.lines_of(doc['html'])
    arts = P.articles(lines)
    nums = [a for a in article_hint if a in arts]
    if not nums:
        nums = [n for n, t in sorted(arts.items()) if law_word in ' '.join(t[:2]).lower() and
                not re.search(r'i lov om|lov om ændring af (?!' + re.escape(law_word) + ')', t[0][:60].lower())]
    items: dict[int, dict[int, set[str]]] = {n: P.items_of(arts[n]) for n in nums}
    named: dict[str, list[tuple[int, int]]] = {}
    for n, its in items.items():
        for i, secs in its.items():
            for s in secs:
                named.setdefault(s, []).append((n, i))
    day, sentence = (None, '')
    if nums:
        day, sentence = P.commencement(arts, nums[0], None, doc['published'])
        if day is None and named:
            ds = []
            for u in named:
                for n, i in named[u]:
                    ds.append(P.commencement(arts, n, i, doc['published']))
            if ds and all(d for d, _ in ds):
                day, sentence = max(ds)
    return {'articles': nums, 'named': named, 'items': items, 'arts': arts, 'day': day, 'sentence': sentence}


def unit_day(an: dict, doc: dict, unit: str) -> tuple[str | None, str]:
    """The day the change to one provision took effect, from the item(s) of the amending act that name it."""
    days = {}
    for n, i in an['named'].get(unit, []):
        d, s = P.commencement(an['arts'], n, i, doc['published'])
        days[(n, i)] = (d, s)
    if not days:
        gl = [P.commencement(an['arts'], n, i, doc['published']) for n, i in an['named'].get('*', [])]
        if gl and all(d for d, _ in gl):
            return max(gl)
        return an['day'], an['sentence']
    ds = [v for v in days.values() if v[0]]
    if len(ds) < len(days):
        return None, ''
    return max(ds)


def build_act(act: dict, offline: bool) -> dict:
    r = read_act(act, offline)
    versions, docs = r['versions'], r['docs']
    own = act['id']
    # The act as passed: its own commencement clause gives the first day.
    base = docs[own]
    note0 = ''
    if versions[0]['kind'] == 'LBK':
        day0, sentence0 = versions[0]['from'], ''
    else:
        lines0 = P.lines_of(base['html'])
        day0, sentence0 = P.commencement(P.articles(lines0), None, None, base['published'])
        if not day0:
            straks = [t for _, t in lines0 if re.search(r'træder i kraft straks', t)]
            if straks:   # "Denne grundlov træder i kraft straks": the day it was signed
                day0, sentence0 = base['enacted'], straks[0]
            else:
                day0, note0 = (base['published'] or base['enacted']), 'undated'
        if len(versions) > 1 and day0 > versions[1]['from']:
            day0, note0 = versions[1]['from'], 'early'
    if not day0:
        raise SystemExit(f'{own}: no first day')
    versions[0]['from'] = day0
    versions[0]['own_sentence'] = sentence0
    versions[0]['note'] = note0
    changes, problems = [], []
    laws: dict[str, dict] = {own: base}
    analyses: dict[str, dict] = {}
    later_prev: dict[str, str] = {}
    for prev, cur in zip(versions, versions[1:]):
        later_prev = not_incorporated(prev['units'].get('indledning', {}).get('text', '')) if prev['kind'] == 'LBK' else {}
        exclude = {prev['key'], own}
        # consolidations (LBK) and Retsinformation's own data compilations (DSK, "Datasammenskrivning", under
        # /eli/retsinfo/) are texts of the act, not acts that amend it
        acts = [(k, s) for k, s in cur['incorporated'] if not s.startswith(('LBK', 'DSK')) and k not in exclude]
        # an act already incorporated in an earlier version is not new here
        done = {k for v in versions[:versions.index(cur)] for k, _ in v['incorporated']}
        acts = [(k, s) for k, s in acts if k not in done]
        cur['laws'] = [k for k, _ in acts]
        carried = []
        for k in sorted(later_prev, key=key_order):
            if k in done and k not in {x for x, _ in acts}:
                carried.append(k)
        intro = cur['units'].get('indledning', {}).get('text', '')
        amap = intro_map(intro)
        later = not_incorporated(intro)
        window_prev, window_cur = prev['from'], cur['from']
        for k, s in acts:
            if k not in laws:
                laws[k] = document(k, offline)
            num = k.split('/')[1]
            analyses[(k, cur['key'])] = analyse_act(laws[k], amap.get(num, []), act['law'], offline)
        for k in carried:
            if k not in laws:
                laws[k] = document(k, offline)
            # the article numbers were named by the earlier consolidation that incorporated the act
            hint = []
            for v in versions[1:versions.index(cur)]:
                hint += intro_map(v['units'].get('indledning', {}).get('text', '')).get(k.split('/')[1], [])
            analyses[(k, cur['key'])] = analyse_act(laws[k], hint, act['law'], offline)
            analyses[(k, cur['key'])]['carried'] = True
        norms = {k: act_norm(laws[k]) for k in [x for x, _ in acts] + carried}
        allkeys = sorted(set(prev['units']) | set(cur['units']), key=P.unit_order)
        changed = [k for k in allkeys if (prev['units'].get(k) or {}).get('text') != (cur['units'].get(k) or {}).get('text')]
        cause, why, when, evid = {}, {}, {}, {}
        for u in changed:
            p, c = prev['units'].get(u), cur['units'].get(u)
            if u in EDITORIAL:
                cause[u], why[u] = 'publisher', 'editorial part of the consolidation (opening words, reprinted provisions of amending acts, signatures, notes)'
                continue
            cands = []
            for k, _ in acts:
                if u in analyses[(k, cur['key'])]['named']:
                    d_ = unit_day(analyses[(k, cur['key'])], laws[k], u)[0]
                    if d_ and d_ > window_cur:
                        continue   # takes effect after this consolidation: not in its text (the next one carries it)
                    cands.append(k)
            for k in carried:   # an act printed in the consolidation before only in part: its later parts
                d_ = unit_day(analyses[(k, cur['key'])], laws[k], u)[0]
                if u in analyses[(k, cur['key'])]['named'] and d_ and d_ > window_prev:
                    cands.append(k)
            if len(cands) == 1:
                cause[u], why[u] = cands[0], 'named by the amending article'
            elif len(cands) > 1:
                cause[u], why[u] = 'candidates', 'named by the amending articles of more than one act'
                evid[u] = cands
            else:
                gl = [k for k, _ in acts if '*' in analyses[(k, cur['key'])]['named']]
                if len(gl) == 1 and u not in EDITORIAL:
                    cause[u], why[u] = gl[0], 'global replacement item of the amending article'
                elif len(gl) > 1:
                    cause[u], why[u] = 'candidates', 'global replacement items of more than one act'
                    evid[u] = gl
                else:
                    # last evidence: the new wording is quoted word for word in the text of an act of this window
                    hits = []
                    c_ = cur['units'].get(u)
                    add = added_lines(prev['units'].get(u), c_) if c_ else []
                    if add and u not in EDITORIAL:
                        for k in [x for x, _ in acts] + carried:
                            if any(x in norms[k] for x in add):
                                hits.append(k)
                    if len(hits) == 1:
                        cause[u], why[u] = hits[0], 'the new wording is quoted in the amending act'
                    elif len(hits) > 1:
                        cause[u], why[u] = 'candidates', 'the new wording is quoted in more than one act'
                        evid[u] = hits
                    else:
                        cause[u], why[u] = 'unexplained', 'no amending article of the consolidation names it'
        # Headings that only moved with a neighbouring provision an act changed.
        order = sorted(set(prev['units']) | set(cur['units']), key=P.unit_order)
        for u in changed:
            if cause[u] != 'unexplained':
                continue
            p, c = prev['units'].get(u), cur['units'].get(u)
            if p and c and heads_split(p['text'])[0] == heads_split(c['text'])[0]:
                moved = heads_split(p['text'])[1] ^ heads_split(c['text'])[1]
                i = order.index(u)
                for nb in (order[i - 1] if i else None, order[i + 1] if i + 1 < len(order) else None):
                    if nb in cause and cause[nb] not in ('unexplained', 'candidates', 'publisher') and moved:
                        cause[u], why[u] = cause[nb], f'headings moved with {nb}'
                        break
        # Dates.
        for u in changed:
            c = cause[u]
            if c in ('publisher', 'unexplained'):
                when[u] = window_cur
            elif c == 'candidates':
                ds = [unit_day(analyses[(k, cur['key'])], laws[k], u)[0] for k in evid[u]]
                when[u] = max(ds) if all(ds) else window_cur
            else:
                an = analyses[(c, cur['key'])]
                if why[u].startswith('headings moved'):
                    d, s = an['day'], an['sentence']
                    nb = why[u].split()[-1]
                    d, s = unit_day(an, laws[c], nb)
                else:
                    d, s = unit_day(an, laws[c], u)
                when[u] = d
                evid[u] = s
        groups: dict[tuple, list[str]] = {}
        for u in changed:
            c = cause[u]
            if c in ('unexplained', 'publisher'):
                groups.setdefault((c, window_cur), []).append(u)
                continue
            d = when[u]
            note = ''
            if d is None:
                d, note = window_cur, 'undated'
            elif d > window_cur:
                d, note = window_cur, 'early'
            elif d <= window_prev:
                # in force (by its own words) on or before the previous consolidation's day, which does not show it: the
                # official text on that day must stay as published, so the change comes the day after
                d, note = min(window_cur, (dt.date.fromisoformat(window_prev) + dt.timedelta(days=1)).isoformat()), 'late'
            when[u] = d
            why[u] = why[u] + ('' if not note else f'; day {note}')
            groups.setdefault((c if c != 'candidates' else 'candidates:' + ','.join(sorted(evid[u])), d), []).append(u)
        for k in carried:
            if not any(g[0] == k or k in g[0] for g in groups):
                analyses[(k, cur['key'])]['unused'] = True
        for k, _ in acts:   # every incorporated act is in the record, even if no file of ours changes that day
            an = analyses[(k, cur['key'])]
            d = an['day']
            if not any(g[0] == k for g in groups):
                d2 = d if d and window_prev <= d <= window_cur else window_cur
                groups[(k, d2)] = []
        for u in changed:
            if cause[u] in ('unexplained',):
                problems.append(f'{cur["from"]} {u} ({why[u]})')
        changes.append({'from': cur['from'], 'url': cur['page'], 'laws': [k for k, _ in acts], 'groups': groups,
                        'cause': cause, 'why': why, 'when': when, 'evid': evid, 'prev': prev, 'cur': cur,
                        'later': later, 'analyses': {k: analyses[(k, cur['key'])] for k in [x for x, _ in acts] + carried},
                        'window': (window_prev, window_cur)})
    title = base['title']
    return {'act': act, 'versions': versions, 'laws': laws, 'changes': changes, 'problems': problems, 'title': title,
            'label': base['short'], 'key': own}


# ---------------------------------------------------------------- the git repository

def git(repo: Path, *args: str, env: dict | None = None, input: str | None = None) -> str:
    out = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, encoding='utf-8', env=env, input=input)
    if out.returncode:
        raise SystemExit(f'git {" ".join(args)} failed: {out.stderr}')
    return out.stdout


def last_sunday(year: int, month: int) -> dt.date:
    d = (dt.date(year, month + 1, 1) if month < 12 else dt.date(year + 1, 1, 1)) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def copenhagen_offset(day: dt.date) -> int:
    """Hours ahead of UTC at noon on a day in Copenhagen (written out: this machine has no tz database). Central
    European Time; summer time from the last Sunday in March to the last Sunday in September until 1995 and in October
    since 1996, from 1980 (Denmark had none before)."""
    y = day.year
    if y < 1980:
        return 1
    return 2 if last_sunday(y, 3) <= day < last_sunday(y, 9 if y < 1996 else 10) else 1


def commit_date(day: str, seq: list[int]) -> str:
    """Noon in Copenhagen on the day. Git cannot record a time before 1970, so changes in force before then are dated
    1 January 1970 (UTC), one second apart in the order they took effect; the real day is in the In-force trailer."""
    d = dt.date.fromisoformat(day)
    if d.year < 1970:
        seq[0] += 1
        return f'@{seq[0]} +0000'
    off = copenhagen_offset(d)
    stamp = int(dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone(dt.timedelta(hours=off))).timestamp())
    return f'@{stamp} +0{off}00'


def author_of(label: str, key: str) -> tuple[str, str]:
    y, n = key.split('/')
    kind = label.split()[0].lower()
    return label, f'{kind}-{y}-{int(n)}@retsinformation.invalid'


def tag_of(label: str, key: str) -> str:
    y, n = key.split('/')
    return f'{label.split()[0].lower()}/{y}-{int(n)}'


def write_unit(repo: Path, slug: str, key: str, unit: dict | None):
    path = repo / slug / f'{key}.md'
    if unit is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit['text'], encoding='utf-8', newline='\n')


PRE_1970 = ['Git kan ikke gemme datoer før 1970, så denne commit er dateret 1. januar 1970; ikrafttrædelsesdagen står',
            'i linjen In-force. (Git cannot record dates before 1970: the real day is In-force.)', '']


def units_of(ch: dict, grp: str, day: str) -> list[str]:
    return sorted(ch['groups'].get((grp, day), []), key=P.unit_order)


def listing(ch: dict, keys: list[str]) -> tuple[list[str], list[str]]:
    labels, lines = [], []
    by: dict[str, list[str]] = {}
    for k in keys:
        p, c = ch['prev']['units'].get(k), ch['cur']['units'].get(k)
        lab = (c or p)['label']
        labels.append(lab)
        by.setdefault('Indsat' if p is None else 'Udgået' if c is None else 'Ændret', []).append(lab)
    for name in ('Indsat', 'Ændret', 'Udgået'):
        if name in by:
            lines.append(f'{name}: {", ".join(by[name])}')
    return labels, lines


def date_note(d: dict) -> str:
    if d.get('from_note') == 'load-day':
        return (f'Date-note: load-day (Retsinformation gives {d["load_day"]}, the day it loaded the document; '
                f'the day of publication is used)')
    return 'Date-note: undated'


def start_message(b: dict, day: str):
    v = b['versions'][0]
    d = b['laws'][b['key']]
    if v['kind'] == 'LBK':
        msg = [f'{b["act"]["short"]}: {d["short"]} (første tekst i Retsinformation)', '', d['title'], '',
               'Retsinformation har ikke loven som vedtaget. Den første tekst, den har, er denne lovbekendtgørelse; den',
               'gengiver loven med de ændringer, der var sket indtil da, og tilskrives derfor ikke nogen lov.', '',
               'Retsinformation does not hold the act as passed. The first text it holds is this consolidation, which reprints',
               'the act with the changes made until then, so it is credited to no act.', '']
        trailers = ['Kind: LBK', f'Issuer: {d["ministry"]}']
        trailers += [f'Enacted: {d["enacted"]}'] if d['enacted'] else []
        trailers += [f'Published: {d["published"]} ({d["short"]})'] if d['published'] else []
        trailers += [f'In-force: {day}', 'Evidence: the valid-from day Retsinformation gives for the consolidation'
                     if not d.get('from_note') else date_note(d)]
        if d['published'] and day < d['published']:
            trailers.append('Date-note: the valid-from day Retsinformation gives is earlier than the day of publication')
        trailers += [f'Source: {d["url"]}']
        if day < '1970-01-01':
            msg += PRE_1970
        return PUBLISHER, msg, trailers
    author = author_of(d['short'], b['key'])
    msg = [f'{b["act"]["short"]}: {d["title"]} ({d["short"]})', '',
           'Loven som vedtaget, i den tekst Retsinformation udgiver den i, med ikrafttræden fra denne dag.', '',
           'The act as passed, in the text Retsinformation publishes it in, in force from this day.', '']
    trailers = ['Kind: LOV', f'Issuer: {d["ministry"]}']
    trailers += [f'Enacted: {d["enacted"]}'] if d['enacted'] else []
    trailers += [f'Published: {d["published"]} ({d["short"]})'] if d['published'] else []
    trailers += [f'In-force: {day}']
    if v.get('own_sentence'):
        msg += ['Ikrafttræden læst i loven selv:', '', f'> {v["own_sentence"]}', '',
                'Commencement read from the act itself, quoted above.', '']
        trailers.append('Evidence: commencement clause of the act itself')
    if v.get('note') == 'undated':
        msg += ['Bemærkning: dagen er ikke læst i loven (fx fastsat af en minister); dagen for offentliggørelsen bruges.', '']
        trailers.append('Date-note: undated')
    elif v.get('note') == 'early':
        msg += ['Bemærkning: loven træder i kraft efter den første lovbekendtgørelses dag; dennes dag bruges.', '']
        trailers.append('Date-note: early')
    trailers += [f'Source: {d["url"]}']
    if day < '1970-01-01':
        msg += PRE_1970
    return author, msg, trailers


def change_message(b: dict, c: dict):
    ch, kind = c['ch'], c['kind']
    short = b['act']['short']
    day = c['day']
    trailers = []
    if kind == 'law':
        law = c['law']
        keys = units_of(ch, law, day)
        labels, lst = listing(ch, keys)
        lm = b['laws'][law]
        an = ch['analyses'][law]
        author = author_of(lm['short'], law)
        subject = f'{short}: {", ".join(labels) if labels else "ingen ændring i teksten"} ({lm["short"]})'
        if len(subject) > 100:
            subject = f'{short}: {len(labels)} bestemmelser ({lm["short"]})'
        msg = [subject, '', lm['title'], ''] + lst + ([''] if lst else [])
        if not keys:
            msg += ['Lovbekendtgørelsen opfører denne lov som indarbejdet, men ingen af bestemmelsernes ord er ændret af den.', '',
                    'The consolidation lists this act as incorporated, but none of the words of this text changed.', '']
        art = ', '.join(f'§ {n}' for n in an['articles'])
        if keys:
            trailers.append('Evidence: the amending article (' + (art or 'none read') + f' of {lm["short"]}) names ' +
                            ', '.join(labels))
        sents = sorted({ch['evid'].get(k) for k in keys if isinstance(ch['evid'].get(k), str) and ch['evid'].get(k)}
                       | ({an['sentence']} if not keys and an['sentence'] else set()))
        if sents:
            msg += ['Ikrafttræden læst i den ændrende lov:', ''] + [f'> {s}' for s in sents] + ['',
                    'Commencement read from the amending act, quoted above.', '']
            trailers.append('Evidence: commencement clause of the amending act')
        notes = [ch['why'][k] for k in keys if '; day ' in ch['why'][k]]
        if notes or (not keys and an['day'] is None):
            kinds = {n.split('; day ')[1] for n in notes} | ({'undated'} if (not keys and an['day'] is None) else set())
            what = {'undated': 'dagen er ikke læst i loven (fx fastsat af en minister); dagen for lovbekendtgørelsen bruges',
                    'early': 'loven træder i kraft efter lovbekendtgørelsens dag men er trykt i den; dagen for lovbekendtgørelsen bruges',
                    'late': 'loven træder i kraft på eller før forrige lovbekendtgørelses dag, men den viser ikke ændringen; dagen efter bruges'}
            msg += [f'Bemærkning: {what[k]}.' for k in sorted(kinds)] + ['']
            trailers += [f'Date-note: {k}' for k in sorted(kinds)]
        trailers += ['Kind: LOV', f'Issuer: {lm["ministry"]}']
        trailers += [f'Enacted: {lm["enacted"]}'] if lm['enacted'] else []
        trailers += [f'Published: {lm["published"]} ({lm["short"]})'] if lm['published'] else []
        trailers.append(f'In-force: {day}')
        if lm['published'] and day < lm['published']:
            trailers.append('Date-note: the in-force day is earlier than the day of publication')
        trailers += [f'Affecting: {b["label"]} {l}' for l in labels]
        trailers.append(f'Source: {lm["url"]}')
    elif kind == 'candidates':
        author = PUBLISHER
        cands = c['grp'].split(':', 1)[1].split(',')
        keys = units_of(ch, c['grp'], day)
        labels, lst = listing(ch, keys)
        names = ', '.join(b['laws'][l]['short'] for l in cands)
        msg = [f'{short}: {", ".join(labels) if len(labels) < 5 else str(len(labels)) + " bestemmelser"} (flere love)', '',
               f'Flere love, {names}, nævner disse bestemmelser i deres ændringsartikler. Lovbekendtgørelsen viser kun',
               'resultatet, så ændringen er ikke tilskrevet nogen af dem.', ''] + lst + [''] + [
               f'{names} all name these provisions in their amending articles. The consolidation shows only the result, so',
               'the change is credited to none of them.', '']
        msg += [f'- {b["laws"][l]["short"]}: {b["laws"][l]["title"]}' for l in cands] + ['']
        trailers += [f'In-force: {day}'] + [f'Affecting: {b["label"]} {l}' for l in labels]
        trailers += [f'Candidate: {b["laws"][l]["short"]}' for l in cands]
        trailers.append('Evidence: the amending articles of each candidate name these provisions; the latest of their commencement days is used')
    else:   # consolidation: editorial parts and anything nothing explains
        author = PUBLISHER
        v = ch['cur']
        d = v['doc']
        keys = sorted(ch['groups'].get(('publisher', ch['from']), []) + ch['groups'].get(('unexplained', ch['from']), []),
                      key=P.unit_order)
        labels, lst = listing(ch, keys)
        unex = ch['groups'].get(('unexplained', ch['from']), [])
        msg = [f'{short}: {d["short"]} (lovbekendtgørelse)', '',
               f'{d["title"]}', '',
               'Lovbekendtgørelsen genudgiver loven med de ændringer den indarbejder. Denne commit indeholder dens egne dele',
               '(indledning, underskrifter, noter)' + (' og ændringer som ingen ændringsartikel forklarer:' if unex else ':'), ''] + lst + ['',
               'The consolidation republishes the act with the changes it incorporates. This commit holds its own parts',
               '(opening words, signatures, notes)' + (' and changes no amending article explains.' if unex else '.'), '']
        if unex:
            msg += ['Ikke tilskrevet nogen lov: ' + ', '.join(v['units'][k]['label'] if k in v['units'] else ch['prev']['units'][k]['label'] for k in unex) + '.', '']
        if ch['later']:
            msg += ['Lovbekendtgørelsen oplyser at følgende ændringer ikke er indarbejdet, fordi de træder i kraft senere: '
                    + ', '.join(f'lov nr. {n}' + (f' ({day_})' if day_ else '') for n, day_ in sorted(ch['later'].items())) + '.', '']
        trailers += [f'In-force: {ch["from"]}'] + ([f'Affecting: {b["label"]} {l}' for l in labels] or ['Affecting: none'])
        trailers += [f'Version-act: {b["laws"][l]["short"]}' for l in ch['laws']] or ['Version-act: none']
        trailers += ['Kind: LBK', f'Issuer: {d["ministry"]}']
        if d.get('from_note'):
            trailers.append(date_note(d))
        if d['enacted']:
            trailers.append(f'Enacted: {d["enacted"]}')
        if d['published']:
            trailers.append(f'Published: {d["published"]} ({d["short"]})')
            if ch['from'] < d['published']:
                trailers.append('Date-note: the valid-from day Retsinformation gives is earlier than the day of publication')
        trailers.append(f'Source: {d["url"]}')
        keys_all = keys
        keys = keys_all
    trailers.append(f'Consolidated: {ch["url"]}')
    if day < '1970-01-01':
        msg += PRE_1970
    return author, msg, trailers, keys


TRAILER_ORDER = ('Evidence', 'Date-note', 'Candidate', 'Kind', 'Issuer', 'Enacted', 'Published', 'In-force', 'Affecting',
                 'Version-act', 'Source', 'Consolidated')
LISTED = ('no amending article of the consolidation names it', 'named by the amending articles of more than one act',
          'global replacement items of more than one act', 'the new wording is quoted in more than one act')


def order_trailers(trailers: list[str]) -> list[str]:
    """The trailers without repeats, grouped by key in a fixed order (the order within a key is kept)."""
    seen, out = set(), []
    for t in trailers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    rank = {k: i for i, k in enumerate(TRAILER_ORDER)}
    return sorted(out, key=lambda t: rank.get(t.split(':', 1)[0], len(rank)))


def act_events(act: dict, offline: bool) -> tuple[dict, list[dict]]:
    """One act's commits as events (no HTML kept), and the facts about it the tables and REPRODUCE.md need."""
    b = build_act(act, offline)
    slug = act['slug']
    events = []
    v0 = b['versions'][0]
    author, msg, trailers = start_message(b, v0['from'])
    d0 = b['laws'][b['key']]
    files = {f'{slug}/{k}.md': u['text'] for k, u in sorted(v0['units'].items())}
    events.append({'day': v0['from'], 'kind': 'start', 'grp': ('start', slug) if v0['kind'] == 'LBK' else ('law', b['key']),
                   'slug': slug, 'act_short': act['short'], 'author': author, 'msg': msg, 'trailers': trailers,
                   'body': msg[2:], 'lm': {'short': d0['short'], 'title': d0['title']}, 'files': files,
                   'tag': (d0['short'], b['key']), 'units': len(files)})
    for ch in b['changes']:
        for (grp, day) in sorted(ch['groups'], key=lambda g: (g[1], g[0])):
            if grp in ('unexplained', 'publisher'):
                continue
            if grp.startswith('candidates:'):
                c = {'kind': 'candidates', 'b': b, 'ch': ch, 'grp': grp, 'day': day}
            else:
                c = {'kind': 'law', 'b': b, 'ch': ch, 'law': grp, 'day': day}
            author, msg, trailers, keys = change_message(b, c)
            files = {f'{slug}/{k}.md': (ch['cur']['units'][k]['text'] if k in ch['cur']['units'] else None) for k in keys}
            if c['kind'] == 'law':
                lm = b['laws'][grp]
                events.append({'day': day, 'kind': 'law', 'grp': ('law', grp), 'slug': slug, 'act_short': act['short'],
                               'author': author, 'msg': msg, 'trailers': trailers, 'body': msg[4:],
                               'lm': {'short': lm['short'], 'title': lm['title']}, 'files': files,
                               'tag': (lm['short'], grp), 'units': len(keys)})
            else:
                events.append({'day': day, 'kind': 'candidates', 'grp': ('cand', f'{slug} {grp}'), 'slug': slug,
                               'author': author, 'msg': msg, 'trailers': trailers, 'files': files, 'tag': None,
                               'units': len(keys)})
        c = {'kind': 'consolidation', 'b': b, 'ch': ch, 'day': ch['from']}
        author, msg, trailers, keys = change_message(b, c)
        files = {f'{slug}/{k}.md': (ch['cur']['units'][k]['text'] if k in ch['cur']['units'] else None) for k in keys}
        v = ch['cur']
        events.append({'day': ch['from'], 'kind': 'consolidation', 'grp': ('cons', '%s %04d/%07d' % ((slug,) + key_order(ch['cur']['key']))), 'slug': slug, 'author': author,
                       'msg': msg, 'trailers': trailers, 'files': files, 'tag': (v['doc']['short'], v['key']),
                       'units': len(keys)})
    # The facts for the tables, the manifest and REPRODUCE.md.
    why: dict[str, int] = {}
    listed: dict[str, list[str]] = {}
    for ch in b['changes']:
        for k, w in sorted(ch['why'].items()):
            w2 = 'headings moved' if w.startswith('headings moved') else w.split('; day ')[0]
            why[w2] = why.get(w2, 0) + 1
            if w2 in LISTED:
                lab = (ch['cur']['units'].get(k) or ch['prev']['units'][k])['label']
                listed.setdefault(w2, []).append(f'{act["short"]} {ch["from"]}: {lab}')
    rows = [{'lov': act['short'], 'nummer': d0['short'], 'titel': d0['title'], 'type': v0['kind'],
             'vedtaget': d0['enacted'] or '', 'offentliggjort': d0['published'] or '', 'ikraft': v0['from'],
             'bestemmelser': len(v0['units']),
             'bemaerkning': 'som vedtaget' if v0['kind'] == 'LOV' else 'første tekst i Retsinformation',
             'kilde': d0['url']}]
    counts: dict[str, int] = {}
    lastday: dict[str, str] = {}
    for ch in b['changes']:
        for (grp, day), keys in sorted(ch['groups'].items(), key=lambda x: (x[0][1], x[0][0])):
            for k in keys:
                counts[k] = counts.get(k, 0) + 1
                lastday[k] = max(lastday.get(k, ''), day)
            if grp in ('unexplained', 'publisher') or grp.startswith('candidates:'):
                continue
            lm = b['laws'][grp]
            rows.append({'lov': act['short'], 'nummer': lm['short'], 'titel': lm['title'], 'type': 'LOV',
                         'vedtaget': lm['enacted'] or '', 'offentliggjort': lm['published'] or '', 'ikraft': day,
                         'bestemmelser': len(keys), 'bemaerkning': '', 'kilde': lm['url']})
        d = ch['cur']['doc']
        rows.append({'lov': act['short'], 'nummer': d['short'], 'titel': d['title'], 'type': 'LBK',
                     'vedtaget': d['enacted'] or '', 'offentliggjort': d['published'] or '', 'ikraft': ch['from'],
                     'bestemmelser': len(ch['cur']['units']), 'bemaerkning': 'lovbekendtgørelse', 'kilde': d['url']})
    last = b['versions'][-1]
    readme = [f'# {b["title"]}', '', f'{b["label"]} · <{d0["url"]}>', '',
              f'{len(b["versions"])} versioner i Retsinformation, gældende fra {v0["from"]} (seneste fra {last["from"]}).', '',
              '| Bestemmelse | Fil | Ændringer | Senest ændret |', '| --- | --- | ---: | --- |']
    for k in sorted(last['units'], key=P.unit_order):
        u = last['units'][k]
        readme.append(f'| {u["label"]} | [{k}.md]({k}.md) | {counts.get(k, 0)} | {lastday.get(k, "")} |')
    summary = {'act': act, 'label': b['label'], 'title': b['title'], 'key': b['key'], 'problems': b['problems'],
               'versions': [{'from': v['from'], 'kind': v['kind'], 'document': v['doc']['short'], 'url': v['url'],
                             'sha256': v['sha256'], 'incorporated': [s_ for _, s_ in v['incorporated']],
                             'units': len(v['units'])} for v in b['versions']],
               'why': why, 'listed': listed, 'rows': rows, 'readme': readme,
               'unit_changes': sum(len(ks) for ch in b['changes'] for ks in ch['groups'].values()),
               'days': sorted({e['day'] for e in events})}
    return summary, events


def act_worker(args):
    act, offline = args
    try:
        return act_events(act, offline)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:   # an act that cannot be read is left out and reported, not the whole build
        import traceback
        return {'act': act, 'error': f'{type(exc).__name__}: {exc}'[:300], 'trace': traceback.format_exc()[-1500:]}, []


def compose(evs: list[dict]) -> tuple[tuple[str, str], list[str], list[str]]:
    """One commit's author, message lines and trailers. One amending act's changes on one day to several acts are one
    commit: the act's title, then each act it changes with its provisions."""
    if len(evs) == 1:
        e = evs[0]
        return e['author'], e['msg'], order_trailers(e['trailers'])
    lm = evs[0]['lm']
    names = [e['act_short'] for e in evs]
    subject = f'{len(evs)} love: {", ".join(names)} ({lm["short"]})'
    if len(subject) > 100:
        subject = f'{len(evs)} love ({lm["short"]})'
    msg = [subject, '', lm['title'], '',
           f'Denne lov ændrer {len(evs)} love i registret; hver står nedenfor med sine bestemmelser.', '',
           f'This act changes {len(evs)} acts in the record; each is listed below with its provisions.', '']
    for e in evs:
        body = [l for l in e['body'] if l not in PRE_1970]
        while body and body[-1] == '':
            body.pop()
        msg += [f'{e["act_short"]}:', ''] + body + ['']
    if evs[0]['day'] < '1970-01-01':
        msg += PRE_1970
    trailers = order_trailers([t for e in evs for t in e['trailers']])
    return evs[0]['author'], msg, trailers


def plan(results: list[tuple[dict, list[dict]]]) -> list[tuple[tuple, list[dict]]]:
    """Every commit in the order the changes took effect: on one day, the first texts of acts and the amending acts in
    the order of their numbers, then changes several acts could explain, then each consolidation's own commit (last, so
    the text on its day is the official text)."""
    groups: dict[tuple, list[dict]] = {}
    for _, evs in results:
        for e in evs:
            groups.setdefault((e['day'],) + e['grp'], []).append(e)
    out = []
    for k, evs in groups.items():
        evs.sort(key=lambda e: e['slug'])
        day, kind, ident = k
        if kind == 'law':
            rank = 0 if any(e['kind'] == 'start' for e in evs) else 1
            sub = key_order(ident) + ('',)
        else:
            rank = {'start': 0, 'cand': 2, 'cons': 3}[kind]
            sub = (0, 0, ident)
        out.append(((day, rank) + sub, evs))
    out.sort(key=lambda x: x[0])
    return out


def write_repo(repo: Path, results: list[tuple[dict, list[dict]]], docs: Path, today: str):
    remote = None
    if (repo / '.git').exists():
        out = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=repo, capture_output=True, text=True)
        remote = out.stdout.strip() or None

    def force(fn, path, _exc):
        os.chmod(path, 0o700)
        fn(path)
    if repo.exists():
        for p in repo.iterdir():
            shutil.rmtree(p, onexc=force) if p.is_dir() else p.unlink()
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'config', 'core.longpaths', 'true')
    if remote:
        git(repo, 'remote', 'add', 'origin', remote)
    seq = [0]
    tags: dict[str, int] = {}
    law_days: dict[str, list[tuple[str, int]]] = {}
    log = []
    stream_path = repo / '.git' / 'build-stream.fi'
    committer = f'{COMMITTER[0]} <{COMMITTER[1]}>'.encode()
    with open(stream_path, 'wb') as fi:
        mark = 0
        for (day, *_), evs in plan(results):
            author, msg, trailers = compose(evs)
            text = ('\n'.join(msg).rstrip('\n') + '\n\n' + '\n'.join(trailers) + '\n').encode('utf-8')
            when = commit_date(day, seq).lstrip('@').encode()
            mark += 1
            fi.write(b'commit refs/heads/main\nmark :%d\n' % mark)
            fi.write(b'author ' + f'{author[0]} <{author[1]}>'.encode('utf-8') + b' ' + when + b'\n')
            fi.write(b'committer ' + committer + b' ' + when + b'\n')
            fi.write(b'data %d\n' % len(text) + text + b'\n')
            if mark > 1:
                fi.write(b'from :%d\n' % (mark - 1))
            for e in evs:
                for path in sorted(e['files']):
                    content = e['files'][path]
                    if content is None:
                        fi.write(b'D ' + path.encode('utf-8') + b'\n')
                    else:
                        data = content.encode('utf-8')
                        fi.write(b'M 100644 inline ' + path.encode('utf-8') + b'\ndata %d\n' % len(data) + data + b'\n')
            fi.write(b'\n')
            for e in evs:
                tags[f'{e["slug"]}/{day}'] = mark
                if e['tag']:
                    t = tag_of(e['tag'][0], e['tag'][1])
                    days = law_days.setdefault(t, [])
                    if days and days[-1][0] == day:
                        days[-1] = (day, mark)
                    else:
                        days.append((day, mark))
            kind = 'start' if any(e['kind'] == 'start' for e in evs) else evs[0]['kind']
            log.append({'day': day, 'slug': ','.join(e['slug'] for e in evs), 'kind': kind, 'author': author[0],
                        'units': sum(e['units'] for e in evs), 'clamped': day < '1970-01-01', 'acts': len(evs),
                        'starts': sum(1 for e in evs if e['kind'] == 'start'),
                        'laws': sum(1 for e in evs if e['kind'] == 'law')})
        for t, days in sorted(law_days.items()):
            if len(days) == 1:
                tags[t] = days[0][1]
            else:
                for day, m in days:
                    tags[f'{t}/{day}'] = m
        for name in sorted(tags):
            fi.write(f'reset refs/tags/{name}\n'.encode('utf-8') + b'from :%d\n\n' % tags[name])
        fi.write(b'done\n')
    with open(stream_path, 'rb') as fi:
        out = subprocess.run(['git', 'fast-import', '--quiet', '--done', '--date-format=raw'], cwd=repo, stdin=fi,
                             capture_output=True)
    if out.returncode:
        raise SystemExit(f'fast-import failed: {out.stderr.decode(errors="replace")[-2000:]}')
    stream_path.unlink()
    git(repo, 'reset', '-q', '--hard', 'main')
    for p in sorted(docs.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            dest = repo / p.relative_to(docs)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(p.read_bytes())
    fill_readme(repo / 'README.md', [s_ for s_, _ in results], log, tags, today)
    for name in ('build.py', 'dkacts.py', 'dkfetch.py', 'dkparse.py', 'reproduce.py', 'check_repo.py', 'test_repo.py'):
        (repo / 'tools' / name).write_bytes((HERE / name).read_bytes())
    (repo / 'tools' / 'acts.json').write_bytes((HERE / 'acts.json').read_bytes())
    summaries = [s_ for s_, _ in results]
    write_tables(repo, summaries)
    from reproduce import write_manifest, write_reproduce
    write_manifest(repo, summaries, today)
    write_reproduce(repo, summaries, log, tags, dkfetch.REQUESTS, today)
    git(repo, 'add', '-A')
    when = commit_date(today, seq)
    env = {**os.environ, 'GIT_AUTHOR_NAME': COMMITTER[0], 'GIT_AUTHOR_EMAIL': COMMITTER[1], 'GIT_AUTHOR_DATE': when,
           'GIT_COMMITTER_NAME': COMMITTER[0], 'GIT_COMMITTER_EMAIL': COMMITTER[1], 'GIT_COMMITTER_DATE': when}
    out = subprocess.run(['git', 'commit', '-q', '--cleanup=verbatim', '-F', '-'], cwd=repo, env=env, capture_output=True,
                         input='Dokumentation, tabeller, værktøjer og REPRODUCE.md\n\nKind: documentation\n'.encode('utf-8'))
    if out.returncode:
        raise SystemExit(out.stderr.decode(errors='replace'))
    return log, tags


def fill_readme(path: Path, summaries: list[dict], log: list[dict], tags: dict, today: str):
    """The README's @@NAME@@ fields are the build's own counts, so they are right after every rebuild."""
    built = [s_ for s_ in summaries if 'error' not in s_]
    from_lbk = sum(1 for b in built if b['versions'][0]['kind'] == 'LBK')
    facts = {
        'ACTS': f'{len(built):,}', 'FROMLBK': f'{from_lbk:,}', 'FROMLOV': f'{len(built) - from_lbk:,}',
        'VERSIONS': f'{sum(len(b["versions"]) for b in built):,}',
        'LBKS': f'{sum(1 for b in built for v in b["versions"] if v["kind"] == "LBK"):,}',
        'COMMITS': f'{len(log):,}', 'FIRSTDAY': min(c['day'] for c in log), 'LASTDAY': max(c['day'] for c in log),
        'AMENDING': f'{len({c["author"] for c in log if c["kind"] == "law" and c["author"].startswith("LOV")}):,}',
        'TAGS': f'{len(tags):,}', 'LASTYEAR': max(b['act']['id'].split('/')[0] for b in built),
        'FIRSTYEAR': min(b['act']['id'].split('/')[0] for b in built), 'TODAY': today,
    }
    text = path.read_text(encoding='utf-8')
    for k, v in facts.items():
        text = text.replace(f'@@{k}@@', v)
    left = re.findall(r'@@\w+@@', text)
    if left:
        raise SystemExit(f'README fields not filled: {sorted(set(left))}')
    path.write_text(text, encoding='utf-8', newline='\n')


def write_tables(repo: Path, summaries: list[dict]):
    out = [r for s_ in summaries if 'error' not in s_ for r in s_['rows']]
    out.sort(key=lambda r: (r['ikraft'], r['lov'], r['type'] != 'LOV', r['nummer']))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(out[0]), lineterminator='\n')
    w.writeheader()
    w.writerows(out)
    (repo / 'love.csv').write_text(buf.getvalue(), encoding='utf-8', newline='\n')
    for s_ in summaries:
        if 'error' in s_:
            continue
        (repo / s_['act']['slug'] / 'README.md').write_text('\n'.join(s_['readme']) + '\n', encoding='utf-8', newline='\n')
    (repo / 'data').mkdir(exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['grund', 'aendring'])
    for s_ in summaries:
        for reason, items in sorted(s_.get('listed', {}).items()):
            for x in items:
                w.writerow([reason, x])
    (repo / 'data' / 'ikke-tilskrevet.csv').write_text(buf.getvalue(), encoding='utf-8', newline='\n')
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['dokument', 'mappe', 'fejl'])
    for s_ in summaries:
        if 'error' in s_:
            w.writerow([s_['act']['current'], s_['act']['slug'], s_['error'].split('\n')[0]])
    (repo / 'data' / 'udeladt.csv').write_text(buf.getvalue(), encoding='utf-8', newline='\n')


def data_day() -> str:
    c = dkfetch.CACHE
    files = [p for p in c.iterdir() if p.name != '.gitignore'] if c.exists() else []
    if not files:
        return dt.date.today().isoformat()
    return dt.date.fromtimestamp(max(p.stat().st_mtime for p in files)).isoformat()


def _init_worker(today):
    global TODAY
    TODAY = today


def build_all(acts: list[dict], offline: bool, workers: int) -> list[tuple[dict, list[dict]]]:
    if offline and workers > 1:
        import multiprocessing as mp
        with mp.Pool(workers, initializer=_init_worker, initargs=(TODAY,)) as pool:
            return list(pool.imap(act_worker, [(a, True) for a in acts], chunksize=2))
    return [act_worker((a, offline)) for a in acts]


def main():
    global TODAY
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=str(ROOT.parent / 'denmark-law'))
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--today', required=True)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--only', default=None, help='comma-separated act ids or folders (a partial build, for testing)')
    ap.add_argument('--verify-rebuild', action='store_true')
    args = ap.parse_args()
    TODAY = args.today
    if args.verify_rebuild:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([os.sys.executable, '-X', 'utf8', str(HERE / 'build.py'), '--offline', '--repo', tmp,
                                  '--today', args.today, '--workers', str(args.workers)]
                                 + (['--only', args.only] if args.only else []), capture_output=True, text=True)
            if out.returncode:
                raise SystemExit(out.stderr)

            def hashes(r):
                log = git(Path(r), 'log', '--format=%H', 'main').split()
                tags = dict(l.split(' ', 1)[::-1] for l in git(Path(r), 'show-ref', '--tags').split('\n') if l)
                return log, tags
            a, b = hashes(args.repo), hashes(tmp)
            rec = {'identical': a[0][1:] == b[0][1:] and a[1] == b[1], 'history_tip': a[0][1], 'commits': len(a[0]) - 1,
                   'tags': len(a[1]), 'main_identical': a[0][0] == b[0][0], 'main': a[0][0], 'rebuilt_main': b[0][0]}
            print(json.dumps(rec, indent=1))
            p = HERE / 'verification.json'
            ver = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
            ver['rebuild'] = {k: rec[k] for k in ('identical', 'history_tip', 'commits', 'tags')}
            p.write_text(json.dumps(ver, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
            for f in Path(tmp).rglob('*'):
                os.chmod(f, 0o700)
            raise SystemExit(0 if rec['identical'] else 1)
    acts = load_acts()
    if args.only:
        want = set(args.only.split(','))
        acts = [a for a in acts if a['id'] in want or a['slug'] in want]
    results = build_all(acts, args.offline, args.workers)
    ok = [r for r in results if 'error' not in r[0]]
    bad = [r[0] for r in results if 'error' in r[0]]
    print(f'{len(ok)} acts built, {len(bad)} left out; {sum(len(s_["versions"]) for s_, _ in ok)} versions, '
          f'{sum(s_["unit_changes"] for s_, _ in ok)} file changes, '
          f'{sum(len(s_["problems"]) for s_, _ in ok)} not credited to one act')
    for s_ in bad:
        print('  left out', s_['act']['id'], s_['act']['slug'], s_['error'][:200])
    if os.environ.get('DK_DRY'):
        return
    log, tags = write_repo(Path(args.repo), ok + [r for r in results if 'error' in r[0]], HERE / 'repo', args.today)
    print(f'repo: {len(log)} commits + 1 documentation commit, {len(tags)} tags -> {args.repo}')


if __name__ == '__main__':
    main()
