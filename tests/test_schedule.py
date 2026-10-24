"""Optimality tests for the scheduler.

The ordering problem is 1 | prec | sum w_j C_j, which is NP-hard in general,
so these tests pin down the two claims altrank actually makes: the answer
matches exhaustive search on small instances, and a schedule reported as
certified really is optimal.
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from altrank import schedule


def _floats(mapping):
    return {k: float(v) for k, v in mapping.items()}


def test_smith_rule_without_precedence():
    # No constraints, so the optimum is ratio order: 2/1, 3/2, 1/4.
    w = {0: 1, 1: 3, 2: 2}
    p = {0: 4, 1: 2, 2: 1}
    result = schedule.solve(3, set(), w, p)
    assert result.order == [2, 1, 0]
    assert result.certified_optimal


def test_chain_is_respected():
    w = {0: 1, 1: 100}
    p = {0: 1, 1: 1}
    # Rule 1 is far hotter but must stay behind rule 0.
    result = schedule.solve(2, {(0, 1)}, w, p)
    assert result.order == [0, 1]
    assert result.certified_optimal


def test_block_is_pulled_forward_as_a_unit():
    # A cheap cold rule unlocks a very hot one, so the pair beats a rule whose
    # own ratio is higher than the cold rule's.
    w = {0: 0, 1: 100, 2: 10}
    p = {0: 1, 1: 1, 2: 1}
    result = schedule.solve(3, {(0, 1)}, w, p)
    assert result.order == [0, 1, 2]
    assert result.certified_optimal


def test_matches_brute_force_on_random_instances():
    rng = random.Random(20261024)
    trials = 0
    worse = 0
    for _ in range(300):
        n = rng.randint(2, 7)
        pairs = set()
        for i in range(n):
            for j in range(i + 1, n):
                if rng.random() < 0.3:
                    pairs.add((i, j))
        w = {i: rng.randint(0, 20) for i in range(n)}
        p = {i: rng.randint(1, 5) for i in range(n)}
        result = schedule.solve(n, pairs, w, p)
        preds = schedule.transitive_preds(n, pairs)
        _best, best_cost = schedule.brute_force(range(n), preds, _floats(w),
                                                _floats(p))
        trials += 1
        if result.cost > best_cost + 1e-9:
            worse += 1
    assert trials == 300
    assert worse == 0, "%d instances beat the scheduler" % worse


def test_certified_schedules_are_optimal():
    rng = random.Random(99)
    certified = 0
    for _ in range(200):
        n = rng.randint(2, 6)
        pairs = {(i, j) for i in range(n) for j in range(i + 1, n)
                 if rng.random() < 0.35}
        w = {i: rng.randint(0, 12) for i in range(n)}
        p = {i: rng.randint(1, 4) for i in range(n)}
        result = schedule.solve(n, pairs, w, p)
        if not result.certified_optimal:
            continue
        certified += 1
        preds = schedule.transitive_preds(n, pairs)
        _best, best_cost = schedule.brute_force(range(n), preds, _floats(w),
                                                _floats(p))
        assert abs(result.cost - best_cost) < 1e-9
    assert certified > 50


def test_precedence_is_never_violated():
    rng = random.Random(5)
    for _ in range(200):
        n = rng.randint(2, 12)
        pairs = {(i, j) for i in range(n) for j in range(i + 1, n)
                 if rng.random() < 0.2}
        w = {i: rng.randint(0, 30) for i in range(n)}
        p = {i: rng.randint(1, 6) for i in range(n)}
        result = schedule.solve(n, pairs, w, p)
        position = {j: k for k, j in enumerate(result.order)}
        assert sorted(result.order) == list(range(n))
        for i, j in pairs:
            assert position[i] < position[j], "constraint %d<%d broken" % (i, j)


def test_interchange_never_increases_cost():
    rng = random.Random(3)
    for _ in range(100):
        n = rng.randint(3, 10)
        pairs = {(i, j) for i in range(n) for j in range(i + 1, n)
                 if rng.random() < 0.15}
        w = _floats({i: rng.randint(0, 20) for i in range(n)})
        p = _floats({i: rng.randint(1, 5) for i in range(n)})
        preds = schedule.transitive_preds(n, pairs)
        start = schedule.ratio_greedy(range(n), preds, w, p)
        improved = schedule.interchange(start, preds, w, p)
        assert schedule.cost_of(improved, w, p) <= \
            schedule.cost_of(start, w, p) + 1e-9
        position = {j: k for k, j in enumerate(improved)}
        for i, j in pairs:
            assert position[i] < position[j]


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
