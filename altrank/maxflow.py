"""Dinic max-flow and the maximum-weight closure it is used for.

A closed set is one that contains every predecessor of every member.  Picard's
reduction turns "find the heaviest closed set" into a minimum cut, which is
what lets :mod:`altrank.schedule` find a maximum-density prefix exactly.
"""

INF = float("inf")


class Dinic:
    def __init__(self, n):
        self.n = n
        self.graph = [[] for _ in range(n)]

    def add_edge(self, u, v, cap):
        self.graph[u].append([v, cap, len(self.graph[v])])
        self.graph[v].append([u, 0.0, len(self.graph[u]) - 1])

    def _bfs(self, s, t):
        self.level = [-1] * self.n
        self.level[s] = 0
        queue = [s]
        while queue:
            nxt = []
            for u in queue:
                for v, cap, _ in self.graph[u]:
                    if cap > 1e-12 and self.level[v] < 0:
                        self.level[v] = self.level[u] + 1
                        nxt.append(v)
            queue = nxt
        return self.level[t] >= 0

    def _dfs(self, u, t, limit):
        if u == t:
            return limit
        while self.it[u] < len(self.graph[u]):
            edge = self.graph[u][self.it[u]]
            v, cap, rev = edge
            if cap > 1e-12 and self.level[v] == self.level[u] + 1:
                got = self._dfs(v, t, min(limit, cap))
                if got > 1e-12:
                    edge[1] -= got
                    self.graph[v][rev][1] += got
                    return got
            self.it[u] += 1
        return 0.0

    def max_flow(self, s, t):
        total = 0.0
        while self._bfs(s, t):
            self.it = [0] * self.n
            while True:
                got = self._dfs(s, t, INF)
                if got <= 1e-12:
                    break
                total += got
        return total

    def min_cut_source_side(self, s):
        """Nodes reachable from s in the residual graph (the minimal cut side)."""
        seen = {s}
        stack = [s]
        while stack:
            u = stack.pop()
            for v, cap, _ in self.graph[u]:
                if cap > 1e-12 and v not in seen:
                    seen.add(v)
                    stack.append(v)
        return seen

    def min_cut_sink_side(self, t):
        """Nodes that can still reach t in the residual graph."""
        rev_adj = [[] for _ in range(self.n)]
        for u in range(self.n):
            for v, cap, _ in self.graph[u]:
                if cap > 1e-12:
                    rev_adj[v].append(u)
        seen = {t}
        stack = [t]
        while stack:
            u = stack.pop()
            for v in rev_adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        return seen


def max_weight_closure(nodes, weights, preds):
    """Heaviest closed subset of ``nodes``.

    ``preds[j]`` lists the elements that must precede ``j``.  The returned set
    is the largest one attaining the optimum, so a zero-weight optimum still
    yields the biggest tied set rather than the empty set.
    """
    index = {v: i for i, v in enumerate(nodes)}
    n = len(nodes)
    s, t = n, n + 1
    net = Dinic(n + 2)
    positive = 0.0
    for v in nodes:
        a = weights[v]
        if a > 0:
            net.add_edge(s, index[v], a)
            positive += a
        elif a < 0:
            net.add_edge(index[v], t, -a)
    for v in nodes:
        for u in preds.get(v, ()):          # v in S forces u in S
            if u in index:
                net.add_edge(index[v], index[u], INF)
    flow = net.max_flow(s, t)
    sink_side = net.min_cut_sink_side(t)
    chosen = [v for v in nodes if index[v] not in sink_side]
    return chosen, positive - flow
