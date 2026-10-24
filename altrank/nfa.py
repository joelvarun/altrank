"""Thompson construction over interval charsets, plus the Sigma* closure.

The overlap test needs three things from a pattern: whether it can match the
empty string, which characters it can start with, and a machine for the
language L followed by anything at all (L . Sigma*).
"""

from . import charset as cs

STATE_CAP = 4000


class TooLarge(Exception):
    """Raised when a pattern expands past STATE_CAP states."""


class NFA:
    __slots__ = ("trans", "eps", "start", "accept")

    def __init__(self):
        self.trans = []   # state -> list of (charset, dst)
        self.eps = []     # state -> list of dst
        self.start = 0
        self.accept = 0

    def new_state(self):
        if len(self.trans) >= STATE_CAP:
            raise TooLarge(len(self.trans))
        self.trans.append([])
        self.eps.append([])
        return len(self.trans) - 1

    def __len__(self):
        return len(self.trans)

    # -- queries ---------------------------------------------------------
    def closure(self, states):
        """Epsilon closure of a set of states."""
        stack = list(states)
        seen = set(stack)
        while stack:
            s = stack.pop()
            for d in self.eps[s]:
                if d not in seen:
                    seen.add(d)
                    stack.append(d)
        return frozenset(seen)

    def start_set(self):
        return self.closure([self.start])

    def nullable(self):
        return self.accept in self.start_set()

    def first_set(self):
        """Characters that can begin a match. A sound over-approximation."""
        out = [chars for s in self.start_set() for chars, _ in self.trans[s]]
        return cs.union(*out) if out else cs.EMPTY

    def step(self, states, codepoint):
        """Advance a state set by one character."""
        nxt = set()
        for s in states:
            for chars, dst in self.trans[s]:
                if cs.contains(chars, codepoint):
                    nxt.add(dst)
        return self.closure(nxt) if nxt else frozenset()

    def out_charsets(self, states):
        return [chars for s in states for chars, _ in self.trans[s]]

    def add_sigma_star(self):
        """Turn the machine for L into one for L . Sigma*."""
        self.trans[self.accept].append((cs.FULL, self.accept))
        return self


def build(node):
    """Compile a parsed node into an NFA. Raises TooLarge on blow-up."""
    m = NFA()
    start, accept = _emit(m, node)
    m.start = start
    m.accept = accept
    return m


def _emit(m, node):
    kind = node[0]
    if kind == "eps":
        s = m.new_state()
        return s, s
    if kind == "set":
        chars = node[1]
        s = m.new_state()
        t = m.new_state()
        if not cs.is_empty(chars):
            m.trans[s].append((chars, t))
        return s, t
    if kind == "cat":
        parts = node[1]
        if not parts:
            s = m.new_state()
            return s, s
        first_s, cur = _emit(m, parts[0])
        for p in parts[1:]:
            ps, pa = _emit(m, p)
            m.eps[cur].append(ps)
            cur = pa
        return first_s, cur
    if kind == "alt":
        s = m.new_state()
        t = m.new_state()
        for p in node[1]:
            ps, pa = _emit(m, p)
            m.eps[s].append(ps)
            m.eps[pa].append(t)
        return s, t
    if kind == "rep":
        _, inner, lo, hi = node
        s = m.new_state()
        cur = s
        for _ in range(lo):
            ps, pa = _emit(m, inner)
            m.eps[cur].append(ps)
            cur = pa
        if hi is None:
            ps, pa = _emit(m, inner)
            m.eps[cur].append(ps)
            m.eps[pa].append(ps)
            t = m.new_state()
            m.eps[cur].append(t)
            m.eps[pa].append(t)
            return s, t
        t = m.new_state()
        m.eps[cur].append(t)
        for _ in range(hi - lo):
            ps, pa = _emit(m, inner)
            m.eps[cur].append(ps)
            m.eps[pa].append(t)
            cur = pa
        return s, t
    raise ValueError("unknown node kind %r" % (kind,))
