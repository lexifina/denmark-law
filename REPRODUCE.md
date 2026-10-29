# How this history was made, and how to make it again

This file records exactly how the repository was built: the sources, the commands, the software, the decisions made
by hand, and what an AI model did and did not do. The build writes it, so it describes the build that made this
commit.

## Short version

```sh
git clone https://github.com/lexifina/denmark-law && cd denmark-law
pip install lxml
python -X utf8 tools/build.py --repo ../rebuilt --today 2026-10-29
git -C ../rebuilt rev-parse main        # the same hash as this repository's main
python -X utf8 tools/check_repo.py --repo ../rebuilt
python -X utf8 tools/test_repo.py --repo ../rebuilt
```

`tools/build.py` needs Python 3.12 or later with `lxml`, and git. It reads Retsinformation (or its own cache, `.cache/`
next to the script) and writes this repository into `--repo`. With the same Retsinformation data and the same `--today`
it gives the same commits with the same hashes. `data/versioner.json` lists every document it read with the sha256 of
the HTML, so a rebuild can show it read the same bytes; Retsinformation may change its pages, and then the hashes change
too.

## Sources and terms

All legal text and all information about consolidations and amending acts come from **Retsinformation**
(www.retsinformation.dk), the official legal database of Denmark, run by Civilstyrelsen. Nothing was typed in,
summarised or rewritten. The build made 0 requests:

| What | Where |
| --- | --- |
| Each document's text (HTML), title, kind, ministry, publication day | `POST https://www.retsinformation.dk/api/document/eli/lta/<year>/<number>` with body `{"isRawHtml":false}` (the call the site's own pages make) |
| The days a consolidation (lovbekendtgørelse, LBK) is valid from | `https://www.retsinformation.dk/eli/lta/<year>/<number>/dan/xml`, field `StartDate` |
| The amending acts each consolidation incorporates ("Dokumentets indarbejdede forskrifter") | `https://www.retsinformation.dk/api/document/<id>/references/1` |
| The act's list of related documents, to find its consolidations | `https://www.retsinformation.dk/api/document/<id>/timeline` |
| The statutes in force (`tools/dkacts.py`, written to `tools/acts.json`) | `https://www.retsinformation.dk/api/documentsearch?dt=10&dt=30&h=false&ps=100&page=<n>` |

1,432 acts were built. Some of the best known:

| Act | Title | Folder | Versions | In force from | Files today |
| --- | --- | --- | ---: | --- | ---: |
| LOV nr 169 af 05/06/1953 | Grundloven | `grundloven/` | 1 | 1953-06-05 to 1953-06-05 | 91 |
| LBK nr 90 af 26/02/1986 | Udlændingeloven | `udlaendingeloven/` | 35 | 1986-03-08 to 2025-10-06 | 270 |
| LBK nr 567 af 01/09/1986 | Retsplejeloven | `retsplejeloven/` | 32 | 1986-09-06 to 2025-11-14 | 1208 |
| LBK nr 607 af 06/09/1986 | Straffeloven | `straffeloven/` | 29 | 1986-09-25 to 2025-11-13 | 405 |
| LOV nr 427 af 06/06/2005 | Skatteforvaltningsloven | `skatteforvaltningsloven/` | 10 | 2005-06-08 to 2025-10-23 | 95 |
| LOV nr 470 af 12/06/2009 | Selskabsloven | `selskabsloven/` | 9 | 2009-06-13 to 2025-03-31 | 417 |

**Terms of use.** Civilstyrelsen's terms for its open data (page `https://www.retsinformation.dk/static/api.html`, shown at
`https://www.retsinformation.dk/api`) give "gratis, ikke-eksklusiv og ubegrænset brugsret" to Retsinformation's open
data: copy, distribute, publish, change, combine, use commercially and non-commercially. Statutes are not protected by
copyright (the Danish Copyright Act § 9). The conditions: do not use the data so that it looks as if Civilstyrelsen supports
or recommends the user or the user's products, and do not load the service in an unsuitable or disproportionate way. The
page speaks of a REST harvesting API (`api.retsinformation.dk`, one call per 10 seconds, 03:00-23:45) for following
changes; this build does not use it, but reads single documents, at most two requests a second in all (a pause of
0.5 seconds between the starts of two requests, at most three acts at a time), each answer cached and never asked again, `Accept-Encoding: gzip`, and the user agent `lexifina-watch/1.0 (+https://lexifina.com/watch;
corpus@lexifina.com)`. `robots.txt` names only a sitemap and allows everything. The data was retrieved on 2026-10-29.
This repository is not endorsed by Civilstyrelsen. It stays private; if it is ever published, the attribution is
"Source: Retsinformation (Civilstyrelsen), www.retsinformation.dk".

## The build, step by step

1. `python -X utf8 scripts/denmark-law/dkacts.py` in Lexifina's own repository listed the statutes in force
   (`tools/acts.json`); `python -X utf8 scripts/denmark-law/fetch_all.py --today 2026-10-29` fetched every document they need
   into the cache, resuming from it after interruptions; `python -X utf8 scripts/denmark-law/build.py --offline --today
   2026-10-29 --repo <folder>` wrote this repository from the cache, reading the acts with a pool of 8 worker processes. `tools/build.py` here is the same file as `scripts/denmark-law/build.py` there (git
   blob `a6abfada9a877592205eb64fd95c6300eee0348a`), with `tools/dkacts.py`, `tools/dkfetch.py`, `tools/dkparse.py`, `tools/reproduce.py`, `tools/check_repo.py` and
   `tools/test_repo.py`. Every later build ran with `--offline`, from the cache.
2. `python -X utf8 scripts/denmark-law/check_repo.py` read every version of each act back from this repository with
   `tools/paa_dato.py`, on the day it took effect, and compared it file by file with the official text parsed afresh
   from the cached HTML; then it compared the whole act, word for word, with all the words of the official document, read
   without the build's parser. (An act as passed that takes effect only after its first consolidation shares that
   consolidation's day; it is checked at its own commit, the act's first.) Result: `4131 versions checked (232184 files), 0 mismatches; 4131 versions word for word (41783886 words) against the whole official text, 52 mismatches`.
3. `python -X utf8 scripts/denmark-law/test_repo.py --record` ran the functional smoke test against this repository
   (6 of 6 passed):
   - pass: blame names an act: skatteforvaltningsloven/par-005.md lines by LOV nr 1125 af 19/11/2019, LOV nr 427 af 06/06/2005, LOV nr 679 af 03/06/2023, Retsinformation (Civilstyrelsen)
   - pass: text before and after an amendment: skatteforvaltningsloven/par-052.md 2019-12-31 != 2020-01-01; skatteforvaltningsloven/par-025.md 2023-12-30 != 2023-12-31; Grundloven whole and § 20
   - pass: log --follow in date order: skatteforvaltningsloven/par-005.md 9 commits; skatteforvaltningsloven/par-019.md 9 commits; skatteforvaltningsloven/par-052.md 6 commits
   - pass: tags resolve, In-force on every law commit: 19131 tags resolve; 12725 law commits carry In-force
   - pass: only the documentation commit is by Lexifina: only the documentation commit 3100e0fe6d is by Lexifina; 5199 distinct authors
   - pass: README commands run: 12 README commands ran and printed output
4. `python -X utf8 scripts/denmark-law/build.py --offline --verify-rebuild` built the repository a second time from the
   same cache into a temporary folder and compared the hashes. A second build from the same cache into an empty folder gave the same history: the last law commit was `412e90b171e6bc58cb9449af52a73a79ac12d8f9` in both, and every one of the 12725 law commits and 19131 tags had the same hash.
5. The build was run once more to write these results into this file, and the final `main` was rebuilt again in a
   temporary folder and compared hash for hash.
6. This history replaces, once, the earlier two-act history of the private GitHub repository `lexifina/denmark-law`
   (`git push -f origin main --tags`, agreed in advance); later builds are appended, never forced.

It ran with Python 3.12.10, lxml 6.1.3 and git version 2.46.0.windows.1 on Windows 11. No network service other than Retsinformation is involved.

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
- **Changes.** Consecutive versions are compared file by file. 71338 changes of a file were found.
- **Cause.** A consolidation says which amending acts it incorporates and, in its opening words, which article of each
  ("§ 2 i lov nr. 905 af 21. juni 2022"). The build reads that article in the amending act's own text, takes each numbered
  item ("1. I § 5, stk. 2, ændres ...") and the provisions its lead clause names (or whose new wording it quotes). A
  changed file is credited to an act in this order:
  1. exactly one act of the consolidation names the provision (17998 file changes);
  2. an item that says "Overalt i loven" (throughout the act), in exactly one act
     (2931);
  3. the new wording is quoted word for word in exactly one act's text
     (5166);
  4. part headings that only moved with a neighbouring provision an act changed
     (244);
  5. more than one act names (or quotes) it: credited to none, committed by the publisher with a `Candidate:` trailer per
     act (3899);
  6. otherwise, and for the consolidation's own parts (opening words, signatures, notes): no act; committed by the
     publisher and labelled (31988 provisions, plus the opening,
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
- **Commits.** One commit per amending act and per in-force day (5957 law commits, of which 1974 change no words of
  that act), one for the first version of each act (1432), 2779 for changes several acts could explain, and one per
  consolidation (2699) holding its own parts and whatever nothing explains, in the order they took effect, then one for
  this documentation. The consolidation's commit is last on its valid-from day, so the repository on that day equals the
  official text.
  - The author is the amending act, `LOV nr 1125 af 19/11/2019`, at an address ending `@retsinformation.invalid`
    (`lov-2019-1125@retsinformation.invalid`). The first version of each act is credited to the act itself.
  - Commits by `Retsinformation (Civilstyrelsen)` are the publisher's own: a consolidation's opening words, signatures and
    notes, changes no amending article explains, and changes with several candidate acts.
  - Author and committer dates are noon in Copenhagen on the day the change took effect: UTC+1, or UTC+2 in summer time
    (from the last Sunday in March to the last Sunday in October; September until 1995; none before 1980), written into
    the code because the build machine has no time-zone database. The committer is `Lexifina <denmark-law@lexifina.com>`.
    113 commit(s) are before 1970 (git cannot store such dates; they are dated 1970-01-01, seconds apart, with the
    real day in `In-force:`, which `tools/paa_dato.py` reads).
  - The message has the act's title, the provisions it inserted, changed or removed (Indsat, Ændret, Udgået), and
    the trailers `Evidence:`, `Kind:`, `Issuer:`, `Enacted:`, `Published:`, `In-force:`, `Date-note:`, `Affecting:`,
    `Source:` (the act on Retsinformation) and `Consolidated:` (the consolidation the text came from).
  - Tags: each act's days (`skatteforvaltningsloven/2020-05-19`) and each amending act (`lov/2019-1125`, or one tag per day
    where it took effect on several days) and consolidation (`lbk/2020-635`); 19131 in all.
- **Documentation commit.** Dated 2026-10-29, the day the data was retrieved, not the day of the run, so a later rebuild of
  the same data gives the same hash.

Changes with several candidate acts (credited to none):

- 3508 file changes, each listed in `data/ikke-tilskrevet.csv`
- 196 file changes, each listed in `data/ikke-tilskrevet.csv`
Changes nothing explains:

- 31988 file changes, each listed in `data/ikke-tilskrevet.csv`

## Versions whose words differ from the official text

These versions have every file the parser makes from the official HTML (check 1 passes), but read in file order
their words differ from the document's (most often the same words in another order: the files are ordered by section
number, and these documents print sections out of that order, e.g. a whole older act reprinted after the reprinted
commencement provisions, or a protocol's signatures inside an annex). The first difference of each, official words /
repository words:

- ligningsloven 2019-08-15: 52117: 'de dermed forbundne omkostninger . Skatteministeriet , den 8 .' / 'de dermed forbundne omkostninger . Installation af tyverialarm Skatteminist
- kildeskatteloven 1998-09-10: 15445: 'af skattekrav . § 62 . E . Reglerne i' / 'af skattekrav . § 62 F . I det omfang'
- kildeskatteloven 1998-10-19: 15455: 'af skattekrav . § 62 . E . Reglerne i' / 'af skattekrav . § 62 F . I det omfang'
- kildeskatteloven 1999-08-13: 15752: 'af skattekrav . § 62 . E . Reglerne i' / 'af skattekrav . § 62 F . I det omfang'
- ejendomsavancebeskatningsloven 1993-09-24: 5435: 'kunnet hos afdøde . § 14 a . Skatteministeren kan' / 'kunnet hos afdøde . § 15 . Loven træder i'
- atp-loven 1998-02-10: 11627: 'træder i kraft straks . Lov nr . 252 af' / 'træder i kraft straks . § 2 a Lov nr'
- luftfartsloven 1993-03-26: 19247: 'indeholder følgende bestemmelse : § 2 Stk . 1 .' / 'indeholder følgende bestemmelse : § 90 . Bestemmelserne i dette'
- luftfartsloven 2000-08-24: 20073: 'af Færøernes lagting . § 2 i lov nr .' / 'af Færøernes lagting . § 1 § 90 . Bestemmelserne'
- luftfartsloven 2001-06-21: 20637: 'indstilles af Færøernes lagting . § 2 i lov nr' / 'indstilles af Færøernes lagting . Kapitel 9 Befordring med luftfartøj'
- luftfartsloven 2006-01-12: 22814: 'jf . note 1 . § 2 i lov nr' / 'jf . note 1 . Befordring med luftfartøj Anvendelsesområde §'
- luftfartsloven 2011-09-16: 23323: 'indstilles af Færøernes Lagting . I lov nr . 1114' / 'indstilles af Færøernes Lagting . Anvendelsesområde § 90 . Bestemmelserne'
- boligbyggeriloven 1986-03-08: 16367: '- - - - - § 2 i lov nr' / '- - - - - Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1987-02-11: 17060: '- - - - - § 3 i lov nr' / '- - - - - Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1989-02-14: 17278: 'juni 1987 er sålydende : Stk . 1 . Loven' / 'juni 1987 er sålydende : Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1990-07-17: 17781: 'juni 1987 er sålydende : § 7 Stk . 1' / 'juni 1987 er sålydende : Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1991-09-20: 17876: 'juni 1987 er sålydende : § 7 Stk . 1' / 'juni 1987 er sålydende : Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1993-08-31: 22464: 'for Færøerne og Grønland . § § 3 og 4' / 'for Færøerne og Grønland . Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1994-06-14: 22757: 'for Færøerne og Grønland . § § 3 og 4' / 'for Færøerne og Grønland . Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1995-08-15: 21942: 'for Færøerne og Grønland . § § 3 og 4' / 'for Færøerne og Grønland . Kapitel VII Rentesikring og garanti'
- boligbyggeriloven 1996-08-09: 23089: 'Færøerne og Grønland . § § 3 og 4 i' / 'Færøerne og Grønland . § 43 . Til almennyttige boligselskabers'
- udlaendingeloven 1994-11-08: 11917: 'eller grønlandske forhold tilsiger . Lov nr . 574 af' / 'eller grønlandske forhold tilsiger . § 2 § 3 §'
- udlaendingeloven 1995-07-14: 4694: '. 1 eller 2 . Kapitel 6 Forskellige regler om' / '. 1 eller 2 . § 29 a . En'
- udlaendingeloven 1997-01-31: 15530: 'eller grønlandske forhold tilsiger . Lov nr . 574 af' / 'eller grønlandske forhold tilsiger . § 2 § 3 §'
- udlaendingeloven 1997-08-22: 17223: 'eller grønlandske forhold tilsiger . Lov nr . 574 af' / 'eller grønlandske forhold tilsiger . § 1 § 2 §'
- udlaendingeloven 2000-07-03: 21301: 'eller grønlandske forhold tilsiger . Lov nr . 574 af' / 'eller grønlandske forhold tilsiger . § 1 § 2 §'
- udlaendingeloven 2002-07-25: 27294: 'eller grønlandske forhold tilsiger . Lov nr . 574 af' / 'eller grønlandske forhold tilsiger . § 1 Lov nr .'
- byggeloven 1986-12-18: 2705: 'eller lignende anlæg . § 16 . A . Kommunalbestyrelsen' / 'eller lignende anlæg . § 17 . Det påhviler den'
- pensionsloven 1987-10-09: 8203: '- - - - § § 2 og 3 i' / '- - - - § 19 . § § 2'
- pensionsloven 2001-07-05: 10474: 'for Færøerne og Grønland . § 3 i lov nr' / 'for Færøerne og Grønland . Kapitel 1 Almindelige betingelser mv'
- vaegtafgiftsloven 1988-10-25: 4942: '6 affattes således : § 6 . Afgiftsperioden er 12' / '6 affattes således : § 2 Loven træder i kraft'
- registreringsafgiftsloven 1994-07-26: 6572: 'for Færøerne og Grønland . Skatteministeriet , den 13 .' / 'for Færøerne og Grønland . § 7 . Afgiften af'
- sygedagpengeloven 2000-03-13: 6960: '. ) indeholder følgende ikrafttrædelsesbestemmelse : § 6 Loven træder' / '. ) indeholder følgende ikrafttrædelsesbestemmelse § 6 Loven træder i
- lov-om-indfoedsrets-meddelelse-1990-222 1990-04-06: 41: 'Lov om indfødsrets meddelelse § 1 . Indfødsret meddeles :' / 'Lov om indfødsrets meddelelse § 2 . Endvidere meddeles indfødsret'
- kreditaftaleloven 1990-06-14: 6488: "OMKOSTNINGERNES VÆRDI K = m A K = K '" / "OMKOSTNINGERNES VÆRDI K = m AK = K ' ="
- planloven 2007-07-12: 1276: 'forventede lokaløkonomiske effekt . Kapitel 2 b ( Ophævet )' / 'forventede lokaløkonomiske effekt . Kapitel 3 Regional udviklingsplanlægning § 
- planloven 2008-10-28: 1196: 'forventede lokaløkonomiske effekt . Kapitel 2 b ( Ophævet )' / 'forventede lokaløkonomiske effekt . Kapitel 3 Regional udviklingsplanlægning § 
- planloven 2015-12-02: 21300: 'for Færøerne og Grønland . Lov nr . 9 af' / 'for Færøerne og Grønland . ( Ophævet ) Lov nr'
- planloven 2015-12-15: 21134: 'for Færøerne og Grønland . Lov nr . 9 af' / 'for Færøerne og Grønland . ( Ophævet ) Lov nr'
- lov-om-indfoedsrets-meddelelse-1996-354 1996-05-10: 47: '. Indfødsret meddeles : § 1 . Indfødsret meddeles :' / '. Indfødsret meddeles : § 2 . Endvidere meddeles indfødsret'
- forskelsbehandlingsloven 2005-01-24: 1912: 'for Færøerne og Grønland . Lov nr . 253 af' / 'for Færøerne og Grønland . På Rådets vegne É .'
- lov-om-indfoedsrets-meddelelse-1996-475 1996-06-13: 47: '. Indfødsret meddeles : § 1 . Indfødsret meddeles :' / '. Indfødsret meddeles : § 2 . Endvidere meddeles indfødsret'
- lov-om-indfoedsrets-meddelelse-1996-1053 1996-12-12: 41: 'Lov om indfødsrets meddelelse § 1 . Indfødsret meddeles :' / 'Lov om indfødsrets meddelelse § 2 . Endvidere meddeles indfødsret'
- konkurrenceloven 2000-07-20: 7156: '§ 9 indsættes : § 10 . På vare -' / '§ 9 indsættes : § 29 . Loven gælder ikke'
- konkurrenceloven 2002-07-08: 7574: '§ 9 indsættes : § 10 . På vare -' / '§ 9 indsættes : § 29 . Loven gælder ikke'
- lov-om-indfoedsrets-meddelelse-1997-419 1997-06-11: 41: 'Lov om indfødsrets meddelelse § 1 . Indfødsret meddeles :' / 'Lov om indfødsrets meddelelse § 2 . Endvidere meddeles indfødsret'
- deltidsloven 2001-06-08: 948: 'for Færøerne og Grønland . Givet på Christiansborg Slot ,' / 'for Færøerne og Grønland . § 7 § 1 §'
- deltidsloven 2002-10-10: 1178: 'for Færøerne og Grønland . Lov nr . 433 af' / 'for Færøerne og Grønland . § 7 § 1 §'
- se-loven 2004-10-08: 2955: 'for Færøerne og Grønland . Givet på Amalienborg , den' / 'for Færøerne og Grønland . Udfærdiget i Luxembourg , den'
- lov-om-hold-af-dyr 2017-01-14: 7918: 'i klagen anførte klagepunkter . Kapitel 13 a Obligatorisk digital' / 'i klagen anførte klagepunkter . § 66 b . Miljø'
- sce-loven 2006-08-18: 3132: 'for Færøerne og Grønland . Givet på Christiansborg Slot ,' / 'for Færøerne og Grønland . På Rådets vegne G .'
- lov-om-bruxelles-i-forordningen-m-v 2006-12-21: 19010: '21 . august 2002 . På Kommissionens vegne António VITORINO' / '21 . august 2002 . EFT L 12 af 16'
- lov-om-miljoe-og-foedevareklagenaevnet 2017-02-01: 1430: 'er formandens stemme udslagsgivende . Kapitel 4 Nævnets prøvelse §' / 'er formandens stemme udslagsgivende . § 10 b . Udbetaling'

## Decisions made by hand

1. **The acts.** Every statute Retsinformation's own search lists as in force (document types LOV and LBK, `h=false`), by
   its current document: the act as passed when it was never consolidated (LOVH), else its latest consolidation (LBKH).
   Each act's timeline gives the act as passed and every consolidation. Where Retsinformation does not hold the act as
   passed (140 acts, mostly from before 1985), the act starts from its first consolidation, committed by the
   publisher and labelled; the record of such an act begins there. Where the search lists two current documents for one
   act, it is built once. Amending acts are not acts of their own here; they are the authors of the changes. The
   Constitution (Danmarks Riges Grundlov, lov nr. 169 af 5. juni 1953) has no amendment and no consolidation; it is one
   commit. Executive orders (bekendtgørelser) are not in this build.
   Acts left out because their documents could not be read:
   - none
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
   "§ 5. E Aktiver ..." after § 5 and there is no § 5 E yet, it is the misprint of "§ 5 E." and is `par-005e.md`.
8. **Days Retsinformation did not set.** For consolidations from before the database (published before 1999),
   Retsinformation's valid-from day is the day it loaded the document (1997-09-24/25, 1997-10-01, 1998-03-15, 1999-07-27,
   ...), years after publication. Where it is more than 60 days after the day of publication (more than 14 days when it is
   1997-09-24, 1997-09-25 or 1998-03-15, the days of the big loads), the day of publication is
   used and the commit says so (`Date-note: load-day`, with the day Retsinformation gives). Where the site cannot serve a
   document's XML (HTTP 500 on four tries, recorded in the cache), there is no valid-from day and the day of publication
   is used (`Date-note: undated`).
9. **Old page layouts.** Documents from before about 2000 keep list items in `<LI>` elements and some paragraphs as text
   directly in a `<div>`; each such element is a line, as a `<p>` is.

## What an AI model did

This repository was built in **Claude Code**, Anthropic's coding tool: first for two acts by the model **Claude Sonnet
5.5** (model id `claude-sonnet-5-5`), then extended to every statute in force and finished on 2026-10-29 by **Claude Opus 5.5**
(`claude-opus-5-5`), working from briefs by the user at Lexifina: a private "git for law" repository for Denmark to the
same standard as Lexifina's other corpora.

The model:

- **Researched the source:** Retsinformation's documents, its API calls (found in the site's own JavaScript), its terms of
  use, and prior art (below).
- **Wrote all the code and text in this repository:** `tools/build.py`, `tools/dkacts.py`, `tools/dkparse.py`, `tools/dkfetch.py`,
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
