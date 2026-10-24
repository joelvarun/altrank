r"""Parse a Python regex into a language that is guaranteed to be a superset.

altrank only ever asks one question about a pattern: "can it match here at
all?"  That makes a deliberate over-approximation safe.  Any construct altrank
cannot model exactly is replaced by something that accepts strictly more:

    zero-width assertions (^ $ \b \B \A \Z lookahead lookbehind)  ->  epsilon
    backreferences, unparseable tails                             ->  Sigma*
    repeat counts above REPEAT_CAP                                ->  unbounded

Dropping a constraint can only add strings, so if two over-approximated
languages cannot both match at a position then neither can the real ones.  The
reverse does not hold, which is why altrank errs toward reporting a conflict.
"""

import re

from . import charset as cs

REPEAT_CAP = 64

_CLASS_CACHE = {}
_FOLD_GROUPS = None


def _scan_class(pattern, ascii_flag):
    """Exact interval set for a built-in class, found by scanning codepoints."""
    key = (pattern, ascii_flag)
    hit = _CLASS_CACHE.get(key)
    if hit is None:
        flags = re.ASCII if ascii_flag else 0
        allchars = "".join(map(chr, range(0, cs.MAXCP + 1)))
        points = [m.start() for m in re.finditer(pattern, allchars, flags)]
        hit = cs.normalize((p, p) for p in points)
        _CLASS_CACHE[key] = hit
    return hit


def _fold_class(ch):
    """Every codepoint that case-folds together with ``ch``.

    Grouping by str.casefold is at least as coarse as the simple case folding
    the re module applies, so the result is a superset.
    """
    global _FOLD_GROUPS
    if _FOLD_GROUPS is None:
        groups = {}
        for c in range(cs.MAXCP + 1):
            groups.setdefault(chr(c).casefold(), []).append(c)
        _FOLD_GROUPS = groups
    members = _FOLD_GROUPS.get(ch.casefold(), [ord(ch)])
    return cs.normalize((c, c) for c in members)


EPS = ("eps",)
SIGMA_STAR = ("rep", ("set", cs.FULL), 0, None)


class ParseResult:
    """A parsed pattern plus the list of approximations that were applied."""

    def __init__(self, node, notes):
        self.node = node
        self.notes = notes

    @property
    def exact(self):
        return not self.notes


class _Parser:
    def __init__(self, pattern, flags):
        self.s = pattern
        self.i = 0
        self.flags = flags
        self.notes = []

    # -- flag helpers ----------------------------------------------------
    @property
    def ignorecase(self):
        return bool(self.flags & re.IGNORECASE)

    @property
    def dotall(self):
        return bool(self.flags & re.DOTALL)

    @property
    def verbose(self):
        return bool(self.flags & re.VERBOSE)

    @property
    def asciimode(self):
        return bool(self.flags & re.ASCII)

    def note(self, what):
        if what not in self.notes:
            self.notes.append(what)

    # -- scanning --------------------------------------------------------
    def eof(self):
        return self.i >= len(self.s)

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def take(self):
        ch = self.s[self.i]
        self.i += 1
        return ch

    def skip_ws(self):
        if not self.verbose:
            return
        while not self.eof():
            ch = self.peek()
            if ch in " \t\n\r\f\v":
                self.i += 1
            elif ch == "#":
                while not self.eof() and self.peek() != "\n":
                    self.i += 1
            else:
                return

    # -- grammar ---------------------------------------------------------
    def parse(self):
        node = self.parse_alt()
        if not self.eof():
            self.note("unparsed tail at offset %d" % self.i)
            node = ("cat", (node, SIGMA_STAR))
        return node

    def parse_alt(self):
        branches = [self.parse_cat()]
        while self.peek() == "|":
            self.take()
            branches.append(self.parse_cat())
        if len(branches) == 1:
            return branches[0]
        return ("alt", tuple(branches))

    def parse_cat(self):
        parts = []
        while True:
            self.skip_ws()
            ch = self.peek()
            if ch == "" or ch == "|" or ch == ")":
                break
            parts.append(self.parse_repeat())
        if not parts:
            return EPS
        if len(parts) == 1:
            return parts[0]
        return ("cat", tuple(parts))

    def parse_repeat(self):
        atom = self.parse_atom()
        while True:
            self.skip_ws()
            ch = self.peek()
            if ch == "*":
                self.take()
                lo, hi = 0, None
            elif ch == "+":
                self.take()
                lo, hi = 1, None
            elif ch == "?":
                self.take()
                lo, hi = 0, 1
            elif ch == "{":
                bounds = self._try_braces()
                if bounds is None:
                    break
                lo, hi = bounds
            else:
                break
            # Laziness and possessiveness change which match is chosen, never
            # whether one exists, so both collapse to the greedy form here.
            if self.peek() in ("?", "+"):
                self.take()
            if hi is not None and hi > REPEAT_CAP:
                self.note("repeat upper bound above cap treated as unbounded")
                hi = None
            if lo > REPEAT_CAP:
                self.note("repeat lower bound above cap relaxed")
                lo = 0
            atom = ("rep", atom, lo, hi)
        return atom

    def _try_braces(self):
        m = re.compile(r"\{(\d*)(,?)(\d*)\}").match(self.s, self.i)
        if not m or (not m.group(1) and not m.group(3)):
            return None
        self.i = m.end()
        lo_txt, comma, hi_txt = m.groups()
        lo = int(lo_txt) if lo_txt else 0
        if not comma:
            return lo, lo
        return lo, (int(hi_txt) if hi_txt else None)

    def parse_atom(self):
        ch = self.take()
        if ch == "(":
            return self.parse_group()
        if ch == "[":
            return ("set", self.parse_class())
        if ch == ".":
            if self.dotall:
                return ("set", cs.FULL)
            return ("set", cs.complement(cs.from_char("\n")))
        if ch == "\\":
            return self.parse_escape()
        if ch in "^$":
            self.note("anchor %r relaxed to epsilon" % ch)
            return EPS
        return ("set", self._literal(ch))

    def _literal(self, ch):
        if self.ignorecase:
            return _fold_class(ch)
        return cs.from_char(ch)

    def parse_group(self):
        if self.peek() == "?":
            self.take()
            kind = self.peek()
            if kind == ":":
                self.take()
            elif kind == "P":
                self.take()
                if self.peek() == "<":
                    while not self.eof() and self.take() != ">":
                        pass
                else:  # (?P=name) backreference
                    while not self.eof() and self.take() != ")":
                        pass
                    self.note("backreference relaxed to Sigma*")
                    return SIGMA_STAR
            elif kind in "=!":
                self.take()
                self._skip_to_close()
                self.note("lookahead relaxed to epsilon")
                return EPS
            elif kind == "<":
                self.take()
                if self.peek() in "=!":
                    self.take()
                    self._skip_to_close()
                    self.note("lookbehind relaxed to epsilon")
                    return EPS
                while not self.eof() and self.take() != ">":
                    pass
            elif kind == "#":
                self._skip_to_close()
                return EPS
            elif kind == "(":
                self._skip_to_close()
                self.note("conditional group relaxed to Sigma*")
                return SIGMA_STAR
            elif kind == ">":
                self.take()
            else:
                return self._parse_inline_flags()
        body = self.parse_alt()
        if self.peek() == ")":
            self.take()
        return body

    def _parse_inline_flags(self):
        letters = ""
        while self.peek() and self.peek() in "aiLmsux-":
            letters += self.take()
        added = 0
        for name, flag in (("i", re.IGNORECASE), ("s", re.DOTALL),
                           ("m", re.MULTILINE), ("x", re.VERBOSE),
                           ("a", re.ASCII)):
            if name in letters.split("-")[0]:
                added |= flag
        if self.peek() == ":":
            self.take()
            saved = self.flags
            self.flags |= added
            body = self.parse_alt()
            self.flags = saved
            if self.peek() == ")":
                self.take()
            return body
        if self.peek() == ")":
            self.take()
        self.flags |= added  # global inline flag
        return EPS

    def _skip_to_close(self):
        depth = 1
        while not self.eof():
            ch = self.take()
            if ch == "\\" and not self.eof():
                self.take()
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return

    def parse_escape(self):
        if self.eof():
            return ("set", cs.from_char("\\"))
        ch = self.take()
        named = self._named_class(ch)
        if named is not None:
            return ("set", named)
        if ch in "bBAZzG":
            self.note("assertion backslash-%s relaxed to epsilon" % ch)
            return EPS
        if ch.isdigit() and ch != "0":
            while self.peek().isdigit():
                self.take()
            self.note("backreference relaxed to Sigma*")
            return SIGMA_STAR
        return ("set", self._literal(self._escape_char(ch)))

    def _named_class(self, ch):
        base = {"d": r"\d", "D": r"\d", "w": r"\w", "W": r"\w",
                "s": r"\s", "S": r"\s"}.get(ch)
        if base is None:
            return None
        positive = _scan_class(base, self.asciimode)
        if ch in "DWS":
            return cs.complement(positive)
        return positive

    def _escape_char(self, ch):
        plain = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v",
                 "a": "\a", "0": "\0", "e": "\x1b"}
        if ch in plain:
            return plain[ch]
        if ch == "x":
            digits = ""
            while len(digits) < 2 and self.peek() in "0123456789abcdefABCDEF":
                digits += self.take()
            return chr(int(digits, 16)) if digits else "x"
        if ch in "uU":
            width = 4 if ch == "u" else 8
            digits = ""
            while len(digits) < width and self.peek() in "0123456789abcdefABCDEF":
                digits += self.take()
            try:
                return chr(int(digits, 16))
            except (ValueError, OverflowError):
                return ch
        if ch == "N" and self.peek() == "{":
            name = ""
            self.take()
            while not self.eof() and self.peek() != "}":
                name += self.take()
            if self.peek() == "}":
                self.take()
            import unicodedata
            try:
                return unicodedata.lookup(name)
            except KeyError:
                return "?"
        return ch

    def parse_class(self):
        negate = False
        if self.peek() == "^":
            self.take()
            negate = True
        acc = []
        first = True
        while not self.eof():
            ch = self.take()
            if ch == "]" and not first:
                break
            first = False
            if ch == "\\":
                if self.eof():
                    acc.append(cs.from_char("\\"))
                    break
                esc = self.take()
                named = self._named_class(esc)
                if named is not None:
                    acc.append(named)
                    continue
                # Inside a class, backslash-b is a backspace, not an assertion.
                lo_char = "\b" if esc == "b" else self._escape_char(esc)
            else:
                lo_char = ch
            if self.peek() == "-" and self.i + 1 < len(self.s) \
                    and self.s[self.i + 1] != "]":
                self.take()
                hi_raw = self.take()
                if hi_raw == "\\":
                    hi_char = self._escape_char(self.take())
                else:
                    hi_char = hi_raw
                acc.append(self._range(lo_char, hi_char))
            else:
                acc.append(self._literal(lo_char))
        out = cs.union(*acc) if acc else cs.EMPTY
        return cs.complement(out) if negate else out

    def _range(self, lo_char, hi_char):
        base = cs.from_range(ord(lo_char), ord(hi_char))
        if not self.ignorecase:
            return base
        if ord(hi_char) - ord(lo_char) > 1024:
            self.note("wide case-insensitive range widened to full range")
            return cs.FULL
        extra = [base]
        for cp in range(ord(lo_char), ord(hi_char) + 1):
            extra.append(_fold_class(chr(cp)))
        return cs.union(*extra)


def parse(pattern, flags=0):
    """Parse ``pattern`` into a superset language. Never raises on bad input."""
    p = _Parser(pattern, flags)
    try:
        node = p.parse()
    except Exception as exc:  # defensive: an unparsable pattern stays sound
        return ParseResult(SIGMA_STAR,
                           ["parse failed (%s), assumed Sigma*" % exc])
    return ParseResult(node, p.notes)
