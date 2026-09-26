"""Tests for the schema context: the description the planner is given.

The main fixture is a library loans file - loan references, branches, late fees.
It shares no column name, no type layout and no subject matter with the
development dataset, which is the point: this is the module the "any CSV"
requirement rests on, so it is tested against a CSV it has never seen.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from insights.config import Settings, get_settings
from insights.context import build_context, render_for_prompt
from insights.context.roles import ColumnRole
from insights.models.profile import (
    ColumnProfile,
    LogicalType,
    TableProfile,
    TypeInference,
)


@pytest.fixture
def loans(profile_for):
    return build_context(profile_for("library_loans.csv"))


@pytest.fixture
def loan_roles(loans):
    return {column.name: column.role for column in loans.columns}


# --- roles, inferred from measurements only --------------------------------


def test_a_column_with_one_value_per_row_is_an_identifier(loan_roles):
    assert loan_roles["Loan Reference"] is ColumnRole.IDENTIFIER


def test_a_date_column_is_temporal(loan_roles):
    assert loan_roles["Borrowed On"] is ColumnRole.TEMPORAL


def test_many_repeated_short_values_are_a_key(loan_roles):
    """60 codes across 300 rows: it names a group, not a row."""
    assert loan_roles["Catalogue Id"] is ColumnRole.KEY


def test_few_repeated_values_are_a_category(loan_roles):
    assert loan_roles["Branch Library"] is ColumnRole.CATEGORY


def test_numbers_are_measures(loan_roles):
    assert loan_roles["Days Kept"] is ColumnRole.MEASURE
    assert loan_roles["Late Fee"] is ColumnRole.MEASURE


def test_a_zero_one_column_is_a_flag_not_a_measure(loan_roles):
    """Summing a flag is meaningless; the role has to stop the planner trying."""
    assert loan_roles["Renewed"] is ColumnRole.FLAG


def test_long_values_are_free_text(loan_roles):
    assert loan_roles["Borrower Comment"] is ColumnRole.FREE_TEXT


def test_an_empty_column_is_unknown(loan_roles):
    assert loan_roles["Reserved Slot"] is ColumnRole.UNKNOWN


def test_every_role_carries_the_measurement_it_came_from(loans):
    for column in loans.columns:
        assert column.role_evidence


def test_a_distinct_rate_from_too_few_rows_is_not_believed(profile_for):
    """In a five-row file every column looks like a key. It is a coincidence.

    Without a minimum number of values, "days hired" - five rows, five
    different whole numbers - is indistinguishable from a primary key.
    """
    context = build_context(profile_for("rentals.csv"))
    roles = {column.name: column.role for column in context.columns}

    assert roles["Days Hired"] is ColumnRole.MEASURE
    assert roles["Booking Ref"] is not ColumnRole.IDENTIFIER


def test_the_same_column_is_an_identifier_once_there_is_enough_of_it(loans):
    loan_reference = next(c for c in loans.columns if c.name == "Loan Reference")
    assert loan_reference.profile.non_null_count == 300
    assert loan_reference.role is ColumnRole.IDENTIFIER


# --- caveats: what makes refusing possible ---------------------------------


def test_a_file_with_no_date_column_says_so(profile_for):
    """The single most useful caveat: it is what turns a question about growth
    into a refusal instead of a guess."""
    context = build_context(profile_for("awkward_names.csv"))
    assert any("no date or time column" in caveat for caveat in context.caveats)


def test_a_file_with_no_number_column_says_so():
    context = build_context(_synthetic_profile(_text_column("Label", distinct=3)))
    assert any("no numeric column" in caveat for caveat in context.caveats)


def test_mostly_empty_columns_are_called_out(loans):
    caveat = next(c for c in loans.caveats if "mostly empty" in c)
    assert '"Borrower Comment"' in caveat
    assert '"Reserved Slot"' in caveat


def test_a_file_with_no_header_says_the_names_mean_nothing(profile_for):
    context = build_context(profile_for("ragged.csv"))
    assert any("No header row" in caveat for caveat in context.caveats)


def test_untyped_columns_are_called_out():
    profile = _synthetic_profile(
        _text_column("Label", distinct=3),
        type_inference=TypeInference.ALL_TEXT_FALLBACK,
    )
    context = build_context(profile)
    assert any("types could not be inferred" in c for c in context.caveats)


def test_a_dataset_that_is_fine_has_no_alarming_caveats(loans):
    assert not any("no date" in caveat for caveat in loans.caveats)
    assert not any("No header" in caveat for caveat in loans.caveats)


# --- the column list is the whitelist --------------------------------------


def test_column_names_are_exactly_what_the_planner_may_reference(loans):
    assert loans.column_names == [
        "Loan Reference",
        "Borrowed On",
        "Catalogue Id",
        "Branch Library",
        "Days Kept",
        "Late Fee",
        "Renewed",
        "Borrower Comment",
        "Reserved Slot",
    ]


def test_a_file_wider_than_the_budget_is_truncated_and_says_so(monkeypatch):
    monkeypatch.setenv("INSIGHTS_MAX_CONTEXT_COLUMNS", "3")
    get_settings.cache_clear()

    profile = _synthetic_profile(
        *[_text_column(f"Field {i}", distinct=3) for i in range(10)]
    )
    context = build_context(profile)

    assert len(context.columns) == 3
    assert context.omitted_column_count == 7
    assert any("only the first 3 are described" in c for c in context.caveats)


# --- rendering --------------------------------------------------------------


def test_every_column_appears_in_the_rendered_prompt(loans):
    rendered = render_for_prompt(loans)
    for name in loans.column_names:
        assert f'"{name}"' in rendered


def test_rendering_is_deterministic(loans):
    assert render_for_prompt(loans) == render_for_prompt(loans)


def test_rendering_explains_the_role_words_it_uses(loans):
    rendered = render_for_prompt(loans)
    used = {column.role.value for column in loans.columns}
    for role in used:
        assert f"{role} = " in rendered


def test_categories_are_rendered_with_their_counts(loans):
    """How lopsided a column is matters before anyone groups by it."""
    rendered = render_for_prompt(loans)
    assert "'Central' (75)" in rendered


def test_measures_are_rendered_with_their_range(loans):
    assert "from 1 to 28" in render_for_prompt(loans)


def test_caveats_are_rendered(loans):
    rendered = render_for_prompt(loans)
    assert "Important facts about this file:" in rendered
    for caveat in loans.caveats:
        assert caveat in rendered


def test_rendering_survives_a_column_named_like_sql(profile_for):
    context = build_context(profile_for("awkward_names.csv"))
    assert '"drop table t; --"' in render_for_prompt(context)


# --- helpers ----------------------------------------------------------------


def _text_column(name: str, *, distinct: int) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        position=0,
        sql_type="VARCHAR",
        logical_type=LogicalType.TEXT,
        non_null_count=100,
        null_count=0,
        null_rate=0.0,
        distinct_count=distinct,
        distinct_rate=distinct / 100,
        is_unique=False,
        mean_length=5.0,
        max_length=5,
    )


def _synthetic_profile(
    *columns: ColumnProfile,
    type_inference: TypeInference = TypeInference.AUTOMATIC,
) -> TableProfile:
    """A profile assembled by hand, for shapes no small fixture file produces."""
    numbered = [
        column.model_copy(update={"position": position})
        for position, column in enumerate(columns)
    ]
    return TableProfile(
        dataset_id="synthetic",
        table_name="ds_synthetic",
        source_filename="synthetic.csv",
        source_bytes=1,
        row_count=100,
        column_count=len(numbered),
        ingested_at=datetime.now(timezone.utc),
        type_inference=type_inference,
        columns=numbered,
    )


def test_settings_used_by_role_inference_are_configuration_not_constants():
    """Every threshold is tunable without touching the inference code."""
    settings = Settings()
    assert settings.identifier_distinct_rate < 1.0
    assert settings.identifier_min_values > 1
    assert settings.category_max_distinct > 0


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (0.0, "0%"),
        (0.0001, "<1%"),
        (0.25, "25%"),
        (0.998, ">99%"),
        (1.0, "100%"),
    ],
)
def test_rates_never_round_away_the_thing_that_matters(rate, expected):
    """A column that is 99.8% empty must not print as "100% empty" beside five
    example values, and one with a single stray value must not print as "0%"."""
    from insights.context.formatting import percent

    assert percent(rate) == expected
