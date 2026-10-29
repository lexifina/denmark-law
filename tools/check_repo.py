"""Checks the git repository against the official text: every version of every act in Retsinformation, read back from git
on the day it took effect (as tools/paa_dato.py reads it), must equal that version's text.

    python -X utf8 scripts/denmark-law/check_repo.py --today 2026-10-29 [--repo ../denmark-law] [--no-record] [--workers 8]

Three checks per version, from the cached Retsinformation documents (no network):
1. File by file: the act's files in git on that day are exactly the files the build's parser makes from that version's
   HTML (same set of files, same bytes).
2. Word for word: the whole act as tools/paa_dato.py prints it, with its markdown marks removed, has the same words in the
   same order as the whole official text, read independently of the parser (every text node of the document after its
   table of contents).
3. Letters and digits: the same two texts, casefolded, with everything but letters and digits removed, are equal.
The result is written to verification.json next to this script (unless --no-record), for REPRODUCE.md.
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

from lxml import html as lhtml

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True   # it imports the repository's tools/paa_dato.py; leave no __pycache__ in the repository
sys.path.insert(0, str(HERE))
import build  # noqa: E402

TOKEN = re.compile(r'\w+|[^\w\s]')
ALNUM = re.compile(r'[^\w]|_')


def official_words(html_text: str) -> list[str]:
    """All words of the document: every text node after the 'Den fulde tekst' bar (or the whole document when the page has
    none). Footnote reference marks ('1)' in a superscript) are left out, as the build leaves them out."""
    doc = lhtml.fromstring('<div>' + html_text + '</div>')
    for e in list(doc.iter('sup', 'span', 'a')):
        cls = e.get('class') or ''
        if 'FodnoteHenvisning' in cls or ((e.tag == 'sup' or 'Superscript' in cls) and re.fullmatch(r'\s*\d+\)\s*', e.text_content())):
            e.drop_tree()
    for bar in list(doc.iter('div')):
        if 'bjelke' in (bar.get('class') or '') and 'fulde tekst' in bar.text_content().lower():
            for prev in list(bar.itersiblings(preceding=True)):
                prev.getparent().remove(prev)
            break
    for bar in list(doc.iter('div')):   # the site's section bars ('Den fulde tekst', 'Officielle noter') are not text of the law
        if 'bjelke' in (bar.get('class') or ''):
            bar.drop_tree()
    parts = []

    def text(e) -> str:
        if not isinstance(e.tag, str):
            return e.tail or ''
        gap = ' ' if e.tag in ('div', 'br', 'p', 'td', 'th', 'tr', 'table', 'li', 'ul', 'h1', 'h2', 'h3', 'h4', 'center') else ''
        return gap + (e.text or '') + ''.join(text(c) for c in e) + gap + (e.tail or '')
    parts.append(text(doc))
    return TOKEN.findall(' '.join(parts).replace(' ', ' '))


def repo_words(text: str) -> list[str]:
    lines = []
    for l in text.split('\n'):
        l = re.sub(r'^\s*#+ ', '', l)   # the build's only mark: '## ' before a heading (it writes no list marks)
        lines.append(l.replace(' | ', ' '))   # the separator between the cells of a table row
    return TOKEN.findall(' '.join(lines))


def alnum(words: list[str]) -> str:
    return ALNUM.sub('', ''.join(words).casefold())


def git(repo, *args, input=None) -> bytes:
    out = subprocess.run(['git', *args], cwd=repo, capture_output=True, input=input)
    if out.returncode:
        raise SystemExit(f'git {" ".join(args)}: {out.stderr.decode(errors="replace")}')
    return out.stdout


def history(repo: str) -> dict[str, list[tuple[str, str]]]:
    """Each act folder's commits, newest first, with their In-force day (one git log for the whole repository)."""
    out = git(repo, 'log', '--format=\x1e%H\t%(trailers:key=In-force,valueonly,separator=)', '--name-only', 'main').decode('utf-8')
    hist: dict[str, list[tuple[str, str]]] = {}
    for rec in out.split('\x1e')[1:]:
        head, _, names = rec.partition('\n')
        sha, _, day = head.partition('\t')
        day = day.strip()
        if not day:
            continue
        for slug in sorted({n.split('/', 1)[0] for n in names.split('\n') if '/' in n}):
            hist.setdefault(slug, []).append((day, sha))
    return hist


def files_at(repo: str, commit: str, slug: str) -> dict[str, str]:
    out = git(repo, 'ls-tree', '-r', commit, f'{slug}/').decode('utf-8').split('\n')
    blobs = []
    for line in out:
        if not line:
            continue
        info, f = line.split('\t', 1)
        if f.endswith('.md') and not f.endswith('/README.md'):
            blobs.append((f[len(slug) + 1:], info.split()[2]))
    if not blobs:
        return {}
    data = git(repo, 'cat-file', '--batch', input=''.join(f'{sha}\n' for _, sha in blobs).encode())
    res, pos = {}, 0
    for name, _ in blobs:
        nl = data.index(b'\n', pos)
        size = int(data[pos:nl].split()[2])
        res[name] = data[nl + 1:nl + 1 + size].decode('utf-8')
        pos = nl + 1 + size + 1
    return res


def check_act(args):
    act, repo, hist, today = args
    build.TODAY = today
    spec = importlib.util.spec_from_file_location('paa_dato', Path(repo) / 'tools' / 'paa_dato.py')
    paa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(paa)
    res = {'slug': act['slug'], 'versions': 0, 'files': 0, 'words': 0, 'bad': [], 'wbad': [], 'abad': []}
    try:
        b = build.build_act(act, offline=True)
    except BaseException as exc:
        res['skipped'] = f'{type(exc).__name__}: {exc}'[:200]
        return res
    for i, v in enumerate(b['versions']):
        day = v['from']
        expected = {f'{k}.md': u['text'] for k, u in v['units'].items()}
        commit = next((sha for d, sha in hist.get(act['slug'], []) if d <= day), '')
        if i == 0 and len(b['versions']) > 1 and b['versions'][1]['from'] == day and hist.get(act['slug']):
            # the act as passed takes effect only after its first consolidation, so both are dated that day and the
            # consolidation is the text in force on it: the act as passed is checked at its own commit, the act's first
            commit = hist[act['slug']][-1][1]
        got = files_at(repo, commit, act['slug']) if commit else {}
        res['versions'] += 1
        res['files'] += len(expected)
        if got != expected:
            diff = sorted(set(got) ^ set(expected)) or [k for k in expected if got.get(k) != expected[k]]
            res['bad'].append(f'{act["slug"]} {day}: {diff[:5]}')
        whole = ''.join(got[n] + '\n' for n in sorted(got, key=lambda n: paa.order(f'{act["slug"]}/{n}')))
        ow, rw = official_words(v['doc']['html']), repo_words(whole)
        res['words'] += len(ow)
        if ow != rw:
            i = next((i for i, (x, y) in enumerate(zip(ow, rw)) if x != y), min(len(ow), len(rw)))
            res['wbad'].append(f'{act["slug"]} {day}: official {len(ow)} vs repo {len(rw)} words; first difference at {i}: '
                               f'{" ".join(ow[max(0, i - 5):i + 5])!r} / {" ".join(rw[max(0, i - 5):i + 5])!r}')
        if alnum(ow) != alnum(rw):
            res['abad'].append(f'{act["slug"]} {day}')
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default=str(build.ROOT.parent / 'denmark-law'))
    ap.add_argument('--today', required=True)
    ap.add_argument('--no-record', action='store_true')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--only', default=None)
    args = ap.parse_args()
    build.TODAY = args.today
    acts = build.load_acts()
    if args.only:
        want = set(args.only.split(','))
        acts = [a for a in acts if a['id'] in want or a['slug'] in want]
    hist = history(args.repo)
    built = set(hist)
    acts = [a for a in acts if a['slug'] in built]
    jobs = [(a, args.repo, {a['slug']: hist[a['slug']]}, args.today) for a in acts]
    if args.workers > 1:
        import multiprocessing as mp
        with mp.Pool(args.workers) as pool:
            results = list(pool.imap(check_act, jobs, chunksize=2))
    else:
        results = [check_act(j) for j in jobs]
    versions = sum(r['versions'] for r in results)
    files = sum(r['files'] for r in results)
    nwords = sum(r['words'] for r in results)
    bad = [x for r in results for x in r['bad']]
    wbad = [x for r in results for x in r['wbad']]
    abad = [x for r in results for x in r['abad']]
    for x in bad[:30]:
        print('MISMATCH', x)
    for x in wbad[:30]:
        print('WORDS', x)
    for x in abad[:30]:
        print('LETTERS', x)
    (HERE / '.probe').mkdir(exist_ok=True)
    (HERE / '.probe' / 'check-details.json').write_text(json.dumps({'files': bad, 'words': wbad, 'letters': abad}, indent=1,
                                                                   ensure_ascii=False), encoding='utf-8')
    skipped = [r for r in results if 'skipped' in r]
    print(f'{len(results)} acts, {versions} versions checked ({files} files), {len(bad)} mismatches; {versions} versions word '
          f'for word ({nwords} words), {len(wbad)} mismatches; letters and digits {len(abad)} mismatches; '
          f'{len(skipped)} acts not re-read')
    if not args.no_record:
        p = HERE / 'verification.json'
        rec = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        rec['check'] = {'acts': len(results), 'versions': versions, 'files': files, 'mismatches': len(bad),
                        'wordcheck': versions, 'words': nwords, 'word_mismatches': len(wbad),
                        'letter_mismatches': len(abad), 'word_mismatch_list': wbad[:200], 'mismatch_list': bad[:200]}
        p.write_text(json.dumps(rec, indent=1, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    raise SystemExit(1 if bad or wbad or abad or skipped else 0)


if __name__ == '__main__':
    main()
