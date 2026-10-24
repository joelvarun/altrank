"""Command line entry point: analyse and reorder a pygments lexer.

    python -m altrank.cli --lexer pygments.lexers.python.PythonLexer \
                          --corpus "C:/Python313/Lib/*.py" --limit 14
"""

import argparse
import glob
import importlib
import json
import sys
import time

from . import optimize

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")


def load_lexer(path):
    module_name, _, class_name = path.rpartition(".")
    if not module_name:
        raise SystemExit("lexer must be given as module.ClassName")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def read_corpus(patterns, limit):
    files = []
    for pattern in patterns:
        files.extend(sorted(glob.glob(pattern, recursive=True)))
    if not files:
        raise SystemExit("no files matched %s" % (patterns,))
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


def build_parser():
    parser = argparse.ArgumentParser(
        prog="altrank",
        description="Reorder an ordered regex rule list for speed without "
                    "changing what it matches.")
    parser.add_argument("--lexer", required=True,
                        help="pygments lexer as module.ClassName")
    parser.add_argument("--corpus", required=True, nargs="+",
                        help="glob(s) of files to profile against")
    parser.add_argument("--limit", type=int, default=0,
                        help="use at most this many files (0 means all)")
    parser.add_argument("--cost-model", choices=("measured", "uniform"),
                        default="uniform",
                        help="uniform counts attempts, measured times them")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="write the full report to this path")
    parser.add_argument("--top", type=int, default=8,
                        help="how many states to print")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the token stream equivalence check")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    lexer_cls = load_lexer(args.lexer)
    corpus, files = read_corpus(args.corpus, args.limit)
    print("lexer   %s" % args.lexer)
    print("corpus  %d files, %d characters" % (len(files), len(corpus)))
    sys.stdout.flush()

    started = time.perf_counter()
    table, reports = optimize.optimize_lexer(lexer_cls, corpus,
                                             cost_model=args.cost_model)
    analysis = time.perf_counter() - started
    summary = optimize.summarize(reports)
    unit = "attempts" if args.cost_model == "uniform" else "microseconds"

    print("analysis took %.1fs" % analysis)
    print()
    print("%-28s %4s %9s %10s %10s %9s %6s" % (
        "state", "n", "events", "before", "after", "floor", "cert"))
    ordered = sorted(reports, key=lambda r: -r.observations)
    for report in ordered[:args.top]:
        events = report.observations or 1
        print("%-28s %4d %9d %10.2f %10.2f %9.2f %6s" % (
            report.state[:28], report.n, report.observations,
            report.baseline_cost / events, report.optimized_cost / events,
            report.floor / events,
            "yes" if report.schedule.certified_optimal else "no"))
    print()
    print("rule lists reordered      %d" % summary["states"])
    print("rules analysed            %d" % summary["rules"])
    print("ordering constraints      %d conflicting pairs" %
          summary["conflict_pairs"])
    print("rules over-approximated   %d" % summary["approximated_rules"])
    print("states certified optimal  %d of %d" %
          (summary["certified_states"], summary["states"]))
    print("cost per match event      %.2f -> %.2f %s (floor %.2f)" % (
        summary["baseline_per_event"], summary["optimized_per_event"],
        unit, summary["floor_per_event"]))
    print("modelled speedup          %.2fx" % summary["speedup"])

    if not args.no_verify:
        same, count, diff = optimize.verify_equivalence(lexer_cls, table,
                                                        corpus)
        if same:
            print("equivalence               identical, %d tokens" % count)
        else:
            print("equivalence               MISMATCH at %s" % (diff,))
            return 1

    if args.json_out:
        payload = {
            "lexer": args.lexer,
            "files": len(files),
            "characters": len(corpus),
            "cost_model": args.cost_model,
            "summary": summary,
            "states": [{
                "state": r.state,
                "rules": r.n,
                "events": r.observations,
                "order": list(r.order),
                "before": r.baseline_cost,
                "after": r.optimized_cost,
                "floor": r.floor,
                "conflicts": len(r.conflicts),
                "certified": r.schedule.certified_optimal,
            } for r in ordered],
        }
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print("report written to %s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
