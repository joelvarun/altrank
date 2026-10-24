"""Tie the pieces together: profile, prove safety, reorder, report.

The safety analysis depends only on the patterns, so a reordering stays
correct on every possible input.  The corpus only decides how fast the result
is, never whether it is right.
"""

from . import overlap, profile, schedule


class StateReport:
    """What altrank did to one state's rule list."""

    def __init__(self, state, order, weights, costs, conflicts, sched,
                 approx_rules, floor):
        self.state = state
        self.order = order
        self.weights = weights
        self.costs = costs
        self.conflicts = conflicts
        self.schedule = sched
        self.approx_rules = approx_rules
        self.floor = floor

    @property
    def n(self):
        return len(self.order)

    @property
    def baseline_cost(self):
        return schedule.cost_of(range(self.n), self.weights, self.costs)

    @property
    def optimized_cost(self):
        return self.schedule.cost

    @property
    def observations(self):
        return sum(self.weights.values())

    @property
    def moved(self):
        return sum(1 for pos, j in enumerate(self.order) if pos != j)

    def speedup(self):
        if self.optimized_cost <= 0:
            return 1.0
        return self.baseline_cost / self.optimized_cost


def optimize_state(patterns, weights, costs, flags=0, budget=None):
    """Reorder one rule list. ``patterns`` are regex strings."""
    n = len(patterns)
    kwargs = {} if budget is None else {"budget": budget}
    pairs, langs, _reasons = overlap.conflict_matrix(patterns, flags, **kwargs)
    sched = schedule.solve(n, pairs, weights, costs)
    floor = schedule.unconstrained_bound(n, weights, costs)
    approx = [i for i, lang in enumerate(langs) if lang.approximated]
    return pairs, sched, floor, approx


def optimize_lexer(lexer_cls, corpus, cost_model="measured", min_events=1,
                   budget=None):
    """Profile a pygments lexer on ``corpus`` and return (token table, reports).

    ``cost_model`` is "measured" to time one attempt per rule, or "uniform" to
    count attempts instead.
    """
    stats, _tokens_seen = profile.profile_lexer(lexer_cls, corpus)
    base = lexer_cls()
    flags = getattr(lexer_cls, "flags", 0)
    positions = (profile.sample_positions(lexer_cls, corpus)
                 if cost_model == "measured" else {})

    table = {}
    reports = []
    for state, rules in base._tokens.items():
        patterns = [r[0].__self__.pattern for r in rules]
        n = len(rules)
        weights = {i: float(stats[(state, i)].wins) for i in range(n)}
        if sum(weights.values()) < min_events or n < 2:
            table[state] = list(rules)
            continue
        if cost_model == "measured":
            compiled = [r[0].__self__ for r in rules]
            costs_list = profile.measure_unit_costs(
                compiled, corpus, positions.get(state, []))
            costs = {i: costs_list[i] for i in range(n)}
        else:
            costs = {i: 1.0 for i in range(n)}
        pairs, sched, floor, approx = optimize_state(
            patterns, weights, costs, flags, budget)
        table[state] = [rules[i] for i in sched.order]
        reports.append(StateReport(state, sched.order, weights, costs,
                                   pairs, sched, approx, floor))
    return table, reports


def apply_to(lexer, table):
    """Attach a reordered token table to a lexer instance."""
    lexer._tokens = table
    return lexer


def verify_equivalence(lexer_cls, table, corpus):
    """Confirm the reordered lexer emits exactly the original token stream."""
    original = list(lexer_cls().get_tokens_unprocessed(corpus))
    tuned = lexer_cls()
    tuned._tokens = table
    produced = list(tuned.get_tokens_unprocessed(corpus))
    if original == produced:
        return True, len(original), None
    for idx, (a, b) in enumerate(zip(original, produced)):
        if a != b:
            return False, len(original), (idx, a, b)
    return False, len(original), (min(len(original), len(produced)), None, None)


def summarize(reports):
    """Aggregate per-state reports into one set of corpus-wide numbers."""
    base = sum(r.baseline_cost for r in reports)
    tuned = sum(r.optimized_cost for r in reports)
    floor = sum(r.floor for r in reports)
    events = sum(r.observations for r in reports)
    return {
        "states": len(reports),
        "rules": sum(r.n for r in reports),
        "events": events,
        "conflict_pairs": sum(len(r.conflicts) for r in reports),
        "approximated_rules": sum(len(r.approx_rules) for r in reports),
        "baseline_cost": base,
        "optimized_cost": tuned,
        "unconstrained_floor": floor,
        "speedup": (base / tuned) if tuned > 0 else 1.0,
        "certified_states": sum(1 for r in reports
                                if r.schedule.certified_optimal),
        "baseline_per_event": (base / events) if events else 0.0,
        "optimized_per_event": (tuned / events) if events else 0.0,
        "floor_per_event": (floor / events) if events else 0.0,
    }
