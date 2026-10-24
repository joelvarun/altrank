"""Compare four orderings of the same rule lists under the same safety rules.

    python bench/compare_orders.py

The point of this script is to separate two questions that are easy to
conflate: whether a reordering is allowed, and whether it is any good.  All
three candidate orderings below obey exactly the same safety constraints, so
any difference between them is the scheduler alone.
"""

import glob
import os
import sys
import sysconfig

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pygments.lexers.python import PythonLexer

from altrank import overlap, profile, schedule

FILES = 14


def frequency_greedy(n, pairs, w, p):
    """Take the highest weight rule whose constraints are already satisfied."""
    preds = schedule.transitive_preds(n, pairs)
    remaining = set(range(n))
    done = set()
    out = []
    while remaining:
        ready = [j for j in remaining if preds[j] <= done]
        if not ready:
            ready = sorted(remaining)
        pick = max(ready, key=lambda j: (w[j], -j))
        out.append(pick)
        done.add(pick)
        remaining.discard(pick)
    return out


def main():
    stdlib = sysconfig.get_paths()["stdlib"]
    paths = sorted(glob.glob(os.path.join(stdlib, "*.py")))[:FILES]
    corpus = "\n".join(open(p, encoding="utf-8", errors="replace").read()
                       for p in paths)
    stats, _ = profile.profile_lexer(PythonLexer, corpus)
    base = PythonLexer()

    totals = {"pygments": 0.0, "frequency greedy": 0.0, "altrank": 0.0,
              "floor (unsafe)": 0.0}
    events = 0.0
    constrained = 0
    for state, rules in base._tokens.items():
        n = len(rules)
        w = {i: float(stats[(state, i)].wins) for i in range(n)}
        if n < 2 or sum(w.values()) < 1:
            continue
        p = {i: 1.0 for i in range(n)}
        patterns = [r[0].__self__.pattern for r in rules]
        pairs, _langs, _why = overlap.conflict_matrix(patterns,
                                                      PythonLexer.flags)
        constrained += len(pairs)
        events += sum(w.values())
        totals["pygments"] += schedule.cost_of(range(n), w, p)
        totals["frequency greedy"] += schedule.cost_of(
            frequency_greedy(n, pairs, w, p), w, p)
        totals["altrank"] += schedule.solve(n, pairs, w, p).cost
        totals["floor (unsafe)"] += schedule.unconstrained_bound(n, w, p)

    print("corpus: %d files, %d characters, %d match events"
          % (len(paths), len(corpus), int(events)))
    print("safety constraints: %d conflicting rule pairs\n" % constrained)
    print("%-18s %14s %10s" % ("ordering", "attempts/token", "vs pygments"))
    base_cost = totals["pygments"]
    for name in ("pygments", "frequency greedy", "altrank", "floor (unsafe)"):
        print("%-18s %14.2f %9.2fx"
              % (name, totals[name] / events, base_cost / totals[name]))
    print("\nAll three reorderings obey the same constraints; only the")
    print("scheduling method differs. The floor ignores safety entirely and")
    print("is not reachable by any correct ordering.")


if __name__ == "__main__":
    main()
