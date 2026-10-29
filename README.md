# Danish law, change by change

Every Danish statute in force, as a git repository: 1,432 acts (love and lovbekendtgørelser) that Retsinformation lists
as in force, from the oldest (1852) to the acts of 2025, the Constitution of 1953 among them, each with every consolidation (lovbekendtgørelse)
Retsinformation holds and the amending acts between them. Each amending act is one commit, credited to that act and dated
the day it took effect, at noon in Copenhagen. The text is the text published by Civilstyrelsen in
[Retsinformation](https://www.retsinformation.dk), in Danish.

*Dansk: [nedenfor](#dansk).*

| | |
| --- | --- |
| Acts | 1,432 (1,292 from the act as passed, 140 from their first consolidation in Retsinformation) |
| Official texts | 4,131 (each act's first text and 2,839 consolidations, each equal to Retsinformation's) |
| Commits | 12,725 law commits, from 1852-01-28 to 2026-05-20 |
| Amending acts credited | 3,974 |
| Tags | 19,131 |

## The questions, as git commands

| Question | Command |
| --- | --- |
| What did § 5 of the Tax Administration Act say on 1 January 2016? | `python tools/paa_dato.py 2016-01-01 skatteforvaltningsloven 5` |
| § 266 b of the Criminal Code on 1 January 2000 | `python tools/paa_dato.py 2000-01-01 straffeloven 266b` |
| The whole Salaried Employees Act as it stood on 1 January 2010 | `python tools/paa_dato.py 2010-01-01 funktionaerloven` |
| § 20 of the Constitution | `python tools/paa_dato.py 2000-01-01 grundloven 20` |
| Which act wrote each paragraph of § 5? | `git blame skatteforvaltningsloven/par-005.md` |
| Every change to § 5, with the act and the day | `git log --follow skatteforvaltningsloven/par-005.md` |
| Everything one amending act changed, in every act | `git show --stat lov/2023-1535` |
| What changed in one act on one day | `git show --stat skatteforvaltningsloven/2020-01-01` |
| Every amending act that changed the Criminal Code | `git log --format=%an -- straffeloven` |
| The acts and consolidations with all their dates | [`love.csv`](love.csv) |
| The consolidations (lovbekendtgørelser) | `git log --grep="(lovbekendtgørelse)"` |
| Changes more than one act could explain | `git log --grep="Candidate:"` |
| Changes whose day is not read from the act | `git log --grep="Date-note: undated"` |

## The dates, and which one we use

A Danish act has the day it was passed (`Enacted:`, the day the King or Queen signed it), the day it was published in
Lovtidende (`Published:`), and the day it took effect (`In-force:`). **Commits are dated the day the change took effect**,
at noon in Copenhagen (CET, or CEST in summer time): that is the day that decides which text applies. The day is read from
the amending act's own commencement sentence ("Loven træder i kraft den 1. januar 2020", "§ 1, nr. 3, træder i kraft den
..."), quoted in the commit. Where an act leaves the day to a minister, the day of the consolidation is used and the commit
says so (`Date-note: undated`). All three dates are in every commit message. Git cannot store a date before 1970, so the
commits for changes before 1970 (the Constitution of 5 June 1953 among them) are dated 1 January 1970, seconds apart, in
the right order, and their real day is in `In-force:`, which `tools/paa_dato.py` reads.

All acts share one history in the order their changes took effect. An amending act that changes several acts on one day is
one commit, listing each act with its provisions.

## What "author" means

The author of a commit is the act that made the change: `LOV nr 1125 af 19/11/2019` (with an address ending
`@retsinformation.invalid`, which cannot exist), so `git blame` names the act. Where a consolidation lists an executive
order among the documents it incorporates (`BEK nr ...`, for example one that moves tasks between ministries), that order
is the author of the changes it made. Retsinformation does not mark which act
changed which provision. It publishes the act as passed and each later consolidation (lovbekendtgørelse), and each
consolidation says which amending acts it incorporates and which article of each. The build reads that article in the
amending act, takes each numbered item and the provisions it names, and credits a changed provision to the act that names
it. Three further rules, each labelled in the commit: an item that says "overalt i loven" counts for every provision; a
provision whose new wording is quoted in exactly one act of the window goes to that act; and part headings that moved with
a provision go with the act that changed it.

Where more than one act names a provision, or none does, the consolidation shows only the result: such changes are
committed by `Retsinformation (Civilstyrelsen)`, say "(flere love)" in the subject and name the acts in `Candidate:`
trailers, or are labelled as explained by no amending article. They are never credited to an act on a guess. A
consolidation's own opening words, signatures and notes are committed by Retsinformation too. The committer is always
`Lexifina`.

## Where an act begins

For most acts the first commit is the act as passed, credited to the act itself. For 140 older acts Retsinformation
does not hold the act as passed; their first commit is the first consolidation it holds, which reprints the act with every
change made until then. That commit is by `Retsinformation (Civilstyrelsen)`, says "(første tekst i Retsinformation)" in its
subject, and credits no act: the history of those acts before that consolidation is not in this record.

## What is official and what is reconstructed

Retsinformation publishes the text only on the days of the consolidations. Between two consolidations several acts take
effect on different days, and no text exists for the days in between. The commits between consolidation days are therefore
reconstructed: each act's changes appear on its own in-force day, with the wording the next consolidation shows. **Only the
state of an act on a consolidation's day (the commit tagged `lbk/<year>-<number>`) and on its first day is an official text,
and it equals Retsinformation's.**

## How it is checked

`tools/check_repo.py` reads every official version of every act back from git on the day it took effect and compares it
with the official text: file by file with the text parsed from Retsinformation's HTML, and word for word with all the
letters and digits of the document, read independently of the parser. `tools/test_repo.py` checks that the commands above
work. The results are in [`REPRODUCE.md`](REPRODUCE.md).

## Files

Each act is a folder named after its short title (`straffeloven/`, `funktionaerloven/`), or after its title and number
where it has none. Each provision (§) is one file: `par-005.md` is § 5, `par-035b.md` is § 35 b; where an act prints the
same number twice (some old acts and the accession acts of 1972), the second is `par-002-dup.md`, the third
`par-002-dup2.md`; such files, and the sections after a repeat that belong to the same second run of numbers
(`par-046a-dup.md`), come after the regular sections. The headings of the parts that begin with a provision are `##` lines at the top of its file; each
paragraph (stk.) and list item is one line. `indledning.md` is the title and the opening words, `ikraft.md` the
commencement provisions of amending acts that a consolidation reprints after its last section ("Lov nr. 285 af 13. maj
1987 ... indeholder følgende ikrafttrædelsesbestemmelse: § 2. ..."; they are not provisions of the act), `slut.md` the
signatures and `noter.md` the footnotes. A section that an amending provision quotes as new wording (»§ 5 a. ...«) stays
in the file of the section that quotes it. A repealed provision stays as a file with "(Ophævet)", as Retsinformation prints it.

Each act's folder has a `README.md` listing its provisions with how often each changed. [`love.csv`](love.csv) lists every
version and amending act with its dates; [`data/versioner.json`](data/versioner.json) every document read, with its
sha256; [`data/ikke-tilskrevet.csv`](data/ikke-tilskrevet.csv) every change credited to no act, and why;
[`data/udeladt.csv`](data/udeladt.csv) any act left out because it could not be read. [`corpus.json`](corpus.json)
describes the corpus for tools that read several of Lexifina's law repositories.

## What it does not show

- Acts no longer in force, and executive orders (bekendtgørelser): the record holds the statutes Retsinformation lists as
  in force on 2026-10-29.
- Acts passed after an act's latest consolidation: Retsinformation has no consolidated text for them yet, so their changes
  wait for the next consolidation.
- The history of an act before its first text in Retsinformation (above).
- The days between consolidations as official texts (above).

The text on Retsinformation is for information; the authoritative publication is Lovtidende.

## How it is built

`tools/build.py` reads Retsinformation and writes this repository from scratch; the same data gives the same hashes. Every
step, the software, the decisions made by hand and what an AI model did are in [`REPRODUCE.md`](REPRODUCE.md).

## Licence

Statutes are not protected by copyright in Denmark (ophavsretsloven § 9), and Civilstyrelsen gives a free, non-exclusive
and unlimited right to use Retsinformation's open data. Source: Retsinformation (Civilstyrelsen), www.retsinformation.dk.
The data is not used to suggest that Civilstyrelsen supports or recommends this repository. This repository is private; the
history, commit messages, tables and tools are released under [CC0 1.0](LICENSE).

---

## Dansk

Alle danske love i kraft som git-repositorium: 1,432 love og lovbekendtgørelser, som Retsinformation viser som gældende,
fra den ældste (1852) til lovene fra 2025, Danmarks Riges Grundlov (1953) iblandt, hver med de lovbekendtgørelser, Retsinformation har, og de
ændringslove, der ligger mellem dem. Teksten er den, Civilstyrelsen udgiver i Retsinformation.

- **Hvert commit er én ændringslov**, skrevet som forfatter (`LOV nr 1125 af 19/11/2019`), så `git blame` viser, hvilken lov
  der skrev hvilket stykke. Loven udpeges af lovbekendtgørelsens oplysning om, hvilke love og hvilke paragraffer den har
  indarbejdet, og af at ændringslovens egen artikel nævner bestemmelsen. En lov, der ændrer flere love samme dag, er ét
  commit.
- **Hvert commit bærer ikrafttrædelsesdagen** (middag i København), læst i ændringslovens egen ikrafttrædelsesbestemmelse.
- **Hver paragraf er en fil**, hvert stykke en linje.
- **Kun tilstanden på en lovbekendtgørelses dag er officiel tekst**; dagene imellem er rekonstrueret og mærket.
- **Ændringer, som flere love kan forklare, tilskrives ingen af dem**; commit'et er fra Retsinformation og nævner dem alle.
- **140 ældre love begynder ved deres første lovbekendtgørelse**, fordi Retsinformation ikke har loven som vedtaget.

Teksten i Retsinformation er til orientering; Lovtidende er den autoritative udgivelse.
