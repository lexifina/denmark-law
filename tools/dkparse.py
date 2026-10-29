"""Reads Retsinformation's document HTML into provisions, and reads amending acts for what they amend and when."""
from __future__ import annotations

import datetime as dt
import re

from lxml import html as lhtml

WS = re.compile(r'[\s ​]+')
BLOCKS = ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'pre', 'strong')
LEAF = ('li', 'div', 'center', 'blockquote', 'dd', 'dt')
SECT = '§'
LQ = '»'   # the opening guillemet of quoted new wording


def clean(s: str) -> str:
    return WS.sub(' ', s).strip()


def _blockish(e) -> bool:
    return isinstance(e.tag, str) and (e.tag in BLOCKS + LEAF or any(
        isinstance(x.tag, str) and x.tag in BLOCKS + LEAF for x in e.iterdescendants()))


def wrap_loose(doc):
    """Old documents leave text loose between blocks (`<BR> § 1. <P CLASS=STK>...`). In a container that is not itself a
    block but holds blocks, each run of loose text and inline elements between two blocks becomes a <p> of its own, in
    place, so it is read as a line. Blocks are read whole, so text inside them is untouched."""
    def loose(e) -> bool:
        return bool(clean(e.text or '')) or any(
            clean(c.tail or '') or (not _blockish(c) and isinstance(c.tag, str) and clean(c.text_content())) for c in e)
    for el in [e for e in doc.iter() if isinstance(e.tag, str) and e.tag not in BLOCKS and len(e)
               and any(_blockish(c) for c in e) and loose(e)]:
        kids = list(el)
        runs, run, text0 = [], [], el.text
        el.text = None
        for c in kids:
            if _blockish(c):
                runs.append(run)
                run = []
                runs.append(c)
            else:
                run.append(c)
        runs.append(run)
        for c in kids:
            el.remove(c)
        lead = text0
        for r in runs:
            if not isinstance(r, list):
                el.append(r)
                lead = r.tail
                r.tail = None
                continue
            text = (lead or '') + ''.join(lhtml.tostring(c, encoding='unicode', with_tail=True) if isinstance(c.tag, str)
                                          else (c.tail or '') for c in r)
            lead = None
            if clean(lhtml.fromstring('<div>' + text + '</div>').text_content()):
                p = lhtml.fromstring('<div><p>' + text + '</p></div>')[0]
                el.append(p)


def lines_of(raw_html: str) -> list[tuple[str, str]]:
    """The document body as (css class, text) blocks in order: everything after the 'Den fulde tekst' bar (the table of
    contents before it is skipped). Nested blocks count once."""
    doc = lhtml.fromstring('<div>' + raw_html + '</div>')
    # Footnote reference marks ('1)' in a superscript or a note link) are not part of the text.
    for e in list(doc.iter('sup', 'span', 'a')):
        cls = (e.get('class') or '')
        if 'FodnoteHenvisning' in cls or ((e.tag == 'sup' or 'Superscript' in cls) and re.fullmatch(r'\s*\d+\)\s*', e.text_content())):
            e.drop_tree()
    for br in doc.iter('br'):   # a line break separates words ('P.M.V<br />Jakob Møller Nielsen')
        br.tail = ' ' + (br.tail or '')
    wrap_loose(doc)
    has_bar = any('bjelke' in (x.get('class') or '') and 'fulde tekst' in clean(x.text_content()).lower() for x in doc.iter('div'))
    started = not has_bar
    out: list[tuple[str, str]] = []
    seen = set()
    for e in doc.iter():
        if not isinstance(e.tag, str):
            continue
        if e.tag == 'div' and 'bjelke' in (e.get('class') or '') and 'fulde tekst' in clean(e.text_content()).lower():
            started = True
            continue
        if not started or e.tag not in BLOCKS + LEAF:
            continue
        if any(a in seen for a in e.iterancestors()):
            continue
        # A container is a block only when it holds no block itself: a list item in old documents (<LI>1) indregistrerede
        # aktieselskaber,</LI>), or a <div> holding text directly (<p class="Tekst2"><div>kan renteudgifter ...</div>).
        if e.tag in LEAF and ('bjelke' in (e.get('class') or '') or any(
                isinstance(x.tag, str) and x.tag in BLOCKS + LEAF for x in e.iterdescendants())):
            continue
        seen.add(e)
        if e.tag == 'tr':
            cells = [clean(td.text_content()) for td in e if isinstance(td.tag, str) and td.tag in ('td', 'th')]
            text = ' | '.join(c for c in cells if c)
        else:
            text = clean(e.text_content())
        if text:
            out.append(((e.get('class') or '').strip(), text))
    return out


LETTER_TYPO = re.compile(r'^' + SECT + r'\s*(\d+)\s*\.\s*([A-Z])\s+[A-ZÆØÅ]')
# 'Lov nr. 285 af 13. maj 1987 om ændring af ... indeholder følgende ikrafttrædelsesbestemmelse:' (old documents, no class)
# also 'Lov nr. ... har følgende ikrafttrædelsesbestemmelse:', '§ 3 i lov nr. 296 af ... 1987 er sålydende:',
# 'Lov nr. ... indeholder følgende ikrafttrædelses- og overgangsregler:'
REPRINT = re.compile(r'^(Lov(bekendtgørelse)?|§§?\s*\d+[^:]{0,30}?\bi\s+lov)\s+nr\.\s*\d+.*(\bfølgende\b.{0,80}?(bestemmelse|regler)|\ber sålydende).{0,40}:\s*$',
                     re.S)
# The same introduction at the end of a line (old documents run it on after the last section's text: '§ 20. Loven
# gælder ikke for Færøerne og Grønland. § 2 i lov nr. 486 af 5. november 1980 er sålydende:'), ending in ':' or '.'
# and perhaps note marks ('(* 5).').
INTRO_END = re.compile(
    r'\bnr\.\s*\d+\b[^:]{0,300}?(\b(indeholder|har)\b[^:]{0,40}?\bfølgende\b[^:]{0,120}?(bestemmelse|regler)[^:.]{0,80}?'
    r'|\ber sålydende\s*)[:.]?(\s*\(\*\s*\d+\))*\s*[:.]\s*$')
BARE = re.compile(r'^' + SECT + r'\s*(\d+)\s*([A-Za-z]?)\s*\.?\s*$')
SECTION = re.compile(r'^' + SECT + r'\s*(\d+)\s*([A-Za-z]?)\s*\.\s*(.*)$', re.S)


def sec_key(num: str, suf: str) -> str:
    return f'par-{int(num):03d}{suf.lower()}'


def is_heading(cls: str, text: str) -> bool:
    c = cls.lower()
    if 'overskrift' in c or c.startswith('ktitle') or c in ('kapitelnummer', 'afsnitsnummer', 'afsnit', 'kapitel', 'bognummer', 'bog', 'tekstoverskrift'):
        return True
    return bool(re.fullmatch(r'(kapitel|afsnit|bog|del)\s+[0-9ivxlc]+[a-z]?\.?', text, re.I)) and c not in ('paragraf', 'stk')


def is_note(cls: str) -> bool:
    c = cls.lower()
    return 'fodnote' in c or 'slutnote' in c


def is_closing(cls: str) -> bool:
    c = cls.lower()
    return c in ('givet', 'sign', 'segl', 'hymne') or c.startswith(('under', 'givet', 'sign'))


def read_units(raw_html: str, track_quotes: bool = True) -> dict:
    """One version as units in order: 'indledning' (title and opening words), each provision (with the headings that
    begin with it), 'slut' (signatures) and 'noter' (footnotes). Each unit has its lines and its text."""
    units: dict[str, dict] = {}
    order: list[str] = []
    pending: list[str] = []
    cur: dict | None = None
    state = 'open'

    def unit(key, label, kind_):
        if key in units:
            raise SystemExit(f'duplicate unit {key}')
        u = {'key': key, 'label': label, 'kind': kind_, 'lines': []}
        units[key] = u
        order.append(key)
        return u

    opening = None
    intro_end = False
    run, top = 0, (0, 0, '', '')   # a second run of section numbers, and the highest section of the first
    depth = 0   # open » quotations: new wording an amending provision quotes ('»Kapitel 5 a ... § 68 f. ...«')
    for cls, text in lines_of(raw_html):
        quoted = track_quotes and depth > 0
        depth = max(0, depth + text.count(LQ) - text.count('«'))
        after_intro, intro_end = intro_end, False
        if state == 'body' and 'slut' not in units and not quoted and not is_heading(cls, text) \
                and not REPRINT.match(text) and INTRO_END.search(text):
            intro_end = True   # this line ends with the introduction: the reprinted provisions begin with the next one
        if state == 'body' and 'slut' not in units and not is_closing(cls) and not is_note(cls) and (
                after_intro or cls.lower() == 'ikrafttekst' or (not is_heading(cls, text) and REPRINT.match(text))):
            state = 'ikraft'   # the amending acts' own provisions, reprinted by a consolidation after its last section
            if 'ikraft' not in units:
                unit('ikraft', 'Ændringslovenes ikrafttrædelsesbestemmelser', 'ikraft')
        if state == 'ikraft' and (is_closing(cls) or is_note(cls)):
            state = 'body'   # the signature (or the notes) ends the reprinted provisions; the rest goes on as before
        if state == 'ikraft':
            units['ikraft']['lines'] += [f'## {h}' for h in pending] + [text]
            pending = []
            continue
        # a section quoted as new wording by an amending provision (»§ 68 f. ...«) is text of the section quoting it
        m = None if (quoted and state == 'body' and cur is not None) else SECTION.match(text)
        if not m and not quoted and cls.lower() in ('', 'parab', 'paragraf'):
            m = BARE.match(text)   # old documents: '§ 1.' alone, without a class (loose or in <pre>), or '§ 5' without the period
            if m:
                cls = cls or 'paragraf'
        elif m and not cls and BARE.match(text):
            cls = 'paragraf'
        if m and cls.lower().startswith(('paragraf', 'parab')) and 'overskrift' not in cls.lower():
            key = sec_key(m.group(1), m.group(2))
            label = f'{SECT} {int(m.group(1))}{(" " + m.group(2)) if m.group(2) else ""}'
            m2 = LETTER_TYPO.match(text)
            if key in units and m2 and not m.group(2) and sec_key(m2.group(1), m2.group(2)) not in units:
                # '§ 5. E Aktiver ...' after § 5: a misprint of '§ 5 E. Aktiver ...'
                key = sec_key(m2.group(1), m2.group(2))
                label = f'{SECT} {int(m2.group(1))} {m2.group(2)}'
            if key in units or (run and unit_order(key) < top):
                # the same § number again (old acts, EU accession acts): -dup, then -dup2, -dup3, ... A repeat starts a
                # second run of numbers; a later section of that run whose own number sorts before the first run's last
                # (§ 46 a after a second § 46) belongs to the run too, so the files keep the printed order.
                base, n = key, 1
                key = base + '-dup'
                while key in units:
                    n += 1
                    key = f'{base}-dup{n}'
                run = max(run, n)
            elif not run:
                top = max(top, unit_order(key))
            cur = unit(key, label, 'paragraf')
            cur['lines'] = [f'## {h}' for h in pending] + [text]
            pending = []
            state = 'body'
            continue
        if is_heading(cls, text):
            pending.append(text)
            continue
        if is_note(cls):
            if 'noter' not in units:
                if pending and cur is not None:
                    cur['lines'] += [f'## {h}' for h in pending]
                    pending = []
                unit('noter', 'Noter', 'noter')
            units['noter']['lines'].append(text)
            continue
        if 'noter' in units:   # after the notes begin, the rest is notes too (e.g. a <strong>Slutnoter</strong> heading)
            units['noter']['lines'] += [f'## {h}' for h in pending] + [text]
            pending = []
            continue
        if state == 'open':
            if opening is None:
                opening = unit('indledning', 'Indledning', 'indledning')
            opening['lines'] += [f'## {h}' for h in pending] + [text]
            pending = []
        elif is_closing(cls) or 'slut' in units or text.startswith('Så er da nu gældende ret'):
            if 'slut' not in units:
                unit('slut', 'Slutning', 'slut')
            units['slut']['lines'] += [f'## {h}' for h in pending] + [text]
            pending = []
        else:
            if pending:
                cur['lines'] += [f'## {h}' for h in pending]
                pending = []
            cur['lines'].append(text)
    if track_quotes and depth > 0:   # a quotation never closed: read the document again without following quotations
        return read_units(raw_html, track_quotes=False)
    if pending and order:   # headings with nothing after them (an annex title at the very end): kept in the last unit
        units[order[-1]]['lines'] += [f'## {h}' for h in pending]
    for k in order:
        units[k]['text'] = '\n\n'.join(units[k]['lines']) + '\n'
    return {'units': units, 'order': order}


def unit_order(key: str) -> tuple:
    if key == 'indledning':
        return (0, 0, '', '')
    m = re.fullmatch(r'par-(\d+)([a-z]*)(.*)', key)
    if m and m.group(3).startswith('-dup'):
        # a number printed again: in a consolidation, the amending acts' own sections reprinted after the last section
        # ("Lov nr. 285 af 13. maj 1987 ... § 2. Loven træder i kraft ..."), act by act: by repeat, then by number
        return (2, int(m.group(3)[4:] or 1), int(m.group(1)), f'{len(m.group(2)):02d}{m.group(2)}')
    if m:
        return (1, int(m.group(1)), f'{len(m.group(2)):02d}{m.group(2)}', m.group(3))
    if key == 'ikraft':
        return (3, 0, '', '')
    if key == 'slut':
        return (4, 0, '', '')
    if key == 'noter':
        return (5, 0, '', '')
    return (6, 0, key, '')


# ---------------------------------------------------------------- dates

MONTHS = {'januar': 1, 'februar': 2, 'marts': 3, 'april': 4, 'maj': 5, 'juni': 6, 'juli': 7, 'august': 8,
          'september': 9, 'oktober': 10, 'november': 11, 'december': 12}
DAY = re.compile(r'(\d{1,2})\.\s*(' + '|'.join(MONTHS) + r')\s+(\d{4})', re.I)


def danish_day(s: str) -> str | None:
    m = DAY.search(s)
    return f'{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}' if m else None


def long_day(day: str) -> str:
    y, mo, d = day.split('-')
    return f'{int(d)}. {list(MONTHS)[int(mo) - 1]} {y}'


def num_set(s: str) -> set[int]:
    """'1, 2, 7-18 og 20-22' -> {1, 2, 7..18, 20..22}."""
    out: set[int] = set()
    for a, b in re.findall(r'(\d+)\s*(?:[-–]\s*(\d+))?', s):
        out |= set(range(int(a), int(b or a) + 1))
    return out


# ---------------------------------------------------------------- amending acts

def articles(lines: list[tuple[str, str]]) -> dict[int, list[str]]:
    """An act's articles: number -> its text lines (the article line first). The articles of an amending act are its
    top-level paragraphs: a centred '§ 1' heading when the act has them (quoted new wording is then in ordinary
    paragraph classes), else the paragraph lines '§ 1. ...'. Quoted wording that begins with a guillemet is not one."""
    centred = [c for c, _ in lines if c.lower().startswith(('centreret', 'cparagrafnummer'))]
    out: dict[int, list[str]] = {}
    cur = None
    for cls, text in lines:
        cl = cls.lower()
        if centred:
            m = re.fullmatch(SECT + r'\s*(\d+)\s*', text) if cl.startswith(('centreret', 'cparagrafnummer')) else None
        else:
            m = SECTION.match(text) if cl.startswith('paragraf') and 'overskrift' not in cl else None
            if m and m.group(2):
                m = None
        if m:
            cur = int(m.group(1))
            if cur in out:
                cur = None
                continue
            out[cur] = [text]
        elif cur is not None and not is_note(cls):
            out[cur].append(text)
    return out


NUM = r'\d+\s*(?:[A-Za-z](?![A-Za-z]))?(?:\s*[-–]\s*\d*\s*(?:[A-Za-z](?![A-Za-z]))?)?'
CONT = r'\d+(?![\d.])\s*(?:[A-Za-z](?![A-Za-z]))?(?:\s*[-–]\s*\d*\s*(?:[A-Za-z](?![A-Za-z]))?)?'
SECS = re.compile(SECT + SECT + r'?\s*(' + NUM + r'(?:\s*(?:,|og|samt)\s*' + CONT + r')*)')
ONE = re.compile(r'(\d+)\s*([A-Za-z](?![A-Za-z]))?(?:\s*[-–]\s*(\d*)\s*([A-Za-z](?![A-Za-z]))?)?')


def sections_in(lead: str) -> set[str]:
    """Provision keys a clause names: '§ 5', '§§ 5 og 6', '§§ 5-7', '§ 5 a', '§ 5 a-c'."""
    keys: set[str] = set()
    for m in SECS.finditer(lead):
        for a, s1, b, s2 in ONE.findall(m.group(1)):
            s1, s2 = s1 or '', s2 or ''
            if b and not s2:
                for n in range(int(a), int(b) + 1):
                    keys.add(sec_key(str(n), ''))
            elif s1 and s2 and not b:
                for c in range(ord(s1.lower()), ord(s2.lower()) + 1):
                    keys.add(sec_key(a, chr(c)))
            else:
                keys.add(sec_key(a, s1))
    return keys


ITEM = re.compile(r'^(\d+)\.\s+(.*)$', re.S)
LEAD_STOP = re.compile(r'[»“]|\b(?:affattes|ophæves|udgår|indsættes|ændres|bliver|erstattes|tilføjes|nyaffattes)\b')
QUOTED_SEC = re.compile(LQ + r'\s*(' + SECT + r'\s*\d+\s*[A-Za-z]?\s*\.)')
NEW_SEC = re.compile(r'^' + LQ + r'?\s*(' + SECT + r'\s*\d+\s*[A-Za-z]?\s*\.)')
GLOBAL = re.compile(r'\b(?:Overalt i loven|I hele loven|Overalt i lovens tekst)\b', re.I)


def items_of(article: list[str]) -> dict[int, set[str]]:
    """The numbered items of an amending article ('1. I § 5, stk. 2, ændres ...') and the provisions each names: those in
    the lead clause before the new wording, and those the new wording opens with ('»§ 5 a. ...')."""
    out: dict[int, set[str]] = {}
    cur = None
    for line in article[1:]:
        m = ITEM.match(line)
        if m:
            cur = int(m.group(1))
            body = m.group(2)
            lead = LEAD_STOP.split(body, 1)[0]
            out.setdefault(cur, set()).update(sections_in(lead))
            if GLOBAL.search(lead):
                out[cur].add('*')
            for q in QUOTED_SEC.findall(body):
                out[cur] |= sections_in(q)
        elif cur is not None:
            for q in QUOTED_SEC.findall(line) + NEW_SEC.findall(line):
                out[cur] |= sections_in(q)
    return out


COMMENCE = re.compile(r'^(.*?)\s*,?\s*træder\s+i\s+kraft\s*(.*)$', re.I | re.S)
MINISTER = re.compile(r'^(?:Tidspunktet\s+for\s+ikrafttrædelsen\s+af\s+(.*?)\s+fastsættes\s+af\s+\w+\.?|'
                      r'\w+\s+fastsætter\s+tidspunktet\s+for\s+(?:ikrafttrædelsen\s+af\s+)?(.*?)\.?)$', re.I)
SEG = re.compile(SECT + SECT + r'?\s*(\d[\d\s,og\-–]*?)(?:,?\s*nr\.\s*([\d\s,og\-–]+?))?(?:,?\s*stk\.\s*[\d\s,og\-–]+)?\s*,?\s*$')


def refs_of(scope: str) -> list[tuple[set[int], set[int] | None]] | None:
    """'§ 1, nr. 1-8 og 11, § 3, nr. 1, og § 7' -> [({1}, {1..8, 11}), ({3}, {1}), ({7}, None)]; None if the scope is not
    made of such references ('Loven' is handled by the caller)."""
    text = scope.replace(SECT + SECT, SECT)
    if 'denne lovs' in text:
        text = text.split('denne lovs', 1)[1]
    text = re.sub(r'^\s*(Lovens|lovens)\s+', '', text.strip())
    segs = [x for x in re.split(r'(?:,\s*)?(?:og\s+)?(?=' + SECT + r')', text) if x.strip()]
    out = []
    for sg in segs:
        m = SEG.match(sg.strip())
        if not m:
            return None
        out.append((num_set(m.group(1)), num_set(m.group(2)) if m.group(2) else None))
    return out or None


def commencement(arts: dict[int, list[str]], article: int | None, item: int | None,
                 published: str | None) -> tuple[str | None, str]:
    """The day the part of an amending act that amends our law took effect, read from the act's own commencement
    sentences ('Loven træder i kraft ...', '§ 1, nr. 3, træder i kraft ...', 'Skatteministeren fastsætter tidspunktet
    ...'). The most specific sentence naming the article (and item) wins, else the sentence for the whole act. Returns
    (day or None when the act leaves it to a minister or the sentence gives no day, the sentence it was read from)."""
    default = None
    whole_art = None
    hit = None
    for n in sorted(arts):
        for line in arts[n]:
            if line.startswith(LQ):
                continue
            for sent in re.split(r'(?<=[a-zæøå0-9])\.\s+(?=[A-ZÆØÅ' + SECT + r'])', line):
                sent = re.sub(r'^(' + SECT + r'\s*\d+\.\s*)?(Stk\.\s*\d+\s*\.\s*)?', '', sent.strip())
                mm = MINISTER.match(sent)
                if mm:
                    what = mm.group(1) or mm.group(2) or ''
                    day = None
                    if re.fullmatch(r'(lovens\s+ikrafttræden|loven)(,?\s*jf\. dog.*)?', what.strip(), re.I) or not what.strip():
                        default = (None, sent)
                    else:
                        r = refs_of(what)
                        if r and article is not None and any(article in a and (i is None or (item is not None and item in i)) for a, i in r):
                            hit = (None, sent)
                    continue
                m = COMMENCE.match(sent)
                if not m:
                    continue
                scope, rest = m.group(1).strip(' ,'), m.group(2)
                day = danish_day(rest)
                if day is None and re.search(r'dagen efter (?:bekendtg|offentliggør)', rest, re.I) and published:
                    day = (dt.date.fromisoformat(published) + dt.timedelta(days=1)).isoformat()
                if re.fullmatch(r'(Loven|Denne lov)', scope, re.I):
                    default = (day, sent)
                    continue
                r = refs_of(scope)
                if r and article is not None:
                    for a, i in r:
                        if article in a:
                            if i is None:
                                whole_art = (day, sent)
                            elif item is not None and item in i:
                                hit = (day, sent)
    return hit or whole_art or default or (None, '')
