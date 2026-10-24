"""Order a rule list to minimise expected work, subject to safety precedence.

Trying rule j costs p[j] and rule j is the winner with weight w[j].  If the
winner sits at position k, the scan pays the cost of every rule up to and
including it, so the expected work for an ordering is

    sum over j of  w[j] * (sum of p[k] for every k at or before j)

which is the classic single-machine problem of minimising total weighted
completion time, written 1 | prec | sum w_j C_j.  Without precedence the
optimum is Smith's ratio rule (sort by w/p descending).  With precedence the
problem is NP-hard in general, so altrank uses Sidney decomposition: the
maximum-density closed set can always be scheduled first by some optimal
sequence, which splits the instance into blocks that are ordered exactly.
Inside a block altrank solves small posets exactly and otherwise falls back to
a ratio-greedy topological order, always reporting a valid lower bound so the
remaining gap is visible instead of assumed away.
"""

import itertools

from .maxflow import max_weight_closure

EPS = 1e-12


class Schedule:
    """An ordering plus the evidence for how good it is."""

    def __init__(self, order, cost, lower_bound, blocks, exact_blocks):
        self.order = order
        self.cost = cost
        self.lower_bound = lower_bound
        self.blocks = blocks
        self.exact_blocks = exact_blocks

    @property
    def certified_optimal(self):
        """True when every Sidney block was solved exactly.

        Sidney's theorem puts some optimal sequence in this block order, and
        the elapsed time ahead of a block is fixed once the block order is,
        so each block optimises independently.  Exact blocks therefore compose
        into a globally optimal schedule.
        """
        return self.exact_blocks == len(self.blocks)

    @property
    def gap(self):
        if self.lower_bound <= EPS:
            return 0.0
        return (self.cost - self.lower_bound) / self.lower_bound


def cost_of(order, w, p):
    """Total weighted completion time of an ordering."""
    total = 0.0
    elapsed = 0.0
    for j in order:
        elapsed += p[j]
        total += w[j] * elapsed
    return total


def transitive_preds(n, pairs):
    """preds[j] = every index that must come before j, transitively closed."""
    direct = {j: set() for j in range(n)}
    for i, j in pairs:
        direct[j].add(i)
    preds = {j: set() for j in range(n)}
    for j in range(n):
        stack = list(direct[j])
        seen = set(stack)
        while stack:
            u = stack.pop()
            for v in direct[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        preds[j] = seen
    return preds


def smith_order(nodes, w, p):
    """Smith's ratio rule: optimal when there is no precedence at all."""
    return sorted(nodes, key=lambda j: (-(w[j] / p[j]) if p[j] > 0 else 0.0, j))


def ratio_greedy(nodes, preds, w, p):
    """Topological order that always takes the best available ratio."""
    inside = set(nodes)
    remaining = set(nodes)
    done = set()
    out = []
    while remaining:
        ready = [j for j in remaining if (preds[j] & inside) <= done]
        if not ready:
            ready = sorted(remaining)
        pick = min(ready, key=lambda j: (-(w[j] / p[j]) if p[j] > 0 else 0.0, j))
        out.append(pick)
        done.add(pick)
        remaining.discard(pick)
    return out


def interchange(order, preds, w, p, rounds=200):
    """Improve a feasible order by adjacent swaps that precedence allows.

    Used only inside blocks that were too large to solve exactly.  A swap is
    applied when it lowers the objective, so this can never make a schedule
    worse, but it does not certify optimality.
    """
    order = list(order)
    inside = set(order)
    for _ in range(rounds):
        improved = False
        for k in range(len(order) - 1):
            a, b = order[k], order[k + 1]
            if a in (preds[b] & inside):
                continue
            # Swapping neighbours only changes these two terms.
            before = w[a] * p[a] + w[b] * (p[a] + p[b])
            after = w[b] * p[b] + w[a] * (p[b] + p[a])
            if after < before - 1e-15:
                order[k], order[k + 1] = b, a
                improved = True
        if not improved:
            break
    return order


def exact_block(nodes, preds, w, p):
    """Exact order for a small block by dynamic programming over ideals."""
    nodes = list(nodes)
    n = len(nodes)
    pos = {v: i for i, v in enumerate(nodes)}
    need = []
    for v in nodes:
        mask = 0
        for u in preds[v]:
            if u in pos:
                mask |= 1 << pos[u]
        need.append(mask)
    pv = [p[v] for v in nodes]
    wv = [w[v] for v in nodes]
    full = (1 << n) - 1
    best = {0: (0.0, 0.0, None, None)}   # mask -> (cost, elapsed, prev, pick)
    frontier = [0]
    while frontier:
        nxt = []
        for mask in frontier:
            cost, elapsed, _, _ = best[mask]
            for k in range(n):
                bit = 1 << k
                if mask & bit or (need[k] & ~mask):
                    continue
                nmask = mask | bit
                nelapsed = elapsed + pv[k]
                ncost = cost + wv[k] * nelapsed
                cur = best.get(nmask)
                if cur is None or ncost < cur[0] - 1e-15:
                    if cur is None:
                        nxt.append(nmask)
                    best[nmask] = (ncost, nelapsed, mask, k)
        frontier = nxt
    if full not in best:
        return ratio_greedy(nodes, preds, w, p)
    out = []
    mask = full
    while mask:
        _, _, prev, pick = best[mask]
        out.append(nodes[pick])
        mask = prev
    out.reverse()
    return out


def brute_force(nodes, preds, w, p):
    """Reference implementation used by the tests to confirm optimality."""
    nodes = list(nodes)
    best = None
    best_cost = None
    for perm in itertools.permutations(nodes):
        seen = set()
        ok = True
        for j in perm:
            if not (preds[j] & set(nodes)) <= seen:
                ok = False
                break
            seen.add(j)
        if not ok:
            continue
        c = cost_of(perm, w, p)
        if best_cost is None or c < best_cost - 1e-15:
            best, best_cost = list(perm), c
    return best, best_cost


def max_density_prefix(nodes, preds, w, p):
    """Maximum-density closed subset, found by Dinkelbach iteration."""
    nodes = list(nodes)
    inside = set(nodes)
    local_preds = {v: (preds[v] & inside) for v in nodes}
    lam = 0.0
    chosen = None
    for _ in range(64):
        weights = {v: w[v] - lam * p[v] for v in nodes}
        cand, value = max_weight_closure(nodes, weights, local_preds)
        if not cand or value <= 1e-9:
            break
        pw = sum(p[v] for v in cand)
        if pw <= EPS:
            break
        chosen = cand
        new_lam = sum(w[v] for v in cand) / pw
        if abs(new_lam - lam) <= 1e-12:
            break
        lam = new_lam
    return chosen if chosen else list(nodes)


def solve(n, pairs, w, p, exact_limit=14):
    """Order 0..n-1 respecting ``pairs``, returning a :class:`Schedule`."""
    p = {j: max(float(p[j]), 1e-9) for j in range(n)}
    w = {j: float(w[j]) for j in range(n)}
    preds = transitive_preds(n, pairs)
    remaining = set(range(n))
    order = []
    bound_order = []
    blocks = []
    exact_blocks = 0
    while remaining:
        block = max_density_prefix(remaining, preds, w, p)
        block = [v for v in block if v in remaining]
        if not block:
            block = sorted(remaining)
        if len(block) <= exact_limit:
            inner = exact_block(block, preds, w, p)
            exact_blocks += 1
            bound_inner = list(inner)
        else:
            inner = interchange(ratio_greedy(block, preds, w, p), preds, w, p)
            bound_inner = smith_order(block, w, p)
        order.extend(inner)
        blocks.append(list(inner))
        bound_order.extend(bound_inner)
        remaining -= set(block)
    cost = cost_of(order, w, p)
    lower = cost_of(bound_order, w, p)
    return Schedule(order, cost, lower, blocks, exact_blocks)


def unconstrained_bound(n, w, p):
    """Cost if safety could be ignored entirely. A floor on any safe order."""
    p = {j: max(float(p[j]), 1e-9) for j in range(n)}
    w = {j: float(w[j]) for j in range(n)}
    return cost_of(smith_order(range(n), w, p), w, p)
