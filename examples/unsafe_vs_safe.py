"""Show why the obvious reordering is wrong and what altrank does instead.

    python examples/unsafe_vs_safe.py

Sorting rules by how often they win is the natural thing to try.  It is also
incorrect: a hot general rule jumps ahead of the specific rules it shadows and
the lexer starts producing different tokens.  altrank keeps the orderings that
matter and reorders everything else.
"""

import glob
import os
import sys
import sysconfig

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pygments.lexers.python import PythonLexer

from altrank import optimize, profile

NL_SEP = chr(10)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

FILES = 6


def load_corpus():
    stdlib = sysconfig.get_paths()["stdlib"]
    paths = sorted(glob.glob(os.path.join(stdlib, "*.py")))[:FILES]
    return "\n".join(open(p, encoding="utf-8", errors="replace").read()
                     for p in paths)


def frequency_sorted_table(corpus):
    """Reorder every state purely by win count, ignoring safety."""
    stats, _ = profile.profile_lexer(PythonLexer, corpus)
    base = PythonLexer()
    table = {}
    for state, rules in base._tokens.items():
        scored = sorted(range(len(rules)),
                        key=lambda i: -stats[(state, i)].wins)
        table[state] = [rules[i] for i in scored]
    return table


def clip(token, width=58):
    """Readable, ASCII-safe preview of one pygments token."""
    if token is None:
        return "end of stream"
    pos, kind, text = token
    shown = ascii(text)
    if len(shown) > width:
        shown = shown[:width] + "..."
    return "%s %s" % (kind, shown)


def describe(diff):
    index, original, produced = diff
    return ("token %d" % index + NL_SEP +
            "      original:  " + clip(original) + NL_SEP +
            "      reordered: " + clip(produced))


def main():
    corpus = load_corpus()
    print("corpus: %d characters of CPython standard library source\n"
          % len(corpus))

    unsafe = frequency_sorted_table(corpus)
    same, count, diff = optimize.verify_equivalence(PythonLexer, unsafe,
                                                    corpus)
    print("sort every rule list by win count, ignoring overlap")
    if same:
        print("  token stream: identical (%d tokens)" % count)
    else:
        print("  token stream: DIFFERENT")
        print("  first divergence: %s" % describe(diff))

    safe, reports = optimize.optimize_lexer(PythonLexer, corpus,
                                            cost_model="uniform")
    same2, count2, diff2 = optimize.verify_equivalence(PythonLexer, safe,
                                                       corpus)
    summary = optimize.summarize(reports)
    print("\naltrank order, with the overlap analysis switched on")
    if same2:
        print("  token stream: identical (%d tokens)" % count2)
    else:
        print("  token stream: DIFFERENT")
        print("  first divergence: %s" % describe(diff2))
    print("  ordering constraints honoured: %d conflicting rule pairs"
          % summary["conflict_pairs"])
    print("  attempts per matched token: %.2f before, %.2f after"
          % (summary["baseline_per_event"], summary["optimized_per_event"]))

    if same and not same2:
        print("\nunexpected: the naive order held but altrank did not")
        return 1
    return 0 if same2 else 1


if __name__ == "__main__":
    sys.exit(main())
