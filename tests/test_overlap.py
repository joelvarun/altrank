"""Safety tests for the overlap decision.

The property that matters is soundness in one direction: a SAFE verdict must
never be wrong, because a wrong SAFE verdict silently changes what the rule
list matches.  A CONFLICT verdict is allowed to be pessimistic.
"""

import itertools
import random
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from altrank import overlap


def verdict(a, b, flags=0):
    return overlap.decide(overlap.RuleLanguage(a, flags),
                          overlap.RuleLanguage(b, flags))[0]


def test_disjoint_literals_are_safe():
    assert verdict("a", "b") == overlap.SAFE
    assert verdict("foo", "bar") == overlap.SAFE


def test_shared_prefix_without_overlap_is_safe():
    # Both start with "a" but no word of one is a prefix of the other.
    assert verdict("ab", "aa") == overlap.SAFE
    assert verdict("abc", "abd") == overlap.SAFE


def test_prefix_pairs_conflict():
    assert verdict("=", "==") == overlap.CONFLICT
    assert verdict("==", "=") == overlap.CONFLICT
    assert verdict(r"\.", r"\.\.\.") == overlap.CONFLICT
    assert verdict(":", ":=") == overlap.CONFLICT


def test_class_versus_keyword_conflicts():
    assert verdict("[a-z]+", "if") == overlap.CONFLICT
    assert verdict(r"[A-Za-z_]\w*", "return") == overlap.CONFLICT


def test_disjoint_classes_are_safe():
    assert verdict(r"\d+", "[a-z]+") == overlap.SAFE
    assert verdict("[0-9]+", "[A-Z]+") == overlap.SAFE


def test_nullable_rule_conflicts_with_everything():
    assert verdict("", "abc") == overlap.CONFLICT
    assert verdict("a*", "b") == overlap.CONFLICT


def test_assertions_are_relaxed_not_trusted():
    # \b is dropped rather than modelled, so the keyword still conflicts.
    assert verdict(r"\bif\b", r"[a-z]+") == overlap.CONFLICT
    assert verdict(r"^foo", "foo") == overlap.CONFLICT


def test_lookahead_is_relaxed():
    assert verdict("a(?=b)", "ab") == overlap.CONFLICT


def test_ignorecase_folds_both_ways():
    assert verdict("ABC", "abc") == overlap.SAFE
    assert verdict("ABC", "abc", re.IGNORECASE) == overlap.CONFLICT


def test_dotall_and_dot():
    assert verdict(".", "x") == overlap.CONFLICT
    assert verdict(r"\n", "x") == overlap.SAFE


def test_repeat_bounds():
    assert verdict("a{2,3}", "aa") == overlap.CONFLICT
    assert verdict("a{3}", "b{3}") == overlap.SAFE


# -- randomised soundness check ------------------------------------------

ATOMS = ["a", "b", "c", "[ab]", "[bc]", r"\d", "[a-c]"]


def _random_pattern(rng, depth=0):
    roll = rng.random()
    if depth >= 2 or roll < 0.4:
        return rng.choice(ATOMS)
    if roll < 0.55:
        return "(?:%s|%s)" % (_random_pattern(rng, depth + 1),
                              _random_pattern(rng, depth + 1))
    if roll < 0.7:
        return "%s%s" % (_random_pattern(rng, depth + 1),
                         _random_pattern(rng, depth + 1))
    if roll < 0.85:
        return "(?:%s)%s" % (_random_pattern(rng, depth + 1),
                             rng.choice(["?", "+", "{1,2}"]))
    return "(?:%s)*" % _random_pattern(rng, depth + 1)


def _brute_force_overlap(pat_a, pat_b, max_len=5):
    """True when some short string lets both patterns match at position 0."""
    rx_a = re.compile(pat_a)
    rx_b = re.compile(pat_b)
    alphabet = "abc0"
    for length in range(max_len + 1):
        for combo in itertools.product(alphabet, repeat=length):
            text = "".join(combo)
            if rx_a.match(text) is not None and rx_b.match(text) is not None:
                return True
    return False


def test_safe_verdicts_are_never_wrong():
    rng = random.Random(20261024)
    checked = 0
    safe_seen = 0
    for _ in range(600):
        pat_a = _random_pattern(rng)
        pat_b = _random_pattern(rng)
        try:
            re.compile(pat_a)
            re.compile(pat_b)
        except re.error:
            continue
        checked += 1
        if verdict(pat_a, pat_b) == overlap.SAFE:
            safe_seen += 1
            assert not _brute_force_overlap(pat_a, pat_b), (
                "unsound SAFE verdict for %r and %r" % (pat_a, pat_b))
    assert checked > 400
    assert safe_seen > 20, "fuzzer never produced a SAFE pair, test is vacuous"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS %s" % name)
            except AssertionError as exc:
                failures += 1
                print("FAIL %s: %s" % (name, exc))
    print("failures:", failures)
    sys.exit(1 if failures else 0)
