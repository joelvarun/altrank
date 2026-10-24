"""Measure how an ordered rule list actually behaves on a real corpus.

Two numbers per rule drive the scheduler: how often the rule is the winner
(its weight) and how much one failed attempt costs (its processing time).
Both are measured, never assumed.
"""

import time


class RuleStats:
    """Call and win counts for one rule in one state."""

    __slots__ = ("state", "index", "pattern", "trials", "wins", "unit_cost")

    def __init__(self, state, index, pattern):
        self.state = state
        self.index = index
        self.pattern = pattern
        self.trials = 0
        self.wins = 0
        self.unit_cost = 1.0

    def __repr__(self):
        return "RuleStats(%r, %d, trials=%d, wins=%d)" % (
            self.state, self.index, self.trials, self.wins)


def _counting(matcher, stats):
    def wrapper(text, pos, _m=matcher, _s=stats):
        _s.trials += 1
        hit = _m(text, pos)
        if hit is not None:
            _s.wins += 1
        return hit
    wrapper.__self__ = matcher.__self__
    return wrapper


def instrument(lexer):
    """Return (token table with counting matchers, {(state, index): RuleStats}).

    The pygments scan loop stops at the first rule that returns a match, so a
    truthy return is exactly a win and a call is exactly a trial.
    """
    token_table = getattr(lexer, "_tokens", None)
    if token_table is None:
        raise TypeError(
            "%s is not a RegexLexer, so it has no ordered rule list to "
            "reorder" % type(lexer).__name__)
    stats = {}
    table = {}
    for state, rules in token_table.items():
        wrapped = []
        for index, rule in enumerate(rules):
            matcher, action, new_state = rule
            entry = RuleStats(state, index, matcher.__self__.pattern)
            stats[(state, index)] = entry
            wrapped.append((_counting(matcher, entry), action, new_state))
        table[state] = wrapped
    return table, stats


def profile_lexer(lexer_cls, corpus):
    """Run a pygments lexer over ``corpus`` and return its per-rule statistics."""
    lexer = lexer_cls()
    table, stats = instrument(lexer)
    lexer._tokens = table
    tokens = 0
    for _ in lexer.get_tokens_unprocessed(corpus):
        tokens += 1
    return stats, tokens


def total_trials(stats):
    return sum(s.trials for s in stats.values())


def total_wins(stats):
    return sum(s.wins for s in stats.values())


def sample_positions(lexer_cls, corpus, per_state=160):
    """Collect input offsets that each state is actually scanned at."""
    lexer = lexer_cls()
    seen = {}
    table = {}
    for state, rules in lexer._tokens.items():
        seen[state] = []
        wrapped = []
        first = True
        for matcher, action, new_state in rules:
            if first:
                wrapped.append((_recording(matcher, seen[state], per_state),
                                action, new_state))
                first = False
            else:
                wrapped.append((matcher, action, new_state))
        table[state] = wrapped
    lexer._tokens = table
    for _ in lexer.get_tokens_unprocessed(corpus):
        pass
    return {k: v for k, v in seen.items() if v}


def _recording(matcher, sink, limit):
    def wrapper(text, pos, _m=matcher, _sink=sink, _limit=limit):
        if len(_sink) < _limit:
            _sink.append(pos)
        return _m(text, pos)
    wrapper.__self__ = matcher.__self__
    return wrapper


def measure_unit_costs(patterns, corpus, positions, repeats=3):
    """Time one failed-or-successful attempt per rule, in microseconds.

    Configurations are interleaved round robin and the minimum of the repeats
    is kept, so a slow moment on the machine cannot be mistaken for a slow
    rule.
    """
    if not positions:
        return [1.0] * len(patterns)
    best = [None] * len(patterns)
    for _ in range(repeats):
        for idx, pattern in enumerate(patterns):
            match = pattern.match
            start = time.perf_counter()
            for pos in positions:
                match(corpus, pos)
            elapsed = time.perf_counter() - start
            if best[idx] is None or elapsed < best[idx]:
                best[idx] = elapsed
    scale = 1e6 / len(positions)
    out = [max(b * scale, 1e-6) for b in best]
    return out
