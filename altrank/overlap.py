"""Decide whether two rules can ever both match at the same input position.

This is the safety core of altrank.  Two rules in an ordered rule list may be
swapped only if no input position exists where both could match; if such a
position exists, the earlier rule wins there and swapping would change the
result.  Writing L(A) for the language of rule A, the condition is

    no word of L(A) is a prefix of a word of L(B), and vice versa

which is exactly

    L(A) . Sigma*   intersect   L(B) . Sigma*   ==   empty

Both sides are regular, so the question is decided by a product construction.
Every approximation in rxparse widens the languages, and widening can only
turn "disjoint" into "overlapping", never the other way round, so a SAFE
verdict from this module holds for the real patterns too.
"""

from . import charset as cs
from . import nfa as nfa_mod
from . import rxparse

PAIR_BUDGET = 20000

SAFE = "safe"
CONFLICT = "conflict"


class RuleLanguage:
    """A rule's over-approximated language, prepared for overlap testing."""

    def __init__(self, pattern, flags=0):
        self.pattern = pattern
        self.flags = flags
        parsed = rxparse.parse(pattern, flags)
        self.notes = list(parsed.notes)
        self.oversized = False
        try:
            machine = nfa_mod.build(parsed.node)
        except nfa_mod.TooLarge as exc:
            self.oversized = True
            self.notes.append("pattern exceeds state cap (%s), assumed to "
                              "conflict with every rule" % exc.args[0])
            self.nfa = None
            self.nullable = True
            self.first = cs.FULL
            return
        self.nullable = machine.nullable()
        self.first = machine.first_set()
        self.nfa = machine.add_sigma_star()

    @property
    def approximated(self):
        return bool(self.notes)


def decide(a, b, budget=PAIR_BUDGET):
    """Return (verdict, reason) for two RuleLanguage objects."""
    if a.oversized or b.oversized:
        return CONFLICT, "pattern too large to analyse, assumed conflicting"
    if a.nullable and b.nullable:
        return CONFLICT, "both rules can match the empty string"
    if a.nullable:
        return CONFLICT, "first rule matches the empty string everywhere"
    if b.nullable:
        return CONFLICT, "second rule matches the empty string everywhere"
    if cs.is_empty(cs.intersect(a.first, b.first)):
        return SAFE, "no shared first character"
    return _product_empty(a.nfa, b.nfa, budget)


def _product_empty(ma, mb, budget):
    """Breadth-first search for a word accepted by both Sigma*-closed NFAs."""
    start = (ma.start_set(), mb.start_set())
    seen = {start}
    queue = [start]
    steps = 0
    while queue:
        nxt_queue = []
        for sa, sb in queue:
            if ma.accept in sa and mb.accept in sb:
                return CONFLICT, "both rules can match at the same position"
            charsets = ma.out_charsets(sa) + mb.out_charsets(sb)
            if not charsets:
                continue
            for lo, _hi in cs.atoms(charsets):
                steps += 1
                if steps > budget:
                    return CONFLICT, ("overlap search hit the %d step budget, "
                                      "assumed conflicting" % budget)
                na = ma.step(sa, lo)
                nb = mb.step(sb, lo)
                if not na or not nb:
                    continue
                pair = (na, nb)
                if pair not in seen:
                    seen.add(pair)
                    nxt_queue.append(pair)
        queue = nxt_queue
    return SAFE, "product automaton has no accepting state"


def conflict_matrix(patterns, flags=0, budget=PAIR_BUDGET):
    """Pairwise conflicts for an ordered rule list.

    Returns (pairs, langs, reasons) where pairs is the set of index pairs
    (i, j) with i < j that must keep their relative order.
    """
    langs = [RuleLanguage(p, flags) for p in patterns]
    pairs = set()
    reasons = {}
    n = len(langs)
    for i in range(n):
        for j in range(i + 1, n):
            verdict, why = decide(langs[i], langs[j], budget)
            if verdict == CONFLICT:
                pairs.add((i, j))
                reasons[(i, j)] = why
    return pairs, langs, reasons
