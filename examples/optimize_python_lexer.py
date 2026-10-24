"""Walk through what altrank does to the pygments Python lexer.

    python examples/optimize_python_lexer.py

Prints the hottest rules in the "root" state with their old and new
positions, the safety constraints that hold the hot rules back, and a check
that the reordered lexer emits exactly the original token stream.
"""

import glob
import os
import sys
import sysconfig
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pygments.lexers.python import PythonLexer

from altrank import optimize, overlap, profile, schedule

FILES = 10
STATE = "root"


def short(pattern, width=46):
    """ASCII-safe one line preview, printable on any console."""
    text = pattern.encode("ascii", "backslashreplace").decode("ascii")
    text = text.replace(chr(10), chr(92) + "n")
    if len(text) <= width:
        return text
    return text[:width - 3] + "..."


def main():
    stdlib = sysconfig.get_paths()["stdlib"]
    paths = sorted(glob.glob(os.path.join(stdlib, "*.py")))[:FILES]
    corpus = "\n".join(open(p, encoding="utf-8", errors="replace").read()
                       for p in paths)
    print("corpus: %d files from %s, %d characters"
          % (len(paths), stdlib, len(corpus)))

    stats, _ = profile.profile_lexer(PythonLexer, corpus)
    base = PythonLexer()
    rules = base._tokens[STATE]
    patterns = [r[0].__self__.pattern for r in rules]
    n = len(rules)
    weights = {i: float(stats[(STATE, i)].wins) for i in range(n)}
    costs = {i: 1.0 for i in range(n)}

    print("\nstate %r has %d rules, %d match events\n"
          % (STATE, n, int(sum(weights.values()))))

    started = time.perf_counter()
    pairs, sched, floor, approx = optimize.optimize_state(
        patterns, weights, costs, PythonLexer.flags)
    print("safety analysis: %d of %d rule pairs must keep their order "
          "(%.1fs)" % (len(pairs), n * (n - 1) // 2,
                       time.perf_counter() - started))
    print("%d rules were over-approximated, so altrank treats them "
          "pessimistically" % len(approx))

    new_position = {rule: pos for pos, rule in enumerate(sched.order)}
    hottest = sorted(range(n), key=lambda i: -weights[i])[:10]
    print("\n%-5s %-5s %9s   %s" % ("was", "now", "wins", "pattern"))
    for i in hottest:
        print("%-5d %-5d %9d   %s"
              % (i + 1, new_position[i] + 1, int(weights[i]),
                 short(patterns[i])))

    events = sum(weights.values())
    before = schedule.cost_of(range(n), weights, costs)
    print("\nattempts per matched token: %.2f before, %.2f after"
          % (before / events, sched.cost / events))
    print("unreachable floor if safety were ignored: %.2f" % (floor / events))
    print("Sidney blocks: %d, solved exactly: %d, certified optimal: %s"
          % (len(sched.blocks), sched.exact_blocks, sched.certified_optimal))

    # Show one binding constraint: the hottest rule that cannot move to front.
    blocked = [i for i in hottest if new_position[i] > 0]
    for i in blocked[:1]:
        holders = sorted(j for j in range(n) if (j, i) in pairs)
        if holders:
            j = holders[0]
            langs = (overlap.RuleLanguage(patterns[j], PythonLexer.flags),
                     overlap.RuleLanguage(patterns[i], PythonLexer.flags))
            _verdict, why = overlap.decide(*langs)
            print("\nwhy rule %d cannot lead: %d rules must precede it, "
                  "for example rule %d" % (i + 1, len(holders), j + 1))
            print("  rule %-3d %s" % (j + 1, short(patterns[j], 60)))
            print("  rule %-3d %s" % (i + 1, short(patterns[i], 60)))
            print("  reason: %s" % why)

    table, _reports = optimize.optimize_lexer(PythonLexer, corpus,
                                              cost_model="uniform")
    same, count, diff = optimize.verify_equivalence(PythonLexer, table, corpus)
    print("\ntoken stream after reordering: %s (%d tokens)"
          % ("identical" if same else "DIFFERENT at %s" % (diff,), count))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
