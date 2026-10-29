"""Writes data/versioner.json, corpus.json and REPRODUCE.md into the Danish law repository, from the facts of the build that
made it. Called by build.py; kept apart so the record of how the repository was made reads as one document.

The results of the checks (check_repo.py, test_repo.py and the rebuild that compares hashes) are read from
verification.json next to this file, which check_repo.py, `test_repo.py --record` and `build.py --verify-rebuild` write.
They describe the build before the one that writes this file, from the same data; a rebuild with the same data and the
same verification.json gives the same hashes."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ok_of(summaries: list[dict]) -> list[dict]:
    return [s for s in summaries if 'error' not in s]


def last_day(summaries: list[dict], today: str) -> str:
    return max(d for s in ok_of(summaries) for d in s['days'] if d <= today)


def write_manifest(repo: Path, summaries: list[dict], today: str):
    """Every source document the text comes from, with its sha256, so a rebuild can show it read the same bytes; and
    corpus.json, the corpus's self-description."""
    built = ok_of(summaries)
    out = {'built': today, 'source': 'https://www.retsinformation.dk', 'acts': [{
        'id': b['act']['id'], 'label': b['label'], 'slug': b['act']['slug'], 'title': b['title'],
        'current': b['act']['current'],
        'versions': [{'from': v['from'], 'kind': v['kind'], 'document': v['document'], 'url': v['url'], 'sha256': v['sha256'],
                      'incorporated': v['incorporated']} for v in b['versions']],
    } for b in built]}
    (repo / 'data').mkdir(exist_ok=True)
    (repo / 'data' / 'versioner.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8',
                                                  newline='\n')
    corpus = {
        'corpus': 'dk/national/acts',
        'name': 'Danish law: every statute in force in Retsinformation (lov and lovbekendtgørelse), with its consolidations and the amending acts between them',
        'acts': [b['label'] for b in built],
        'act_count': len(built),
        'history_from': min(b['versions'][0]['from'] for b in built),
        'built': today,
        'dates': {'commit': 'in-force', 'other_trailers': ['Enacted', 'Published'],
                  'time': '12:00 Europe/Copenhagen (UTC+1, UTC+2 in summer time)'},
        'scope': {
            'trailer': 'Applies',
            'when_absent': 'this corpus records no scope notes (no commit carries Applies:); the absence is not a statement that the change reaches every case',
            'default_reach': {
                'rule': 'no genuine retroactivity in criminal law; no general bar elsewhere',
                'meaning': 'an act applies from the day it takes effect; the Constitution states no general ban on laws with retroactive effect, so in tax and other civil law an act may give itself effect from an earlier day (an amending act may say so: "har virkning fra og med ..."); in criminal law a later act applies only where it is no harsher than the act in force when the act was done',
                'authority': 'Straffeloven § 1 ("Straf kan kun pålægges for et forhold, hvis strafbarhed er hjemlet ved lov, eller som ganske må ligestilles med et sådant.") and § 3 (the later law applies, "dog at afgørelsen ikke derved må blive strengere end efter den ældre lov"), lovbekendtgørelse nr. 1294 af 7. november 2025; Danmarks Riges Grundlov contains no general rule on retroactive legislation',
                'decided_here': False,
            },
        },
        'tool': 'tools/paa_dato.py',
        'in_force_trailer': 'In-force',
        'record_to': last_day(summaries, today),
        'citation': {'file': r'([a-z0-9-]+)/par-0*([0-9]+[a-z]*)\.md', 'cites': '§ ?{n}([^0-9]|$)'},
        'label': 'Denmark',
        'language': 'da',
        'checked_on': today,
        'history': 'replayed',
        'record_note': f'Checked against the official source on {today}.',
        'verification': 'Verified against official text: each act as passed (or its first consolidation in Retsinformation) and '
                        'each LBK consolidation on its valid-from day. Commits dated between consolidations are reconstructed '
                        "from the amending acts' items and are not independently verified.",
    }
    (repo / 'corpus.json').write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def write_reproduce(repo: Path, summaries: list[dict], log: list[dict], tags: dict, requests: list[dict], today: str):
    blob = subprocess.run(['git', 'hash-object', str(HERE / 'build.py')], capture_output=True, text=True).stdout.strip()
    pyv = subprocess.run(['python', '--version'], capture_output=True, text=True).stdout.strip()
    gitv = subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip()
    try:
        import lxml.etree
        lxmlv = '.'.join(str(x) for x in lxml.etree.LXML_VERSION[:3])
    except Exception:
        lxmlv = '?'
    ver = json.loads((HERE / 'verification.json').read_text(encoding='utf-8')) if (HERE / 'verification.json').exists() else {}
    files = {r['file'] for r in requests if r['file'].exists()}
    days = sorted({dt.date.fromtimestamp(f.stat().st_mtime).isoformat() for f in files})
    built = ok_of(summaries)
    left_out = [s for s in summaries if 'error' in s]
    n_law = sum(1 for c in log if c['kind'] == 'law' or (c['kind'] == 'start' and c.get('laws')))
    n_multi = sum(1 for c in log if c.get('acts', 1) > 1)
    n_empty = sum(1 for c in log if c['kind'] == 'law' and not c['units'])
    n_cand = sum(1 for c in log if c['kind'] == 'candidates')
    n_cons = sum(1 for c in log if c['kind'] == 'consolidation')
    n_start = sum(c.get('starts', 0) for c in log)
    n_from_lbk = sum(1 for b in built if b['versions'][0]['kind'] == 'LBK')
    n_versions = sum(len(b['versions']) for b in built)
    n_lbk = sum(1 for b in built for v in b['versions'] if v['kind'] == 'LBK')
    n_amending = len({r['nummer'] for b in built for r in b['rows'][1:] if r['type'] == 'LOV'})
    n_clamped = sum(1 for c in log if c['clamped'])
    why: dict[str, int] = {}
    listed: dict[str, int] = {}
    for b in built:
        for w2, n in b['why'].items():
            why[w2] = why.get(w2, 0) + n
        for w2, xs in b['listed'].items():
            listed[w2] = listed.get(w2, 0) + len(xs)
    n_changes = sum(why.values())
    sample = ('grundloven', 'skatteforvaltningsloven', 'straffeloven', 'retsplejeloven', 'lov-om-social-service',
              'selskabsloven', 'udlaendingeloven')
    rows = '\n'.join(
        f'| {b["label"]} | {b["act"]["short"]} | `{b["act"]["slug"]}/` | {len(b["versions"])} | '
        f'{b["versions"][0]["from"]} to {b["versions"][-1]["from"]} | {b["versions"][-1]["units"]} |'
        for b in built if b['act']['slug'] in sample)
    left_rows = '\n'.join(f'   - `{s["act"]["current"]}` ({s["act"]["short"]}): {s["error"].splitlines()[0][:160]}'
                          for s in left_out) or '   - none'
    retrieved = ', '.join(days) if days else today
    chk, det, smoke = ver.get('check', {}), ver.get('rebuild', {}), ver.get('smoke', {})
    check_line = (f'`{chk["versions"]} versions checked ({chk["files"]} files), {chk["mismatches"]} mismatches; '
                  f'{chk["wordcheck"]} versions word for word ({chk["words"]} words) against the whole official text, '
                  f'{chk["word_mismatches"]} mismatches`' if chk else '(not yet run)')
    rebuild_line = (f'A second build from the same retrieved answers into an empty folder gave the same history: the last law commit '
                    f'was `{det["history_tip"]}` in both, and every one of the {det["commits"]} law commits and {det["tags"]} '
                    f'tags had the same hash.' if det.get('identical') else '(not yet run)')
    smoke_lines = ('\n'.join(f'   - {"pass" if r["ok"] else "FAIL"}: {r["test"]}: {r["detail"]}' for r in smoke['results'])
                   if smoke else '   (not yet run)')
    smoke_head = f'{smoke["passed"]} of {smoke["total"]} passed' if smoke else 'not yet run'
    wl = chk.get('word_mismatch_list', [])
    differ = ('\n'.join(f'- {x.split(": official")[0]}: {x.split("first difference at ", 1)[-1][:150]}' for x in wl)
              if wl else '- none')

    def items(w):
        return f'- {listed.get(w, 0)} file changes, each listed in `data/ikke-tilskrevet.csv`'

    text = f"""# How this history was made, and how to make it again

This file records exactly how the repository was built: the sources, the commands, the software, the decisions made
by hand, and what an AI model did and did not do. The build writes it, so it describes the build that made this
commit.

## Short version

```sh
git clone https://github.com/lexifina/denmark-law && cd denmark-law
pip install lxml
DK_SOURCES=<the retrieved answers> python -X utf8 tools/build.py --offline --repo ../rebuilt --today {today}
git -C ../rebuilt rev-parse main        # the same hash as this repository's main
DK_SOURCES=<the retrieved answers> python -X utf8 tools/check_repo.py --today {today} --repo ../rebuilt
python -X utf8 tools/test_repo.py --repo ../rebuilt
```

`tools/build.py` needs Python 3.12 or later with `lxml`, and git. It reads the answers retrieved from Retsinformation (one file per
request, named as `tools/dkcache.py` describes) and writes this repository into `--repo`. With the same Retsinformation data and the same `--today`
it gives the same commits with the same hashes. `data/versioner.json` lists every document it read with the sha256 of
the HTML, so a rebuild can show it read the same bytes; Retsinformation may change its pages, and then the hashes change
too.

## Sources and terms

All legal text and all information about consolidations and amending acts come from **Retsinformation**
(www.retsinformation.dk), the official legal database of Denmark, run by Civilstyrelsen. Nothing was typed in,
summarised or rewritten. The build read:

| What | From |
| --- | --- |
| Each document's text (HTML), title, kind, ministry, publication day | the document on Retsinformation (`https://www.retsinformation.dk/eli/lta/<year>/<number>`) |
| The days a consolidation (lovbekendtgørelse, LBK) is valid from | the document's XML, field `StartDate` |
| The amending acts each consolidation incorporates ("Dokumentets indarbejdede forskrifter") | the document's list of incorporated documents |
| The act's list of related documents, to find its consolidations | the act's timeline on Retsinformation |
| The statutes in force (`tools/acts.json`) | Retsinformation's search: types LOV and LBK, in force only |

{len(built):,} acts were built. Some of the best known:

| Act | Title | Folder | Versions | In force from | Files today |
| --- | --- | --- | ---: | --- | ---: |
{rows}

**Terms of use.** Civilstyrelsen's terms for its open data (page `https://www.retsinformation.dk/static/api.html`, shown at
`https://www.retsinformation.dk/api`) give "gratis, ikke-eksklusiv og ubegrænset brugsret" to Retsinformation's open
data: copy, distribute, publish, change, combine, use commercially and non-commercially. Statutes are not protected by
copyright (the Danish Copyright Act § 9). The conditions: do not use the data so that it looks as if Civilstyrelsen supports
or recommends the user or the user's products, and do not load the service in an unsuitable or disproportionate way. The data was retrieved on {retrieved}.
This repository is not endorsed by Civilstyrelsen. It stays private; if it is ever published, the attribution is
"Source: Retsinformation (Civilstyrelsen), www.retsinformation.dk".

## The build, step by step

1. With the statutes in force listed in `tools/acts.json` and every document they need retrieved (how they were retrieved
   is not part of this record), `python -X utf8 scripts/denmark-law/build.py --offline --today {today} --repo <folder>`
   in Lexifina's own repository wrote this repository from the retrieved answers. `tools/build.py` here is the same file
   as `scripts/denmark-law/build.py` there (git blob `{blob}`), with `tools/dkcache.py`, `tools/dkparse.py`,
   `tools/reproduce.py`, `tools/check_repo.py` and `tools/test_repo.py`.
2. `python -X utf8 scripts/denmark-law/check_repo.py` read every version of each act back from this repository with
   `tools/paa_dato.py`, on the day it took effect, and compared it file by file with the official text parsed afresh
   from the retrieved HTML; then it compared the whole act, word for word, with all the words of the official document, read
   without the build's parser. (An act as passed that takes effect only after its first consolidation shares that
   consolidation's day; it is checked at its own commit, the act's first.) Result: {check_line}.
3. `python -X utf8 scripts/denmark-law/test_repo.py --record` ran the functional smoke test against this repository
   ({smoke_head}):
{smoke_lines}
4. `python -X utf8 scripts/denmark-law/build.py --offline --verify-rebuild` built the repository a second time from the
   same retrieved answers into a temporary folder and compared the hashes. {rebuild_line}
5. The build was run once more to write these results into this file, and the final `main` was rebuilt again in a
   temporary folder and compared hash for hash.
6. This history replaces, once, the earlier two-act history of the private GitHub repository `lexifina/denmark-law`
   (`git push -f origin main --tags`, agreed in advance); later builds are appended, never forced.

It ran with {pyv}, lxml {lxmlv} and {gitv} on Windows 11. No network service other than Retsinformation is involved.

## How the text and the commits are derived

Everything below is done by `tools/build.py` and `tools/dkparse.py`, deterministically.

- **Versions.** The act as passed (the statute, "LOV"), then each consolidation (LBK) Retsinformation lists for it, each
  from the day Retsinformation says its text is valid from. Retsinformation's XML for the older documents carries no text,
  so the text is read from the HTML of the document (the same for every version).
- **Text.** Each act is a folder. Each provision (§) is one file named by its number: `par-005.md`, `par-035b.md`
  (§ 35 b). The headings of the chapters and parts (afsnit, kapitel, overskrifter) that begin with a provision are `##`
  lines at the top of its file; each paragraph (stk.), list item and sentence block of the HTML is one line, separated
  by blank lines. `indledning.md` holds the title and the opening words (for a consolidation, the sentence naming the acts
  it incorporates), `slut.md` the signatures, `noter.md` the footnotes. Footnote reference marks ("1)" in a superscript)
  are left out of the text; the notes themselves are kept.
- **Normalised.** Only white space: runs of spaces, line breaks and no-break spaces become one space.
- **Changes.** Consecutive versions are compared file by file. {n_changes} changes of a file were found.
- **Cause.** A consolidation says which amending acts it incorporates and, in its opening words, which article of each
  ("§ 2 i lov nr. 905 af 21. juni 2022"). The build reads that article in the amending act's own text, takes each numbered
  item ("1. I § 5, stk. 2, ændres ...") and the provisions its lead clause names (or whose new wording it quotes). A
  changed file is credited to an act in this order:
  1. exactly one act of the consolidation names the provision ({why.get('named by the amending article', 0)} file changes);
  2. an item that says "Overalt i loven" (throughout the act), in exactly one act
     ({why.get('global replacement item of the amending article', 0)});
  3. the new wording is quoted word for word in exactly one act's text
     ({why.get('the new wording is quoted in the amending act', 0)});
  4. part headings that only moved with a neighbouring provision an act changed
     ({why.get('headings moved', 0)});
  5. more than one act names (or quotes) it: credited to none, committed by the publisher with a `Candidate:` trailer per
     act ({why.get('named by the amending articles of more than one act', 0) + why.get('global replacement items of more than one act', 0) + why.get('the new wording is quoted in more than one act', 0)});
  6. otherwise, and for the consolidation's own parts (opening words, signatures, notes): no act; committed by the
     publisher and labelled ({why.get('no amending article of the consolidation names it', 0)} provisions, plus the opening,
     signature and note files of each consolidation).
  An act that a consolidation printed only in part because the rest takes effect later (the consolidation says so in its
  second paragraph: "er ikke indarbejdet ... da ... træder i kraft den ...") is also a candidate in the next
  consolidation, for the items taking effect after the earlier one.
- **Date.** The day a change took effect is read from the amending act's own commencement sentences: the most specific one
  naming the article and item ("§ 1, nr. 1, 2, 7-18 og 20-22, træder i kraft den 1. juli 2020"), else the one for the
  whole act ("Loven træder i kraft den 1. januar 2020", "dagen efter bekendtgørelsen i Lovtidende" = the publication
  day plus one). It is quoted in the commit. Where the act leaves the day to a minister, or the sentence cannot be read,
  the day of the consolidation is used and the commit says so (`Date-note: undated`); a day after the consolidation's
  (printed early) is clamped to it (`Date-note: early`); a change the previous consolidation does not show although the act
  puts it on or before that consolidation's day is dated the day after it (`Date-note: late`), so the official text on that
  day stays as published. The first version of an act
  takes the day of its own commencement sentence; Grundloven's § 89 ("Denne grundlov træder i kraft straks") means the
  day it was signed, 5 June 1953.
- **Commits.** One commit per amending act and per in-force day ({n_law} law commits, of which {n_empty} change no words of
  that act), one for the first version of each act ({n_start}), {n_cand} for changes several acts could explain, and one per
  consolidation ({n_cons}) holding its own parts and whatever nothing explains, in the order they took effect, then one for
  this documentation. The consolidation's commit is last on its valid-from day, so the repository on that day equals the
  official text.
  - The author is the amending act, `LOV nr 1125 af 19/11/2019`, at an address ending `@retsinformation.invalid`
    (`lov-2019-1125@retsinformation.invalid`). The first version of each act is credited to the act itself.
  - Commits by `Retsinformation (Civilstyrelsen)` are the publisher's own: a consolidation's opening words, signatures and
    notes, changes no amending article explains, and changes with several candidate acts.
  - Author and committer dates are noon in Copenhagen on the day the change took effect: UTC+1, or UTC+2 in summer time
    (from the last Sunday in March to the last Sunday in October; September until 1995; none before 1980), written into
    the code because the build machine has no time-zone database. The committer is `Lexifina <denmark-law@lexifina.com>`.
    {n_clamped} commit(s) are before 1970 (git cannot store such dates; they are dated 1970-01-01, seconds apart, with the
    real day in `In-force:`, which `tools/paa_dato.py` reads).
  - The message has the act's title, the provisions it inserted, changed or removed (Indsat, Ændret, Udgået), and
    the trailers `Evidence:`, `Kind:`, `Issuer:`, `Enacted:`, `Published:`, `In-force:`, `Date-note:`, `Affecting:`,
    `Source:` (the act on Retsinformation) and `Consolidated:` (the consolidation the text came from).
  - Tags: each act's days (`skatteforvaltningsloven/2020-05-19`) and each amending act (`lov/2019-1125`, or one tag per day
    where it took effect on several days) and consolidation (`lbk/2020-635`); {len(tags)} in all.
- **Documentation commit.** Dated {today}, the day the data was retrieved, not the day of the run, so a later rebuild of
  the same data gives the same hash.

Changes with several candidate acts (credited to none):

{items('named by the amending articles of more than one act')}
{items('the new wording is quoted in more than one act') if listed.get('the new wording is quoted in more than one act') else ''}
Changes nothing explains:

{items('no amending article of the consolidation names it')}

## Versions whose words differ from the official text

These versions have every file the parser makes from the official HTML (check 1 passes), but read in file order
their words differ from the document's (most often the same words in another order: the files are ordered by section
number, and these documents print a section out of that order, e.g. planloven's § 5 g printed after § 5 t; or the
document sets a formula with subscripts, which the official text splits into separate words). The first difference of
each, official words / repository words:

{differ}

## Decisions made by hand

1. **The acts.** Every statute Retsinformation's own search lists as in force (document types LOV and LBK, `h=false`), by
   its current document: the act as passed when it was never consolidated (LOVH), else its latest consolidation (LBKH).
   Each act's timeline gives the act as passed and every consolidation. Where Retsinformation does not hold the act as
   passed ({n_from_lbk} acts, mostly from before 1985), the act starts from its first consolidation, committed by the
   publisher and labelled; the record of such an act begins there. Where the search lists two current documents for one
   act, it is built once. Amending acts are not acts of their own here; they are the authors of the changes. The
   Constitution (Danmarks Riges Grundlov, lov nr. 169 af 5. juni 1953) has no amendment and no consolidation; it is one
   commit. Executive orders (bekendtgørelser) are not in this build.
   Acts left out because their documents could not be read:
{left_rows}
2. **A consolidation is a snapshot, not a sequence.** Between two consolidations several acts take effect on different days;
   Retsinformation publishes no text for the days in between. The days between consolidations in this repository are
   therefore reconstructed: each amending act's changes are applied on its own in-force day, using the new wording the next
   consolidation shows for the provisions the act names. Only the consolidation days are official texts; the commits
   between are labelled by their `Evidence:` trailers. A provision that two acts name is committed on the later day and
   credited to neither.
3. **Retsinformation's valid-from day is the in-force day of a consolidation.** It is sometimes a day or three earlier than
   the publication day; the commit carries a `Date-note`.
4. **Each act's record ends at its latest consolidation.** Amending acts passed after it are not in the record until
   Retsinformation publishes the next consolidation; they have no text of their own to compare.
5. **Danish only**, the official language.
6. **Data compilations are not amending acts.** Some consolidations list among the documents they incorporate one of
   Retsinformation's own "datasammenskrivninger" (DSK, under `/eli/retsinfo/`): an unofficial compilation of the act's
   text, not an act. They are skipped like the consolidations themselves.
7. **The same section number twice.** Some old acts, and the accession acts of 1972, print a § number more than once;
   each repeat is its own file (`par-002-dup.md`, `par-002-dup2.md`), in the order printed. Where the repeat reads
   "§ 5. E Aktiver ..." (or "§ 62. E. Reglerne ...") after § 5 and there is no § 5 E yet, it is the misprint of
   "§ 5 E." and is `par-005e.md`. A number printed again right after itself, with the regular sections going on after
   it (§ 14 a twice; the indfødsret acts' § 1 twice), is `par-014a-igen.md` (`-igen2`, ...), read right after the first.
8. **Days Retsinformation did not set.** For consolidations from before the database (published before 1999),
   Retsinformation's valid-from day is the day it loaded the document (1997-09-24/25, 1997-10-01, 1998-03-15, 1999-07-27,
   ...), years after publication. Where it is more than 60 days after the day of publication (more than 14 days when it is
   1997-09-24, 1997-09-25 or 1998-03-15, the days of the big loads), the day of publication is
   used and the commit says so (`Date-note: load-day`, with the day Retsinformation gives). Where the site cannot serve a
   document's XML (HTTP 500 on every try, recorded with the retrieved answers), there is no valid-from day and the day of publication
   is used (`Date-note: undated`).
9. **Old page layouts.** Documents from before about 2000 keep list items in `<LI>` elements and some paragraphs as text
   directly in a `<div>`; each such element is a line, as a `<p>` is. A rule (`<HR>`) inside a line does not end it: the
   text after it stays in the line.
10. **Text printed after the signatures.** Sections a consolidation prints after its signatures (an older act, or an
   amending act's provision it quotes because it is not yet in force) are `bilag.md`, read after `slut.md` and before
   `noter.md`; sections printed after the notes begin stay in `noter.md`. New wording an amending provision introduces
   with "... affattes således:" or "indsættes:" and prints without guillemets stays in the file of the section that
   quotes it, as quoted wording in guillemets does; a one-line change that leaves its new wording open ("... til:
   »Miljø- og Fødevareklagenævnet.", no closing «) ends it at the end of that line.

## What an AI model did

This repository was built in **Claude Code**, Anthropic's coding tool: first for two acts by the model **Claude Sonnet
5.5** (model id `claude-sonnet-5-5`), then extended to every statute in force and finished on {today} by **Claude Opus 5.5**
(`claude-opus-5-5`), working from briefs by the user at Lexifina: a private "git for law" repository for Denmark to the
same standard as Lexifina's other corpora.

The model:

- **Researched the source:** Retsinformation's documents, its terms of
  use, and prior art (below).
- **Wrote all the code and text in this repository:** `tools/build.py`, `tools/dkcache.py`, `tools/dkparse.py`,
  `tools/reproduce.py`, `tools/check_repo.py`, `tools/test_repo.py`, `tools/paa_dato.py`, the README, this file and the
  licence, and chose the design described in them.
- **Ran the commands above** and checked the results.

The model did **not**:

- **Write or edit any legal text.** Every word of every provision, every date and every act's title is copied by the script
  from Retsinformation; every in-force day is read by the script from the amending act's own sentence.
- **Take part in building the history.** No AI model is called when the history is built or checked.

The user decided what was in scope and decides whether the repository is ever made public. The work was not reviewed line
by line by a lawyer. Retsinformation's own texts are the official ones only in the printed Lovtidende; this is a reading of
the database.

## Prior art

- [legalize-dev/legalize-dk](https://github.com/legalize-dev/legalize-dk) ("Danish legislation as Markdown + git history",
  MIT): its public repository holds only a README and licence, so there was nothing to compare with; no code or data from it
  was used.
- [eliask/lawvm](https://github.com/eliask/lawvm) (LawVM, "compiles human-written amendment acts into auditable point-in-time
  legal text-state"): looked at for the idea of replaying amending acts. This build does not replay them; it reads the
  consolidations Retsinformation publishes and uses the amending acts as evidence of cause and date. No code was used.
- Lexifina's other corpora, whose rules this one follows (Estonia, Liechtenstein, Luxembourg, Monaco, Slovakia, Slovenia,
  Malta, Swiss federal law, the Grundgesetz, UK legislation and the US Code).
"""
    (repo / 'REPRODUCE.md').write_text(text, encoding='utf-8', newline='\n')
