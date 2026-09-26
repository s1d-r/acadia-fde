"""Run evaluation suites from the command line.

    python -m insights.evaluation                 # every suite in eval/suites
    python -m insights.evaluation --suite eval/suites/library_loans.json
    python -m insights.evaluation --check         # validate suites, no model needed

Exits non zero if any case fails, so it can be wired into CI on a machine that
has a model available.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import db
from ..errors import InsightsError
from .runner import SuiteResult, Verdict, run_suite, truth_statement
from .suite import Suite, load_suite, suite_paths

DEFAULT_SUITE_DIR = Path("eval/suites")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insights-eval", description=__doc__)
    parser.add_argument("--suite", type=Path, action="append", dest="suites")
    parser.add_argument("--suite-dir", type=Path, default=DEFAULT_SUITE_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the suites and their truth SQL without asking the model",
    )
    args = parser.parse_args(argv)

    paths = args.suites or suite_paths(args.suite_dir)
    if not paths:
        print(f"No suites found in {args.suite_dir}", file=sys.stderr)
        return 2

    suites: list[Suite] = []
    for path in paths:
        if not path.exists():
            print(f"No such suite: {path}", file=sys.stderr)
            return 2
        suites.append(load_suite(path))

    if args.check:
        return _check(suites)

    failures = 0
    for suite in suites:
        try:
            result = run_suite(suite, con=db.session())
        except InsightsError as error:
            print(f"{suite.name}: could not run: {error.code}: {error.message}")
            failures += 1
            continue
        _report(result)
        failures += result.total - result.passed

    print()
    print("FAILED" if failures else "All suites passed")
    return 1 if failures else 0


def _check(suites: list[Suite]) -> int:
    """Validate every suite without a model.

    Loading already checks the shape. This also runs each truth query against
    the real file, which is what catches a truth query that stopped matching
    the data.
    """
    from ..ingest.service import ingest_csv

    problems = 0
    for suite in suites:
        con = db.session()
        if not Path(suite.csv).exists():
            print(f"{suite.name}: SKIPPED, {suite.csv} is not present")
            continue
        try:
            profile = ingest_csv(Path(suite.csv), con=con)
        except InsightsError as error:
            print(f"{suite.name}: cannot ingest {suite.csv}: {error.message}")
            problems += 1
            continue

        for case in suite.cases:
            if not case.truth_sql:
                continue
            statement = truth_statement(case.truth_sql, profile.table_name)
            try:
                con.execute(statement).fetchall()
            except Exception as error:  # noqa: BLE001 - reported, not raised
                print(f"{suite.name}/{case.id}: truth SQL failed: {error}")
                problems += 1
        print(f"{suite.name}: {len(suite.cases)} cases, {len(suite.refusal_cases)} refusals")

    print("FAILED" if problems else "All suites are well formed")
    return 1 if problems else 0


def _report(result: SuiteResult) -> None:
    print()
    print(f"{result.suite.name}  ({result.suite.csv})")
    print("-" * 78)
    if result.skipped:
        print(f"  SKIPPED: {result.skipped_reason}")
        return
    for case in result.results:
        mark = "PASS" if case.ok else "FAIL"
        print(f"  {mark:<5} {case.case.id:<28} {case.seconds:5.1f}s  {case.verdict.value}")
        if not case.ok:
            print(f"        {case.detail}")
    print(f"  {result.passed}/{result.total} passed")

    dangerous = [r for r in result.results if r.verdict is Verdict.ANSWERED_THE_UNANSWERABLE]
    if dangerous:
        print(f"  WARNING: {len(dangerous)} unanswerable question(s) were answered")


if __name__ == "__main__":
    raise SystemExit(main())
