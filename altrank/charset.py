"""Character sets as sorted, disjoint, inclusive codepoint intervals.

Every regex atom in :mod:`altrank.rxparse` is reduced to one of these, so the
overlap test in :mod:`altrank.overlap` only ever has to reason about intervals
rather than about regex syntax.
"""

MAXCP = 0x10FFFF

EMPTY = ()
FULL = ((0, MAXCP),)


def from_char(ch):
    c = ord(ch)
    return ((c, c),)


def from_range(lo, hi):
    if lo > hi:
        return EMPTY
    return ((lo, hi),)


def normalize(intervals):
    """Sort, clip and coalesce an arbitrary interval list."""
    items = sorted((lo, hi) for lo, hi in intervals if lo <= hi)
    out = []
    for lo, hi in items:
        lo = max(0, lo)
        hi = min(MAXCP, hi)
        if lo > hi:
            continue
        if out and lo <= out[-1][1] + 1:
            if hi > out[-1][1]:
                out[-1][1] = hi
        else:
            out.append([lo, hi])
    return tuple((lo, hi) for lo, hi in out)


def union(*sets):
    acc = []
    for s in sets:
        acc.extend(s)
    return normalize(acc)


def complement(s):
    out = []
    prev = 0
    for lo, hi in s:
        if lo > prev:
            out.append((prev, lo - 1))
        prev = max(prev, hi + 1)
    if prev <= MAXCP:
        out.append((prev, MAXCP))
    return tuple(out)


def intersect(a, b):
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if lo <= hi:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return tuple(out)


def is_empty(s):
    return not s


def size(s):
    return sum(hi - lo + 1 for lo, hi in s)


def contains(s, cp):
    for lo, hi in s:
        if lo <= cp <= hi:
            return True
        if cp < lo:
            return False
    return False


def atoms(sets):
    """Partition the union of ``sets`` into intervals that no set splits.

    Testing one representative codepoint per returned interval is equivalent to
    testing every codepoint, which is what keeps the product construction in
    :mod:`altrank.overlap` finite.
    """
    bounds = set()
    for s in sets:
        for lo, hi in s:
            bounds.add(lo)
            bounds.add(hi + 1)
    cuts = sorted(bounds)
    out = []
    for i in range(len(cuts) - 1):
        lo, hi = cuts[i], cuts[i + 1] - 1
        if lo <= hi <= MAXCP:
            out.append((lo, hi))
    return tuple(out)
