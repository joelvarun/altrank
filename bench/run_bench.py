"""Benchmark altrank against the shipped pygments rule order and draw the chart.

Every corpus here ships with CPython, so the numbers can be reproduced on any
machine with a stock interpreter and pygments installed:

    python bench/run_bench.py

The script writes docs/before_after.png and docs/results.json.  Nothing in
either file is hand written; both come from this run.
"""

import argparse
import glob
import importlib
import json
import os
import sys
import sysconfig
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from altrank import optimize, profile

STDLIB = sysconfig.get_paths()["stdlib"]
INCLUDE = sysconfig.get_paths()["include"]

PREFIX = os.path.dirname(STDLIB)

# Each target lists candidate globs; the first one that matches any file wins,
# and a target with no corpus on this machine is skipped rather than faked.
TARGETS = [
    ("Python", "pygments.lexers.python.PythonLexer",
     [[os.path.join(STDLIB, "*.py")]], 14),
    ("C", "pygments.lexers.c_cpp.CLexer",
     [[os.path.join(INCLUDE, "*.h")]], 0),
    ("HTML", "pygments.lexers.html.HtmlLexer",
     [[os.path.join(STDLIB, "idlelib", "help.html")],
      [os.path.join(PREFIX, "Doc", "html", "*.html")]], 12),
    ("CSS", "pygments.lexers.css.CssLexer",
     [[os.path.join(PREFIX, "Doc", "html", "_static", "*.css")],
      [os.path.join(PREFIX, "**", "*.css")]], 0),
]

REPEATS = 5


def load(path):
    module_name, _, class_name = path.rpartition(".")
    return getattr(importlib.import_module(module_name), class_name)


def read_corpus(patterns, limit):
    files = []
    for pattern in patterns:
        files.extend(sorted(glob.glob(pattern, recursive=True)))
    if limit:
        files = files[:limit]
    chunks = []
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                chunks.append(handle.read())
        except OSError:
            continue
    return "\n".join(chunks), files


def time_lexers(lexer_a, lexer_b, corpus, repeats=REPEATS):
    """Interleave the two configurations and keep the best run of each.

    Round robin plus minimum-of-n keeps a slow moment on the machine from
    showing up as a difference between the two orderings.
    """
    best = [None, None]
    for _ in range(repeats):
        for slot, lexer in ((0, lexer_a), (1, lexer_b)):
            start = time.perf_counter()
            count = 0
            for _token in lexer.get_tokens_unprocessed(corpus):
                count += 1
            elapsed = time.perf_counter() - start
            if best[slot] is None or elapsed < best[slot]:
                best[slot] = elapsed
    return best[0], best[1]


def count_trials(lexer_cls, table, corpus):
    """Total regex attempts a token table needs for the whole corpus."""
    lexer = lexer_cls()
    if table is not None:
        lexer._tokens = table
    counted, stats = profile.instrument(lexer)
    lexer._tokens = counted
    for _token in lexer.get_tokens_unprocessed(corpus):
        pass
    return profile.total_trials(stats), profile.total_wins(stats)


def pick_corpus(candidates, limit):
    for patterns in candidates:
        corpus, files = read_corpus(patterns, limit)
        if corpus.strip():
            return corpus, files
    return "", []


def run_target(name, lexer_path, candidates, limit):
    from pygments.lexer import RegexLexer

    lexer_cls = load(lexer_path)
    if not issubclass(lexer_cls, RegexLexer):
        print("  skipped %s: %s is not a RegexLexer" % (name, lexer_path))
        return None
    corpus, files = pick_corpus(candidates, limit)
    if not corpus:
        print("  skipped %s: no corpus matched on this machine" % name)
        return None
    print("%s: %d files, %d characters" % (name, len(files), len(corpus)))
    sys.stdout.flush()

    started = time.perf_counter()
    table, reports = optimize.optimize_lexer(lexer_cls, corpus,
                                             cost_model="uniform")
    analysis = time.perf_counter() - started
    summary = optimize.summarize(reports)

    same, tokens, diff = optimize.verify_equivalence(lexer_cls, table, corpus)
    if not same:
        raise SystemExit("%s: reordering changed the token stream at %s"
                         % (name, diff))

    trials_before, events = count_trials(lexer_cls, None, corpus)
    trials_after, _ = count_trials(lexer_cls, table, corpus)

    plain = lexer_cls()
    fast = lexer_cls()
    fast._tokens = table
    t_plain, t_fast = time_lexers(plain, fast, corpus)

    kb = len(corpus) / 1024.0
    result = {
        "name": name,
        "lexer": lexer_path,
        "files": len(files),
        "characters": len(corpus),
        "tokens": tokens,
        "match_events": events,
        "analysis_seconds": round(analysis, 2),
        "trials_before": trials_before,
        "trials_after": trials_after,
        "trials_per_token_before": trials_before / events,
        "trials_per_token_after": trials_after / events,
        "trial_reduction": trials_before / trials_after,
        "seconds_before": t_plain,
        "seconds_after": t_fast,
        "throughput_before_kbs": kb / t_plain,
        "throughput_after_kbs": kb / t_fast,
        "wall_speedup": t_plain / t_fast,
        "equivalent_token_stream": same,
        "states_reordered": summary["states"],
        "rules_analysed": summary["rules"],
        "conflict_pairs": summary["conflict_pairs"],
        "approximated_rules": summary["approximated_rules"],
        "certified_states": summary["certified_states"],
        "modelled_floor_per_event": summary["floor_per_event"],
    }
    print("  attempts/token %.2f -> %.2f (%.2fx), wall %.3fs -> %.3fs "
          "(%.2fx), tokens identical: %s"
          % (result["trials_per_token_before"],
             result["trials_per_token_after"], result["trial_reduction"],
             t_plain, t_fast, result["wall_speedup"], same))
    sys.stdout.flush()
    return result


def draw_chart(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    names = [r["name"] for r in results]
    x = np.arange(len(names))
    width = 0.38
    before_color = "#8c8c8c"
    after_color = "#1f6feb"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.4, 5.2))

    b1 = [r["trials_per_token_before"] for r in results]
    a1 = [r["trials_per_token_after"] for r in results]
    top1 = max(b1) * 1.42
    ax1.bar(x - width / 2, b1, width, label="pygments rule order",
            color=before_color)
    ax1.bar(x + width / 2, a1, width, label="altrank order", color=after_color)
    ax1.set_ylabel("regex attempts per matched token")
    ax1.set_title("Work per token (lower is better)")
    for i, (bv, av) in enumerate(zip(b1, a1)):
        ax1.text(i - width / 2, bv + top1 * 0.012, "%.1f" % bv, ha="center",
                 va="bottom", fontsize=9, color="#333333")
        ax1.text(i + width / 2, av + top1 * 0.012, "%.1f" % av, ha="center",
                 va="bottom", fontsize=9, color=after_color)
        ax1.text(i, max(bv, av) + top1 * 0.072, "%.1fx fewer" % (bv / av),
                 ha="center", fontsize=10, color="#111111", weight="bold")
    ax1.set_ylim(0, top1)

    b2 = [r["throughput_before_kbs"] for r in results]
    a2 = [r["throughput_after_kbs"] for r in results]
    top2 = max(a2) * 1.42
    ax2.bar(x - width / 2, b2, width, label="pygments rule order",
            color=before_color)
    ax2.bar(x + width / 2, a2, width, label="altrank order", color=after_color)
    ax2.set_ylabel("lexing throughput (KB per second)")
    ax2.set_title("Measured throughput (higher is better)")
    for i, (bv, av) in enumerate(zip(b2, a2)):
        ax2.text(i - width / 2, bv + top2 * 0.012, "%.0f" % bv, ha="center",
                 va="bottom", fontsize=9, color="#333333")
        ax2.text(i + width / 2, av + top2 * 0.012, "%.0f" % av, ha="center",
                 va="bottom", fontsize=9, color=after_color)
        ax2.text(i, max(bv, av) + top2 * 0.072, "%.2fx faster" % (av / bv),
                 ha="center", fontsize=10, color="#111111", weight="bold")
    ax2.set_ylim(0, top2)

    for axis in (ax1, ax2):
        axis.set_xticks(x)
        axis.set_xticklabels(names)
        axis.legend(loc="upper center", frameon=False, fontsize=9,
                    ncol=2, bbox_to_anchor=(0.5, 1.005))
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.grid(axis="y", color="#dddddd", linewidth=0.7)
        axis.set_axisbelow(True)

    fig.suptitle("altrank: optimal safe ordering of pygments rule lists "
                 "(token streams verified identical)", fontsize=13)
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.savefig(path, dpi=150)
    print("chart written to %s" % path)


def main():
    parser = argparse.ArgumentParser(description="run the altrank benchmark")
    parser.add_argument("--only", nargs="*", default=None,
                        help="restrict to these target names")
    parser.add_argument("--redraw", action="store_true",
                        help="redraw the chart from docs/results.json")
    args = parser.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs = os.path.join(here, "docs")
    os.makedirs(docs, exist_ok=True)

    if args.redraw:
        with open(os.path.join(docs, "results.json"), encoding="utf-8") as fh:
            saved = json.load(fh)
        draw_chart(saved["results"], os.path.join(docs, "before_after.png"))
        return

    results = []
    for name, lexer_path, candidates, limit in TARGETS:
        if args.only and name not in args.only:
            continue
        got = run_target(name, lexer_path, candidates, limit)
        if got:
            results.append(got)
    if not results:
        raise SystemExit("no targets produced results")

    payload = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "repeats": REPEATS,
        "timing": "interleaved round robin, minimum of %d runs" % REPEATS,
        "results": results,
    }
    with open(os.path.join(docs, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    draw_chart(results, os.path.join(docs, "before_after.png"))

    print()
    print("%-7s %14s %10s %10s %8s" % ("target", "attempts/token", "after",
                                       "reduction", "wall"))
    for r in results:
        print("%-7s %14.2f %10.2f %9.2fx %7.2fx"
              % (r["name"], r["trials_per_token_before"],
                 r["trials_per_token_after"], r["trial_reduction"],
                 r["wall_speedup"]))


if __name__ == "__main__":
    main()
