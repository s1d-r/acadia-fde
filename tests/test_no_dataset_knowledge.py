"""The guard against learning the development dataset.

The requirement is that a CSV the app has never seen works with no code change.
The way that requirement quietly dies is one developer, one afternoon, reaching
for a column name they know is there. This test scans the source for the names
in the development file and fails if any of them appear.

The list is deliberately made of names specific enough that they cannot turn up
by accident in ordinary prose. Generic words that happen to also be columns in
that file - "country", "quantity", "description" - are not listed, because they
are also the normal English words for the roles a later slice has to infer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"

FORBIDDEN = [
    # Column names in the development file.
    "invoice_no",
    "invoice_type",
    "invoice_date",
    "invoice_year",
    "invoice_quarter",
    "invoice_month",
    "invoice_dow",
    "invoice_hour",
    "stock_code",
    "unit_price",
    "line_revenue",
    "line_type",
    "customer_id",
    "operator_note",
    "is_product_line",
    "is_revenue_line",
    "is_return",
    "is_complete_quarter",
    "is_identified_customer",
    "is_country_known",
    "has_negative_price",
    "is_extreme_quantity",
    # Column names as the original UCI Online Retail file spells them.
    "invoiceno",
    "stockcode",
    "unitprice",
    "customerid",
    "invoicedate",
    # The file itself.
    "online_retail",
    "onlineretail",
]

SOURCE_FILES = sorted(
    path
    for path in SOURCE_ROOT.rglob("*")
    if path.is_file() and "__pycache__" not in path.parts
)


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda path: path.name)
def test_source_file_names_no_column_of_the_development_dataset(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    found = [
        name for name in FORBIDDEN if re.search(rf"\b{re.escape(name)}\b", text)
    ]
    assert found == [], (
        f"{path} mentions {found}. Anything the engine needs to know about a "
        f"dataset must be measured from the file at ingest time."
    )


def test_the_guard_is_actually_scanning_something():
    """A scan that finds no files would pass forever without checking anything."""
    assert len(SOURCE_FILES) >= 10
