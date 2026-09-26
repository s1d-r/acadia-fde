"""The prompt, and the shape the model must answer in.

Nothing here mentions a column, a table, a business or a dataset. Everything the
model learns about the data arrives at runtime in the rendered schema context.
That is not a stylistic preference: a prompt that names a column is a prompt
that works on one file.
"""

from __future__ import annotations

from typing import Any

from ..context import render_for_prompt
from ..models.context import SchemaContext

#: The shape the model must return. Ollama constrains decoding to this, so the
#: model cannot wrap its answer in prose or apologise before the JSON.
#:
#: All three fields are required rather than making ``sql`` conditional.
#: Constrained decoding handles a fixed shape far more reliably than a
#: conditional one, and an empty string is an unambiguous "no query".
#:
#: The field order is load-bearing. Constrained decoding emits the properties in
#: the order they appear here, so putting ``reason`` before ``sql`` makes the
#: model state in words what it is about to compute and then write SQL with that
#: sentence already in its context. Ordered the other way, the first version of
#: this returned good SQL and an empty reason: having already written the query,
#: the model had nothing left to say.
PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answerable": {
            "type": "boolean",
            "description": "True only if the question can be answered from the "
            "columns listed. False otherwise.",
        },
        "reason": {
            "type": "string",
            # A minimum length, because the first version of this returned an
            # empty string here whenever the question was answerable: an empty
            # string satisfies "type: string", and it is the cheapest token path
            # available. Ollama enforces the constraint during decoding, so the
            # model cannot take that path even when told to. The planner still
            # substitutes a default if a provider ignores the constraint.
            "minLength": 15,
            "description": "If answerable, one sentence describing what the query "
            "you are about to write computes. If not, one sentence naming exactly "
            "what is missing from the data.",
        },
        "sql": {
            "type": "string",
            "description": "The DuckDB SELECT statement. Empty string if not answerable.",
        },
    },
    "required": ["answerable", "reason", "sql"],
}


SYSTEM_PROMPT = """\
You translate a question about one table of data into a single read-only SQL \
query for DuckDB.

You will be given a description of that table which was measured from the data \
file itself. It lists every column that exists. There are no other tables and \
no other columns.

Rules:

1. Use only the columns listed. Never invent a column. Never assume a column \
exists because the question implies it should.
2. Write every column name exactly as it is given, wrapped in double quotes. \
The names may contain spaces, punctuation or accents.
3. Write the table name exactly as given, wrapped in double quotes.
4. Produce exactly one SELECT statement. Never write INSERT, UPDATE, DELETE, \
CREATE, DROP, ALTER, ATTACH, COPY, CALL, EXPORT or PRAGMA. Do not end the \
statement with a semicolon.
5. If the question cannot be answered from the columns listed, set "answerable" \
to false and use "reason" to name exactly what is missing. Refusing is correct \
and expected. Never answer a different question instead, and never substitute a \
column that seems close.
6. Read the notes about the file. If they say there is no date column, then no \
question about periods, months, quarters, growth or trends can be answered. If \
they say the column names are positional and carry no meaning, do not read \
meaning into them.
7. A column whose role is "temporal" answers any question about a period. You \
can filter it to a range, or group it with date_trunc, year, month, quarter or \
strftime. Never refuse a question about a month, a quarter or a year just \
because no column is named after one: if a date or timestamp column exists, the \
period can be derived from it.
8. Refuse only when no column holds the information at all. Do not refuse \
because a column is worded differently from the question. Match on what a \
column contains, using its example values and its role, not on whether its name \
repeats the question.
9. Most useful answers are calculated, not looked up. Never refuse because the \
thing being asked for is not already a column. If the facts are in the file, \
the calculation is your job. For example:
  - things that happened only once: count the rows for each value, then keep \
the values whose count is 1
  - a change between two periods: sum each period with a filtered aggregate in \
one query, then subtract one from the other
  - a share or a percentage: compute the part and the whole in the same query \
and divide
  - things that occur together: join the table to itself on the column they \
share, keeping each pair once, and count the pairs
  - a rate per group: divide one aggregate by another in the same group
Refuse when a fact is missing from the file, never when a calculation is \
required.
10. A column whose role is "flag" holds only 0 and 1. Counting or filtering on \
one is meaningful; summing or averaging one is not.
11. When the question asks for a ranking or a "top N", use ORDER BY with an \
explicit direction and LIMIT N.
12. When the question asks for a share, a percentage or a proportion, compute \
both parts in the query rather than returning one number and leaving the \
division to the reader.
13. Group by the column that names the thing being counted, not by an \
identifier that happens to sit beside it.
14. Always fill "reason", whether or not the question is answerable. When it \
is, say in one sentence what the query computes and which columns it uses, and \
write it before the SQL. That sentence is shown to the person who asked, beside \
the result.

Answer with JSON only.\
"""


def build_user_prompt(question: str, context: SchemaContext) -> str:
    """The per-question half of the prompt: the data, then the question.

    The schema comes first and the question last. A model attends most reliably
    to the end of its input, and the question is the part that changes.
    """
    return (
        f"{render_for_prompt(context)}\n\n"
        f"Question: {question.strip()}\n\n"
        "Answer with JSON only."
    )
