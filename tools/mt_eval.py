"""Score one chapter's English against another chapter's English.

    python tools/mt_eval.py reference.json candidate.json

Both files are what the editor's **Download translations** button writes: a
`{"pages": [{"name": ..., "regions": [{"id", "order", "kind", "japanese",
"english", "speaker"}]}]}` object. The first is the run you are measuring
AGAINST - normally the AI run you already accepted - and the second is the run
you are measuring.

WHY THIS EXISTS. Choosing a translator by reading a page of it is how you end
up with the answer you went in with. It was written to compare an OFFLINE
translator against the AI (see the note the same day), and the four things it
counts are the four that separated them:

    chrF                a rough character-level agreement, per box kind.
                        Two good translations of one line disagree, so this
                        is a similarity and NEVER a score out of a hundred.
    names               one katakana run, how many English spellings. A
                        translator with no glossary spells a name freshly
                        every time it meets it, and often twice in a chapter.
    honorifics          -san / -sama kept where the Japanese has one, which
                        is a setting the app has and a sentence model has not.
    who                 the person an English pronoun names, where the
                        Japanese supplies no pronoun at all. Japanese drops
                        the subject; English cannot. Somebody has to decide,
                        and with one box to look at the decision is a guess.

The last three are the mechanical ones - a machine can see them, and a human
has to fix every one it gets wrong. What no counter here reaches is whether
the line is any good, which is what a person reading the page is for.

Nothing is imported from the package, so this runs on a bare Python.
"""
import collections
import json
import re
import sys
import unicodedata

HON = re.compile(r"-(san|sama|chan|kun|dono|senpai|sensei)\b", re.I)
JA_HON = ("さん", "様", "ちゃん", "くん", "君", "殿", "先生")
PRON = re.compile(r"\b(I|me|my|mine|you|your|yours|he|him|his|she|her|hers|"
                  r"they|them|their|we|us|our|ours)\b", re.I)
JA_PRON = ("俺", "僕", "私", "わたし", "わたくし", "あたし", "君", "お前",
           "あなた", "彼", "彼女", "自分", "うち", "我々", "拙者")
KATA = re.compile(r"[ァ-ヶ][ァ-ヶー]{1,}")


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for p in d.get("pages", []):
        for r in p.get("regions", []):
            out["%s#%s" % (p.get("name", "?"), r.get("id"))] = dict(
                kind=r.get("kind") or "", ja=r.get("japanese") or "",
                en=r.get("english") or "", speaker=r.get("speaker"))
    return out


# ------------------------------------------------------------------ chrF

def _grams(s, n):
    # Whitespace out entirely, which is what sacrebleu's chrF does by default
    # and the reason this agrees with it to the fifth decimal. Where a line
    # breaks inside a balloon is the typesetter's business, not the
    # translator's, so it must not count for or against anybody.
    s = re.sub(r"\s+", "", s)
    return collections.Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf(hyps, refs, order=6, beta=2.0):
    """chrF with the usual 6 character orders, averaged over the corpus.

    Written out rather than imported so this file needs nothing installed.
    Matches sacrebleu's corpus_chrf to within a tenth on the sets it was
    checked against, which is all the precision anything here deserves.
    """
    tp = [0] * order
    hl = [0] * order
    rl = [0] * order
    for h, r in zip(hyps, refs):
        for n in range(1, order + 1):
            gh, gr = _grams(h, n), _grams(r, n)
            tp[n - 1] += sum((gh & gr).values())
            hl[n - 1] += sum(gh.values())
            rl[n - 1] += sum(gr.values())
    ps = [tp[i] / hl[i] for i in range(order) if hl[i]]
    rs = [tp[i] / rl[i] for i in range(order) if rl[i]]
    if not ps or not rs:
        return 0.0
    p, r = sum(ps) / len(ps), sum(rs) / len(rs)
    if p + r == 0:
        return 0.0
    b2 = beta * beta
    return 100.0 * (1 + b2) * p * r / (b2 * p + r)


# ------------------------------------------------------------------ names

# Capitalised words that are just the start of a sentence. Without this the
# name columns fill up with Right, Lady, These - and a false spelling is worse
# than a missed one here, because the whole point of the column is to be read.
COMMON = set("""A An And As At But Because By Do Does Even For From He Her Here
His How I If In Is It Its Just Let Lets Me My No Not Now Of Oh Ok On One Or
Our Out Please Right Say She So That The Their Them Then There These They This
Those To Too Um Up Us We Well What When Where Which Who Why Will With Would
Yes You Your Yeah Yeah Ah Eh Hey Hmm Huh Lady Lord Sir Miss Mr Mrs Ms Queen
King Saint Time Take Look Get Got Give Come Go Going Stop Wait Only Still Also
Maybe Sorry Thanks Thank Sure Okay Fine Good Great Man Boss Master Father
Mother Sister Brother Everyone Someone Something Nothing Anything""".split())


def _romanish(word, kana):
    """Could `word` be somebody's attempt at romanising `kana`?

    Deliberately loose - the point is to catch Eeda beside Ada, not to
    transliterate. It asks that the first sound roughly agree and the length
    be in the same neighbourhood, which is enough to separate a name from the
    ordinary capitalised word that opens a sentence.

    The vowels are one class, not five. エーダ is rendered Ada by a person who
    is naming a character and Eeda by a machine reading the kana, and a table
    that calls those two different names has missed the only thing it is for.
    """
    word = re.sub(r"[’']s$", "", word)
    if word in COMMON or not word:
        return False
    first = {"ア": "aeiou", "エ": "aeiou", "イ": "aeiou", "オ": "aeiou",
             "ウ": "aeiou",
             "カ": "k", "キ": "k", "ク": "k", "ケ": "k", "コ": "k",
             "サ": "s", "シ": "s", "ス": "s", "セ": "s", "ソ": "s",
             "タ": "t", "チ": "ct", "ツ": "t", "テ": "t", "ト": "t",
             "ナ": "n", "ニ": "n", "ヌ": "n", "ネ": "n", "ノ": "n",
             "ハ": "h", "ヒ": "h", "フ": "fh", "ヘ": "h", "ホ": "h",
             "マ": "m", "ミ": "m", "ム": "m", "メ": "m", "モ": "m",
             "ヤ": "y", "ユ": "y", "ヨ": "y",
             "ラ": "rl", "リ": "rl", "ル": "rl", "レ": "rl", "ロ": "rl",
             "ワ": "w", "ヲ": "w", "ガ": "g", "ギ": "g", "グ": "g",
             "ゲ": "g", "ゴ": "g", "ザ": "z", "ジ": "jz", "ズ": "z",
             "ゼ": "z", "ゾ": "z", "ダ": "d", "ヂ": "d", "デ": "d",
             "ド": "d", "バ": "b", "ビ": "b", "ブ": "b", "ベ": "b",
             "ボ": "b", "パ": "p", "ピ": "p", "プ": "p", "ペ": "p",
             "ポ": "p"}
    w = word.lower()
    if not w or not kana:
        return False
    ok = first.get(kana[0], "")
    if ok and w[0] not in ok:
        return False
    return abs(len(w) - len(kana)) <= 4


def name_table(ref, cand):
    """Every katakana run of two or more, and what each side called it."""
    runs = collections.Counter()
    for k, v in ref.items():
        for m in KATA.findall(v["ja"]):
            runs[m] += 1
    rows = []
    for kana, n in runs.most_common():
        if n < 2:                       # one sighting cannot drift
            continue
        got = {}
        for side, book in (("ref", ref), ("cand", cand)):
            spell = collections.Counter()
            for k, v in book.items():
                if kana not in (ref.get(k) or v)["ja"]:
                    continue
                for w in re.findall(r"\b[A-Z][a-zA-Z'’-]{1,}\b", v["en"]):
                    base = w.split("-")[0]
                    if _romanish(base, kana):
                        spell[base] += 1
            got[side] = spell
        rows.append((kana, n, got["ref"], got["cand"]))
    return rows


# ------------------------------------------------------------------- who

def person(t):
    m = set(w.lower() for w in PRON.findall(t))
    who = set()
    if m & {"i", "me", "my", "mine"}:
        who.add("1s")
    if m & {"you", "your", "yours"}:
        who.add("2")
    if m & {"he", "him", "his", "she", "her", "hers", "they", "them",
            "their"}:
        who.add("3")
    if m & {"we", "us", "our", "ours"}:
        who.add("1p")
    return who


# ------------------------------------------------------------------ main

def report(ref, cand):
    keys = [k for k in ref if k in cand and ref[k]["en"] and cand[k]["en"]]
    if not keys:
        print("no box has an English line on both sides")
        return
    print("boxes compared            %d of %d" % (len(keys), len(ref)))
    fam = lambda k: ("sfx" if ref[k]["kind"].startswith("sfx") else "text")
    print()
    print("CHARACTER AGREEMENT (chrF - a similarity, not a mark)")
    for want in ("*", "text", "sfx"):
        ks = [k for k in keys if want == "*" or fam(k) == want]
        if ks:
            print("  %-10s %5.1f   (n=%d)" % (
                "all" if want == "*" else want,
                chrf([cand[k]["en"] for k in ks], [ref[k]["en"] for k in ks]),
                len(ks)))
    same = sum(1 for k in keys
               if cand[k]["en"].strip().lower() == ref[k]["en"].strip().lower())
    print("  word for word %d" % same)

    print()
    print("ONE NAME, HOW MANY SPELLINGS")
    drift = 0
    for kana, n, a, b in name_table(
            {k: ref[k] for k in keys}, {k: cand[k] for k in keys}):
        if not a and not b:
            continue
        f = lambda c: (", ".join("%s x%d" % (w, v) for w, v in c.most_common(4))
                       or "-")
        flag = "  <-- two spellings" if len(b) > 1 else ""
        drift += 1 if len(b) > 1 else 0
        print("  %-8s seen %2d   reference: %-22s candidate: %s%s" % (
            kana, n, f(a), f(b), flag))
    print("  names the candidate spells more than one way: %d" % drift)

    print()
    print("HONORIFICS")
    ja = [k for k in keys if any(h in ref[k]["ja"] for h in JA_HON)]
    print("  japanese lines with one   %d" % len(ja))
    print("  kept by the reference     %d" % sum(1 for k in ja if HON.search(ref[k]["en"])))
    print("  kept by the candidate     %d" % sum(1 for k in ja if HON.search(cand[k]["en"])))

    print()
    print("WHO, WHERE THE JAPANESE DOES NOT SAY")
    noja = [k for k in keys if not any(p in ref[k]["ja"] for p in JA_PRON)]
    both = [k for k in noja if person(ref[k]["en"]) and person(cand[k]["en"])]
    dis = [k for k in both if person(ref[k]["en"]) != person(cand[k]["en"])]
    print("  no pronoun in the japanese %d" % len(noja))
    print("  both sides named somebody  %d" % len(both))
    print("  ...and they disagree       %d" % len(dis))
    for k in dis[:12]:
        print("     %-12s %-24s" % (k, " ".join(ref[k]["ja"].split())[:24]))
        print("        reference: %s" % " ".join(ref[k]["en"].split())[:70])
        print("        candidate: %s" % " ".join(cand[k]["en"].split())[:70])


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    report(load(argv[1]), load(argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
