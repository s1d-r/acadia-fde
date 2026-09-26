"""Converting database values into values that survive JSON.

Used by the profiler and by the executor. It lives on its own because the two
must agree: a timestamp that renders one way in a schema description and another
way in a result is a discrepancy someone will eventually chase for an hour.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

#: What we are willing to put in a JSON document.
Scalar = str | int | float | bool | None


def to_jsonable(value: object) -> Scalar:
    """Convert one database value.

    Timestamps become ISO 8601 strings and decimals become floats, so the same
    value can be stored, returned over HTTP and rendered into a prompt without
    a second conversion anywhere.

    Floats are a deliberate loss of precision on ``DECIMAL``. The alternative -
    strings - would mean every consumer parsing numbers back out before they
    could add them up, and nothing here is doing accounting to the penny.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    return str(value)
