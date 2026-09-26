"""Command line entry point.

A thin wrapper so each slice can be demonstrated without a running server.
Everything it does, it does by calling the same functions the API will call.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, registry
from .answers import answer_question
from .context import build_context, render_for_prompt
from .errors import InsightsError
from .ingest.service import ingest_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insights", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="load a CSV and print its profile")
    ingest.add_argument("path", type=Path)

    commands.add_parser("list", help="list ingested datasets")

    show = commands.add_parser("show", help="print a stored profile")
    show.add_argument("dataset_id")

    context = commands.add_parser(
        "context", help="print the schema description the planner will be given"
    )
    context.add_argument("dataset_id")
    context.add_argument(
        "--json",
        action="store_true",
        help="print the structured context instead of the prompt text",
    )

    ask = commands.add_parser("ask", help="ask a question about a dataset")
    ask.add_argument("dataset_id")
    ask.add_argument("question")
    ask.add_argument(
        "--json", action="store_true", help="print the full answer as JSON"
    )

    args = parser.parse_args(argv)
    con = db.session()

    try:
        if args.command == "ingest":
            profile = ingest_csv(args.path, con=con)
            print(profile.model_dump_json(indent=2))
        elif args.command == "list":
            for summary in registry.list_datasets(con=con):
                print(
                    f"{summary.dataset_id}  {summary.row_count:>10,} rows  "
                    f"{summary.column_count:>3} cols  {summary.source_filename}"
                )
        elif args.command == "show":
            print(registry.get_profile(args.dataset_id, con=con).model_dump_json(indent=2))
        elif args.command == "context":
            schema = build_context(registry.get_profile(args.dataset_id, con=con))
            print(schema.model_dump_json(indent=2) if args.json else render_for_prompt(schema))
        elif args.command == "ask":
            answer = answer_question(args.dataset_id, args.question, con=con)
            if args.json:
                print(answer.model_dump_json(indent=2))
            else:
                _print_answer(answer)
    except InsightsError as error:
        # Expected failures print their message, not a traceback. Same rule as
        # the API: the caller is told what went wrong, never how.
        print(f"{error.code}: {error.message}", file=sys.stderr)
        if error.details:
            print(f"  details: {error.details}", file=sys.stderr)
        return 1

    return 0


def _print_answer(answer) -> None:
    """Show a refusal as an answer, not as a failure.

    A refusal prints its reason and nothing else. There is no empty table and no
    error marker, because nothing went wrong: the question could not be answered
    from this data, and that is the answer.
    """
    if answer.is_refusal:
        print(f"Cannot answer: {answer.reason}")
        return

    print(answer.reason)
    print()
    print(answer.sql)
    print()

    result = answer.result
    widths = [
        max(len(str(name)), *(len(str(row[i])) for row in result.rows))
        if result.rows
        else len(str(name))
        for i, name in enumerate(result.columns)
    ]
    print("  ".join(str(n).ljust(w) for n, w in zip(result.columns, widths)))
    print("  ".join("-" * w for w in widths))
    for row in result.rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))

    print()
    note = f"{result.row_count} rows in {result.duration_ms} ms"
    if result.truncated:
        note += " (truncated)"
    print(f"{note}; planned by {answer.model} in {answer.planning_ms} ms")


if __name__ == "__main__":
    raise SystemExit(main())
