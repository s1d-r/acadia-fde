"""Turning a profile into the description the planner sees.

Two steps, kept apart on purpose:

``build_context`` decides *what* to say - roles, caveats, which columns fit.
``render_for_prompt`` decides *how* to say it - the exact text.

They are separate because the structured context is also what the validator and
the API use, and because the wording of a prompt gets rewritten far more often
than the decision about what belongs in it.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..models.context import ColumnContext, SchemaContext
from ..models.profile import TableProfile, TypeInference
from .formatting import percent
from .roles import ColumnRole, infer_role


def build_context(
    profile: TableProfile, *, settings: Settings | None = None
) -> SchemaContext:
    """Interpret a profile. No database access: everything needed was measured
    at ingest time."""
    settings = settings or get_settings()

    kept = profile.columns[: settings.max_context_columns]
    columns = [
        ColumnContext(
            profile=column,
            role=(assessment := infer_role(column, settings=settings)).role,
            role_evidence=assessment.evidence,
        )
        for column in kept
    ]

    return SchemaContext(
        dataset_id=profile.dataset_id,
        table_name=profile.table_name,
        row_count=profile.row_count,
        column_count=profile.column_count,
        columns=columns,
        omitted_column_count=len(profile.columns) - len(kept),
        caveats=_caveats(profile, columns, settings=settings),
    )


def _caveats(
    profile: TableProfile,
    columns: list[ColumnContext],
    *,
    settings: Settings,
) -> list[str]:
    """Facts about the file that change what can honestly be answered.

    These are written for the planner to act on. "There is no date column" is
    the difference between refusing a question about growth and inventing an
    answer to it.
    """
    caveats: list[str] = []

    if not profile.header_detected:
        caveats.append(
            "No header row was found in this file, so the column names are "
            "positional and carry no meaning. Do not read meaning into them."
        )

    if profile.type_inference is TypeInference.ALL_TEXT_FALLBACK:
        caveats.append(
            "Column types could not be inferred; every column is text. "
            "Arithmetic and date comparisons need an explicit cast, and a cast "
            "may fail on some rows."
        )

    roles = {column.role for column in columns}

    if ColumnRole.TEMPORAL not in roles:
        caveats.append(
            "There is no date or time column. Questions about periods, growth, "
            "trends or 'between two quarters' cannot be answered from this data."
        )

    if ColumnRole.MEASURE not in roles:
        caveats.append(
            "There is no numeric column to aggregate. Questions asking for a "
            "total, an average or a ranking by value cannot be answered."
        )

    mostly_empty = [
        column.name
        for column in columns
        if column.profile.null_rate >= settings.high_null_rate
    ]
    if mostly_empty:
        caveats.append(
            "These columns are mostly empty, so any figure grouped or filtered "
            "by them covers only part of the data: "
            + ", ".join(f'"{name}"' for name in mostly_empty)
            + "."
        )

    if profile.row_count and len(columns) < profile.column_count:
        caveats.append(
            f"This file has {profile.column_count} columns and only the first "
            f"{len(columns)} are described here."
        )

    return caveats


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

#: What each role means, in the prompt's own words. Included with the context so
#: the vocabulary always travels with the data it describes.
_ROLE_LEGEND = {
    # The clause about deriving periods is load-bearing, not decoration. Without
    # it the model refused "total late fees in March" on a file with a date
    # column, on the grounds that no column was named after a month. Saying so
    # in the legend, beside the columns, works where the same sentence buried in
    # the system prompt's rules did not.
    ColumnRole.TEMPORAL: (
        "a date or time; any day, month, quarter or year can be derived from it"
    ),
    ColumnRole.FLAG: "a two-state flag",
    ColumnRole.IDENTIFIER: "names one row",
    ColumnRole.KEY: "names a group of rows",
    ColumnRole.CATEGORY: "a small set of repeated values",
    ColumnRole.FREE_TEXT: "long text",
    ColumnRole.MEASURE: "a number to aggregate",
    ColumnRole.UNKNOWN: "unclear",
}


def render_for_prompt(context: SchemaContext) -> str:
    """Render the context as the text block the planner is given.

    Deterministic: the same profile renders to the same characters every time.
    A prompt that varies between runs makes a wrong answer impossible to
    reproduce, which is the thing you most need when one appears.
    """
    lines = [
        f'Table: "{context.table_name}"',
        f"Rows: {context.row_count:,}",
        f"Columns: {context.column_count}",
        "",
        "Columns, as: \"name\" TYPE [role] facts | examples",
        "",
    ]
    lines.extend(f"  {_render_column(column)}" for column in context.columns)

    used_roles = sorted({column.role for column in context.columns})
    lines += [
        "",
        "Roles are inferred from the data, not from the column names: "
        + "; ".join(f"{role.value} = {_ROLE_LEGEND[role]}" for role in used_roles)
        + ".",
    ]

    if context.caveats:
        lines += ["", "Important facts about this file:"]
        lines.extend(f"  - {caveat}" for caveat in context.caveats)

    return "\n".join(lines)


def _render_column(column: ColumnContext) -> str:
    profile = column.profile
    facts = [f"{profile.distinct_count:,} distinct", f"{percent(profile.null_rate)} empty"]

    if profile.min_value is not None and profile.max_value is not None:
        facts.append(f"from {profile.min_value} to {profile.max_value}")
    if profile.mean_value is not None:
        facts.append(f"mean {profile.mean_value:,.2f}")

    if column.role is ColumnRole.TEMPORAL:
        # Repeated on the column line, not only in the legend below. The
        # legend alone was enough for "which month", and not enough for
        # "between two quarters": the harder the question, the closer the
        # affordance has to sit to the thing it applies to.
        facts.append("can be filtered or grouped by day, month, quarter or year")

    rendered = (
        f'"{profile.name}" {profile.sql_type} [{column.role.value}] '
        + ", ".join(facts)
    )

    examples = _render_examples(column)
    return f"{rendered} | {examples}" if examples else rendered


def _render_examples(column: ColumnContext) -> str:
    """Example values, with counts only where the counts carry information.

    For a category the counts show how lopsided the column is - that one value
    covers 95% of the rows is worth knowing before grouping by it. For an
    identifier the counts are all 1 and say nothing.
    """
    samples = column.profile.sample_values
    if not samples:
        return ""

    if column.role in (ColumnRole.CATEGORY, ColumnRole.FLAG):
        rendered = ", ".join(f"'{s.value}' ({s.count:,})" for s in samples)
    else:
        rendered = ", ".join(f"'{s.value}'" for s in samples)
    return f"e.g. {rendered}"

