# Walkthrough notes

Written for me, to study before the panel. Plain language. For each component:
what it does, why it is built that way, what they are likely to ask, and a good
answer. Then every SQL query the system generates, explained clause by clause.

---

## Part 1. The shape of the thing in one minute

If they ask me to start by describing the system, this is the answer:

> A CSV comes in. We load it into DuckDB and measure every column: types, how
> much is missing, how many distinct values, the range, what typical values look
> like. That measurement is the only thing the rest of the system knows about
> the data.
>
> A question comes in. We turn the measurement into a description, send that
> plus the question to a local model, and get back either SQL or a refusal. If
> it is SQL, we check it before it runs: one statement, a SELECT, reading only
> this dataset's table, with columns that actually resolve. Then we run it under
> a row limit and a timeout and return the rows together with the SQL that
> produced them.
>
> Both the upload and the question are jobs. The caller gets an id and polls.
> Nothing slow happens while a request is held open.

The two sentences I want to land early:

1. **Nothing in the code knows any column name.** Everything the system knows
   about a file was measured from that file at ingest time, and there is a test
   that fails if a column name from the development dataset ever appears in the
   source.
2. **Refusing is a correct answer, not an error.** It is a return value that
   travels to the caller with a reason attached.

---

## Part 2. Component by component

### Loader, `src/insights/ingest/loader.py`

**What it does.** Takes a path, gets the rows into a DuckDB table, and reports
honestly how the types were decided.

**Why it is built this way.** It measures nothing and concludes nothing. It has
exactly one job. Two details matter:

*Types are inferred from the whole file.* DuckDB samples the first twenty
thousand rows by default. We pass `sample_size = -1` so it reads everything.
That cost 0.86 seconds instead of 0.43 on a 78 MB file, and it buys correct
typing of a column that looks like an integer for twenty thousand rows and turns
messy at row four hundred thousand.

*There is a fallback.* If type inference fails, we read every column as text and
record that in the profile, so downstream code knows the types are not to be
trusted. The dataset stays queryable.

**What they will ask: "What happens if the CSV has no header?"**

> DuckDB does not error. It decides there is no header, names the columns
> `column0`, `column1` and so on, and treats the header row as data. That is a
> silent correctness hazard, so I detect it: if every column name matches the
> pattern DuckDB invents, the profile records `header_detected: false` and the
> schema context tells the model the names are positional and carry no meaning.
> The same thing happens on a ragged file where rows have different numbers of
> fields. There is a fixture for it.

**What they will ask: "Why reject a file with a header and no rows?"**

> A dataset with zero rows would be listed, selectable and would answer every
> question with nothing. Failing at ingest with "the file has a header but no
> data rows" is a better experience than five confusing refusals later.

### Profiler, `src/insights/ingest/profiler.py`

**What it does.** For every column: how many values are not null, how many are
distinct, the minimum and maximum for ordered types, the mean for numbers, the
mean and maximum length for text, and the five most frequent values.

**Why it is built this way.** It draws no conclusions. It does not decide a
column is a price. That is the context builder's job. Keeping measurement and
interpretation apart means the interpretation can change without re-reading the
data, which is exactly what happened twice during the build.

**What they will ask: "Your profiler runs n plus one queries."**

> True, and deliberate. The statistics are one query with seven aggregates per
> column, so the table is scanned once instead of once per column. The frequent
> values are one query per column on top of that. DuckDB has a `histogram`
> function that would fold them into the wide query, but it materialises a map
> of every distinct value, which on a column with twenty five thousand distinct
> invoice numbers is a bad trade.

**What they will ask: "Why measure text length?"**

> It is the only thing that separates a short product code from a sentence when
> both have several thousand distinct values. Without it, a product description
> and a stock code look identical in the statistics.

### Registry, `src/insights/registry.py`

**What it does.** Stores each dataset's profile as a JSON document in a `meta`
schema inside the same DuckDB file, keyed by dataset id.

**Why JSON and not columns.** The profile model grows. It gained text lengths
and a non null count during the build. A JSON column absorbs that without a
migration. Nothing queries inside it; it is always read whole, by id.

**Why a separate `meta` schema.** So our bookkeeping can never collide with a
user's data, and so the validator can refuse any schema qualified name outright.

### Context builder, `src/insights/context/`

**What it does.** Turns a measured profile into the description the model sees:
a role per column, caveats about the file, and a rendered text block.

**This is the component the whole assignment rests on. Know it cold.**

**The decision. Roles come from statistics only, never from column names.**

> The tempting design is a token list. A column whose name contains "price" is
> money, one containing "date" is a date. I rejected it, because the model
> already reads the column names. Whatever a column is called, the model can see
> what it is called. A name matching heuristic adds a second, worse opinion about
> the same evidence. It contradicts the name on any file that is not in English
> business vocabulary, and it has to be maintained forever.
>
> What the model cannot see is that a column has 38 distinct values across half
> a million rows, or that a quarter of it is empty, or that its values average
> six characters. That is what this module contributes, and it is all it
> contributes.

**The accepted cost, and I should volunteer it before they find it.**

> It does not claim to tell a price from a count. Both are `measure`. That is a
> claim about meaning and the only evidence for it is the name, which the model
> has. On the retail file this means the customer id column comes out as
> `measure`, because statistically an integer with four thousand repeated values
> is a measure. The role is a hint; the measurements are the substance, and the
> model reads the name.

**What they will ask: "How do you know a column is a flag and not a year?"**

> The measured minimum and maximum, not the name. A flag is an integer column
> whose minimum is 0 and maximum is 1. A year column has two distinct values in
> this dataset as well, 2010 and 2011, and it is not a flag because its range is
> not zero to one.

**What they will ask: "Show me a bug you found here."**

> The first version called a column an identifier on distinct rate alone. On the
> five row rentals fixture that made "Days Hired", five different whole numbers,
> indistinguishable from a primary key, and it made a column with one value and
> four blanks an identifier at a distinct rate of 1.0. The fix is a minimum
> evidence count: below twenty non null values the distinct rate is a
> coincidence, not evidence. Both the failing and the passing case are tests.

**The caveats, and why they matter more than the roles.**

> The builder also states facts about the file as a whole. The most useful one
> is "there is no date or time column, so questions about periods, growth or
> trends cannot be answered from this data". That single line is the difference
> between refusing a question about growth and inventing an answer to it, and it
> costs nothing to compute. A refusal that names what is missing is useful. One
> that says "I cannot answer that" is not.

**The lesson I most want to tell them, because it is architectural.**

> Twice, the model refused a question the data could answer. The first time it
> was "net revenue in March" on a file with a timestamp column. I added a rule
> to the system prompt saying a temporal column can be grouped into periods. It
> fixed the development file and did nothing for an unseen one.
>
> What fixed it was moving the same sentence out of the rules list and into the
> schema context, attached to the column: `temporal = a date or time; any day,
> month, quarter or year can be derived from it`. Later the same thing happened
> again for "between two quarters", and the fix was to repeat the clause on the
> column line itself rather than only in the legend.
>
> The lesson is that an affordance belongs next to the data it applies to, not
> in a list of rules far above it. A rule competes with a dozen other rules for
> attention. A clause attached to the column is read at the moment that column is
> being considered. Where a fact lives in a prompt changes whether it is used.

### LLM client, `src/insights/llm/`

**What it does.** One protocol with one method: `generate(system, user,
json_schema)`. One implementation for Ollama, one fake for tests.

**What they will ask: "How would you swap the model provider?"**

> One new file implementing the protocol, one entry in the provider map in
> `llm/__init__.py`, one changed setting. Nothing above `llm/` changes, because
> nothing above it has heard of Ollama. The planner is handed a client and does
> not know where it came from.

**What they will ask: "Why a local model?"**

> No API key, no network, no per question cost, and nothing to fail in a room
> with bad wifi during a walkthrough. The cost is real and I will say it first:
> a 7B model is weaker at multi step reasoning than a frontier model, and the
> evaluation numbers show exactly where. It is also why the validator carries
> more weight here than it would behind a large model. The seam means moving to
> a frontier model is a one file change if that trade stops being worth it.

**Why not a chat interface.** Planning a question is one exchange with no
history. A conversational interface would invite state we do not have and could
not reproduce.

### Planner, `src/insights/planner/`

**What it does.** Question plus schema context in, SQL or a refusal out.

**The output is constrained JSON.** Ollama constrains decoding to a schema, so
the model cannot wrap its answer in prose or apologise before the JSON.

**Two findings here that are worth telling, because they are concrete.**

*Field order is load bearing.*

> Constrained decoding emits properties in schema order. My first version was
> `answerable`, `sql`, `reason`, and it returned good SQL with an empty reason
> every single time. Having already written the query, the model had nothing
> left to say. Reordered to `answerable`, `reason`, `sql`, the model states in
> words what it is about to compute and then writes SQL with that sentence
> already in its context. It is a small chain of thought that costs nothing, and
> it is where the explanation shown in the UI comes from.

*An empty string satisfies "type: string".*

> Reordering alone did not fix it. An empty string is the cheapest token path,
> and my prompt only asked for a reason when refusing. The fix is `minLength: 15`
> on the field. Ollama enforces it in the grammar. I tested it by telling the
> model explicitly to leave the field empty, and it could not.

**Refusal is a return value.** `plan_query` returns a plan that is either a
query or a refusal, and both are successes. `PlanningFailed` is raised only when
the model returns something that is not a decision at all: unparseable text,
JSON that is not an object, a response with no `answerable` key. That
distinction is the whole design. "The data cannot answer this" and "the model
malfunctioned" are different events and must not share a code path.

**One case sits between them.** The model says `answerable: true` and returns no
SQL. That is treated as a refusal rather than passed to the executor, because an
empty statement produces a database error the user can do nothing with.

### Validator, `src/insights/validator.py`

**What it does.** Decides whether generated SQL may run. Four checks.

**The framing I want to use.** Each check is done by whatever is best able to do
it, rather than by code I wrote:

| Question | Answered by |
| --- | --- |
| One statement, and a SELECT? | DuckDB's own parser |
| Reads only our table? | sqlglot AST walk against an allowlist |
| Do the columns exist? | DuckDB's binder, via `EXPLAIN` |
| Does it finish? | the executor, not here |

**What they will ask: "Why not check the column names yourself?"**

> Because that means re-implementing SQL name resolution. An alias is not a
> column. `SELECT sum(a) AS s FROM t ORDER BY s` refers to `s`, which does not
> exist in the table, and it is valid. CTE output names are the same problem.
> The binder already resolves all of this correctly, and `EXPLAIN` runs it
> without executing anything. Planning a query over a four way self join of 8.1
> billion combinations returns in single digit milliseconds, because it never
> touches the rows.

**What they will ask: "Show me you cannot read another dataset."**

> The table check is an allowlist, not a denylist. Every table reference must be
> this dataset's table or a CTE defined in the statement. A denylist would have
> to anticipate `read_csv`, `read_parquet`, a bare file path, a schema qualified
> name, an extension installed later, and it only has to be incomplete once. The
> case it would never have caught is another dataset's table, because
> `ds_a1b2...` looks exactly like the table we do allow. There are tests for
> reading another dataset and for joining to it.

**The detail I am proudest of, and they may not ask, so I will offer it.**

> The order of the checks matters and it is pinned by a test. The table
> allowlist runs before the database is asked to bind the statement, because
> binding is not free of consequences. `EXPLAIN SELECT * FROM read_csv('<a path
> that does not exist>')` returns an IO error saying no files matched, and
> pointed at a file that does exist, the plan contains that file's column names.
> DuckDB opens the file at plan time to work out its schema. So asking the binder
> first would leak whether an arbitrary path exists and what is in it, without
> ever running a query. The test proves the ordering: pointed at a missing path,
> the rejection must be ours, not DuckDB's.

**A bug worth telling, because it failed in the good direction.**

> Every single SELECT was rejected on the first run. I had written
> `if kind is not duckdb.StatementType.SELECT`. DuckDB's `StatementType` is a
> pybind11 enum, not a Python one, so each attribute access hands back a fresh
> object: `==` is true and `is` is false. `is` is the idiomatic choice for enums,
> which is exactly why the line now carries a comment saying not to use it. It
> failed loudly and immediately, which is the good version of this bug. The bad
> version is the same mistake in a check that fails open.

**What is still weak, and I should say it before they find it.**

> Two parsers see the statement. sqlglot decides which tables are read and
> DuckDB decides what runs. If they ever disagree, the allowlist could be walked
> around. That is inherent in using a second parser, and DuckDB exposes no public
> API to enumerate a statement's tables. Nothing here inspects scalar function
> calls either. DuckDB's built ins are pure, so that is fine today, but it is an
> assumption rather than a check.

### Executor, `src/insights/executor.py`

**What it does.** Runs a validated query under a row limit and a timeout.

**The type is the guarantee.** `run_query` accepts a `ValidatedQuery` and
nothing else, and only the validator produces one. A future caller cannot skip
validation by passing a string. There is a test that fails if that signature is
loosened.

**Row limit.** It fetches one row beyond the limit, purely to find out whether
there were more, then returns the limit and sets `truncated`. A query that
matches a million rows costs a thousand, and the caller is told the result is a
prefix rather than being quietly shown one.

**Timeout.** The query runs on a worker thread. The calling thread waits and
calls `interrupt()` if the wait expires.

**What they will ask: "What happens to a query that runs forever?"**

> It is cancelled. I measured three things rather than assuming them. The
> interrupt raises inside the running query within about ten milliseconds. The
> connection and the cursor are both still usable afterwards, and there is a
> test that runs a normal query right after a cancellation. And the interrupt is
> scoped to the handle it is called on: two heavy queries on two cursors,
> interrupt one, that one dies and the other completes. That last measurement is
> why every unit of work takes its own handle from `db.session()`, and it is what
> lets one runaway question be cancelled without touching any other question in
> flight.

### Job layer, `src/insights/jobs/`

**What it does.** Queues work on a bounded thread pool, records status, survives
a restart.

**What they will ask: "Why threads and not Celery?"**

> DuckDB allows one writing process. A separate worker process could not write
> to the same file, so a queue server would add two moving parts and still not
> solve anything. Threads inside the API process is the shape that fits the
> storage engine, and it works because the two slow things both release the
> interpreter lock: DuckDB runs queries in its own C++ threads, and the model
> call is waiting on a socket. The limit is real and I write it down: this scales
> up, not out.

**What they will ask: "What happens under concurrent load?"**

> The pool is bounded, four by default. Beyond that, jobs queue where we can see
> them rather than piling up at the storage layer. Each job takes its own DuckDB
> cursor, which is an independent handle sharing the same buffer pool, so two
> jobs never read each other's rows. Reads during a write are fine, because
> DuckDB is MVCC. The ceiling is one process.

**What they will ask: "What happens under partial failure?"**

> Three answers, one per failure.
>
> A job that raises an expected error is marked failed with the same structured
> error a synchronous call would have returned. An unexpected exception is logged
> in full on the server and reported to the caller as a bare `internal_error`,
> because a traceback is not something a caller can act on.
>
> A process that dies mid job leaves rows saying `running` that would never
> change. On the next start, any job still queued or running belongs to a dead
> process, because this one has not started any yet, so they are marked failed
> with "the service restarted while this job was running". A client polling is
> told the truth instead of waiting forever.
>
> During ingestion, the table is created, then profiled, then registered. If
> profiling or registration fails, the table is dropped before the error
> propagates. A dataset in the warehouse with no profile would be invisible to
> the registry and still queryable with a schema nobody had checked.

**What I have not done, and will say so.** A job interrupted by a restart is
marked failed, not resumed. Resuming means making every job idempotent and
restartable, which is a lot of machinery for a service whose longest job is a few
seconds.

### API, `src/insights/api/`

**What it does.** Input validation, status codes, one error shape, serialisation.
No business logic at all, which is why the command line and the API give
identical answers.

**One error shape.** `{"error": {"code", "message", "details"}}` for everything,
including FastAPI's own validation errors, which are reshaped into the same
envelope. A caller writes one piece of error handling, not one per endpoint. The
`code` is stable and meant to be branched on. No handler ever returns a
traceback.

**Why the dataset is looked up in the endpoint and not in the worker.** So that
a bad dataset id is a 404 immediately, rather than a job that is accepted and
fails a moment later. There is a test asserting no job is created.

**Uploads are streamed and counted as they go**, so a caller cannot make the
service buy a gigabyte of memory by claiming a small file and sending a large
one. The name on disk comes from a generated id, never from the uploaded
filename.

### Evaluation, `src/insights/evaluation/`

**The decision worth defending.** A case records its right answer as **truth
SQL**, not as a number.

> Recording the number is the obvious way and it rots. It is copied from a run
> that may itself have been wrong, it breaks the moment the file changes, and it
> cannot be reused on a second file. Truth SQL is a query I wrote by hand that
> defines what the right answer is. The harness runs it and compares. The
> expected answer is recomputed from the data every run, the same suite works on
> a different file, and reviewing a case means reading a query rather than
> trusting a figure.

**Failures are bucketed, because they are not equally bad.** Wrong answer, wrong
refusal, answered the unanswerable, and error. Answering an unanswerable
question is the dangerous direction and it gets its own bucket and a warning
line in the report.

**A flaw I found in my own evaluation, which I should tell them about.**

> My first ranking cases failed, and it was my fault, not the system's. The
> library loans fixture has exactly 75 loans at each of four branches and exactly
> five loans of each catalogue item. Every ranking over it is a four way or sixty
> way tie. The model cannot be wrong about an order that is not determined. I
> built a second dataset with deliberately skewed distributions so that every
> ranking has one unambiguous right answer, and removed the ranking cases from
> the uniform fixture with a note in the suite saying why.

---

## Part 3. Every SQL query the system generates

Four kinds. The ones we write for ingestion and profiling, the ones for
bookkeeping, the one the validator uses, and the ones the model writes.

### 3.1 Loading a file

```sql
CREATE OR REPLACE TABLE "ds_7f3c9a..." AS
SELECT * FROM read_csv(?, auto_detect = true, sample_size = -1)
```

* `CREATE OR REPLACE TABLE ... AS SELECT` creates a table and fills it from the
  query in one statement. The name comes from a generated UUID, never from the
  uploaded filename, so no user input can reach a table name.
* The name is wrapped in double quotes. In SQL, double quotes delimit an
  identifier. Any internal double quote is escaped by doubling it, which is what
  makes an arbitrary string safe to use as a name.
* `read_csv(?)` is DuckDB's CSV reader used as a table. The `?` is a bound
  parameter, so the file path is never interpolated into the SQL string.
* `auto_detect = true` lets DuckDB sniff the delimiter, the quoting, whether
  there is a header, and a type per column.
* `sample_size = -1` means read the whole file when deciding those types, rather
  than the first twenty thousand rows.

The fallback, used only if the above fails:

```sql
CREATE OR REPLACE TABLE "ds_7f3c9a..." AS
SELECT * FROM read_csv(?, auto_detect = true, all_varchar = true)
```

* `all_varchar = true` reads every column as text. The file loads, and the
  profile records that types were not inferred.

Then two cheap statements:

```sql
SELECT count(*) FROM "ds_7f3c9a..."
DESCRIBE "ds_7f3c9a..."
```

* `count(*)` counts every row, including rows that are entirely null.
* `DESCRIBE` returns one row per column with its name and its type. We use it
  for the column list and to detect the names DuckDB invents when it finds no
  header.

### 3.2 Profiling, the wide statistics query

One query with seven aggregates per column. For a column called `Days Hired` and
another called `Notes`:

```sql
SELECT count("Days Hired"),
       count(DISTINCT "Days Hired"),
       min("Days Hired"),
       max("Days Hired"),
       avg("Days Hired"),
       NULL, NULL,
       count("Notes"),
       count(DISTINCT "Notes"),
       NULL, NULL, NULL,
       avg(length("Notes")),
       max(length("Notes"))
FROM "ds_7f3c9a..."
```

Clause by clause:

* `count(col)` counts rows where `col` is not null. Subtracting it from the row
  count gives the null count. This is why `count(*)` and `count(col)` both
  appear in the system: they mean different things, and the difference is the
  measurement.
* `count(DISTINCT col)` is how many different values the column holds. Divided
  by the non null count it becomes the signal that separates an identifier,
  where nearly every row differs, from a category, where a handful of values
  repeat.
* `min` and `max` are emitted only for numbers, dates, timestamps and booleans.
  On free text they would report alphabetical extremes, which describe nothing.
* `avg(col)` is emitted only for numbers.
* `avg(length(col))` and `max(length(col))` are emitted only for text.
  `length` returns the number of characters. This is what separates a six
  character product code from a thirty character description when both have
  thousands of distinct values.
* The `NULL` placeholders keep the result row exactly seven slots wide per
  column, so it can be sliced by position rather than parsed by name.
* One query rather than one per column, so the table is scanned once. On the
  development file that is one scan instead of twenty five.

**If they ask why not `approx_count_distinct`:** it is faster and it is
approximate, and this number decides whether a column is called an identifier.
Exact counting on half a million rows is fast enough that trading accuracy for
speed would be paying for something we do not need.

### 3.3 Profiling, the frequent values query

One per column:

```sql
SELECT CAST("Branch Library" AS VARCHAR) AS value, count(*) AS frequency
FROM "ds_7f3c9a..."
WHERE "Branch Library" IS NOT NULL
GROUP BY value
ORDER BY frequency DESC, value ASC
LIMIT 5
```

* `GROUP BY value` collapses the rows to one row per distinct value. `count(*)`
  is then how many rows fell into each group.
* `WHERE ... IS NOT NULL` because "null" is not an example of what a column
  holds. The null rate is reported separately.
* `ORDER BY frequency DESC` puts the most common first, which is what shows the
  shape of a category column.
* `, value ASC` breaks ties alphabetically. This matters more than it looks:
  these values go into a prompt, and a prompt that changes between runs makes a
  wrong answer impossible to reproduce, which is exactly when you need to
  reproduce it.
* `CAST(... AS VARCHAR)` because these are display examples. They are truncated
  to 120 characters so a free text column cannot blow up the prompt.
* The whole thing is wrapped in a try block. A nested or binary column has no
  text form, and a column we cannot sample is still a column worth reporting.

### 3.4 Bookkeeping

```sql
CREATE SCHEMA IF NOT EXISTS meta

CREATE TABLE IF NOT EXISTS meta.datasets (
    dataset_id      VARCHAR PRIMARY KEY,
    table_name      VARCHAR NOT NULL,
    source_filename VARCHAR NOT NULL,
    row_count       BIGINT  NOT NULL,
    column_count    INTEGER NOT NULL,
    ingested_at     TIMESTAMP NOT NULL,
    profile_json    VARCHAR NOT NULL
)
```

* `IF NOT EXISTS` on both, so a fresh database file needs no separate migration
  step. They run on every write.
* A separate `meta` schema so our bookkeeping cannot collide with a user's data,
  and so the validator can refuse any schema qualified name outright.
* `profile_json` holds the whole profile as one JSON document. Nothing queries
  inside it; it is always read whole, by id.
* `ingested_at` is `TIMESTAMP`, not `TIMESTAMPTZ`. Reading an offset back needs
  an extra dependency for no benefit, since every timestamp we write is already
  UTC. We drop the offset on the way in and restore it on the way out.

```sql
INSERT OR REPLACE INTO meta.datasets
    (dataset_id, table_name, source_filename, row_count, column_count,
     ingested_at, profile_json)
VALUES (?, ?, ?, ?, ?, ?, ?)
```

* `INSERT OR REPLACE` so re-profiling a dataset overwrites its record rather
  than failing on the primary key.
* Every value is a bound parameter.

The jobs table is the same shape, and one query in it is worth reading:

```sql
SELECT job_json FROM meta.jobs WHERE status IN (?, ?)
```

* Run once at startup with `queued` and `running`. Any job in those states
  belongs to a process that died, because this one has not started any yet. They
  are marked failed so nobody polls a job that can never change.

### 3.5 The validator's query

```sql
EXPLAIN SELECT "Branch Library", count(*) FROM "ds_7f3c9a..." GROUP BY 1
```

* `EXPLAIN` plans the statement and stops. It resolves every column, alias and
  CTE exactly as execution would, and fails the same way on a name that is not
  there. That is precisely the check we want, and it is the one hardest to write
  correctly by hand.
* It does not touch the data. Planning a query over billions of row combinations
  returns in single digit milliseconds, and there is a test asserting validation
  of such a query completes in under two seconds, which fails if `EXPLAIN` ever
  starts executing.
* It runs **after** the table allowlist, because binding a `read_csv` opens the
  file.

### 3.6 The queries the model writes

These are the ones I should be able to read aloud. All are real output from
`qwen2.5-coder:7b`.

#### Top N by a summed measure

```sql
SELECT "Station", SUM("Fee Charged") AS Total_Fees
FROM "ds_b210961f..."
GROUP BY "Station"
ORDER BY Total_Fees DESC
LIMIT 3
```

* `GROUP BY "Station"` makes one output row per distinct station.
* `SUM("Fee Charged")` adds the fee across every row in each group. `SUM`
  ignores nulls rather than producing null, which is usually what you want and
  is worth knowing.
* `AS Total_Fees` names the computed column so it can be referred to below.
* `ORDER BY Total_Fees DESC` sorts largest first. In DuckDB you can order by an
  alias defined in the select list, which is why this works. Strict SQL would
  need the expression repeated.
* `LIMIT 3` keeps the top three. Without an `ORDER BY`, a `LIMIT` returns an
  arbitrary three rows, which is why the prompt insists the two appear together.

#### A period filter on a date column

```sql
SELECT SUM("Fee Charged") AS Total_Fee
FROM "ds_b210961f..."
WHERE "Hired On" >= DATE '2024-03-01' AND "Hired On" < DATE '2024-04-01'
```

* Note there is no column named after a month. The model derived the period from
  the date column, which is what the schema context tells it that it can do.
* `>= start AND < next start` is the correct way to filter a month. It is
  half open, so it catches every instant inside March regardless of the time of
  day, and it does not accidentally include midnight on the first of April.
  `BETWEEN` would be inclusive at both ends and would be wrong on a timestamp.
* `DATE '2024-03-01'` is a typed literal, so no string to date coercion is
  guessed at.

#### Counting on a flag

```sql
SELECT count(*) FROM "ds_b210961f..." WHERE "Was Late" = 1
```

* A flag holds only 0 and 1. Filtering on it and counting the rows is
  meaningful. Summing it would also give the right number here by accident, and
  averaging it would give a rate that looks like a measurement and is easy to
  misread. The prompt says a flag is for counting and filtering, and the role in
  the schema context is what tells the model this column is a flag.

#### Comparing two periods, the shape that is hardest for a small model

This is the truth SQL for the growth case:

```sql
WITH by_station AS (
    SELECT "Station" AS name,
           sum(CASE WHEN quarter("Hired On") = 1 THEN "Fee Charged" ELSE 0 END) AS earlier,
           sum(CASE WHEN quarter("Hired On") = 2 THEN "Fee Charged" ELSE 0 END) AS later
    FROM "ds_b210961f..."
    WHERE year("Hired On") = 2024
    GROUP BY 1
)
SELECT name FROM by_station ORDER BY (later - earlier) DESC LIMIT 1
```

* `WITH ... AS (...)` is a common table expression. It names a result so the
  outer query can read from it. It is not a temporary table; it is scoped to this
  statement.
* The two `sum(CASE WHEN ...)` expressions are the important trick. Each one
  adds up only the rows belonging to one quarter, and returns 0 for the others.
  Both totals come out of a **single pass** over the data, side by side in one
  row per station. The alternative is two queries and a join, which is slower and
  harder to read.
* `quarter()` and `year()` extract parts from a date.
* `GROUP BY 1` groups by the first item in the select list. Shorthand for
  `GROUP BY "Station"`.
* `ORDER BY (later - earlier) DESC` ranks by the change. Growth here is the
  absolute change, not the percentage, because a percentage rewards whichever
  station started nearest to zero. That is a business judgement and it is written
  into the case where a reviewer can argue with it.

#### Things that happened only once

```sql
WITH per_customer AS (
    SELECT "customer_id", count(DISTINCT "invoice_no") AS orders
    FROM "ds_ccf63ee..."
    WHERE "customer_id" IS NOT NULL
    GROUP BY 1
)
SELECT count(*) FROM per_customer WHERE orders = 1
```

* Two stages. The inner query counts orders per customer. The outer query counts
  the customers whose total is one.
* `count(DISTINCT "invoice_no")` rather than `count(*)`, because one order has
  many lines. Counting rows would count line items and nearly nobody would look
  like a one time buyer.
* `WHERE "customer_id" IS NOT NULL` excludes unidentified sales. An anonymous
  sale cannot be attributed to a customer who bought once.
* This is one of the shapes the 7B model gets wrong. It is in the evaluation
  suite as a failing case, which is the point of having a suite.

#### Things bought together

```sql
SELECT a."description", b."description", count(*)
FROM "ds_ccf63ee..." a
JOIN "ds_ccf63ee..." b
  ON a."invoice_no" = b."invoice_no"
 AND a."description" < b."description"
GROUP BY 1, 2
ORDER BY count(*) DESC
LIMIT 1
```

* A self join: the table joined to itself under two aliases, `a` and `b`. Each
  row of `a` is paired with each row of `b` that shares an invoice.
* `a."description" < b."description"` does two jobs at once. It stops a product
  pairing with itself, and it keeps each pair only once rather than twice in both
  orders. A string comparison is alphabetical, so exactly one of the two
  orderings survives.
* `GROUP BY 1, 2` groups by the pair.
* This is a genuinely expensive query on half a million rows, which is why the
  executor has a timeout.

---

## Part 4. Questions I expect, with short answers ready

**"Show me where a column name from your dataset appears in the code."**
It does not, and there is a test that enforces it. It scans every file under
`src/` for the 27 column names in the development file and fails if one appears.
It runs in CI. It caught me once on a docstring.

**"Load this CSV I just handed you."**
Upload it in the UI, or `insights ingest path.csv`. Nothing else changes. The
profile is measured from the file and the schema context is built from the
profile.

**"Why is your accuracy not higher?"**
Twenty eight of thirty three across three files, and twelve of twelve on the
questions that should be refused. The failures are all the same shape: answers
that have to be derived rather than looked up. The same shapes pass on the eight
column file and fail on the twenty five column one, so it is the model's
reasoning under a wider schema, not the pipeline. I tried twice to fix it in the
prompt and stopped, because tuning further would have meant fitting the prompt to
one dataset. The fix is a bigger model behind the same seam, or a self repair
loop, and both are in the next steps.

**"How do you know it is not inventing answers?"**
Three layers. The context tells the model what is missing, so it can refuse for a
concrete reason. The validator rejects any query naming a column that does not
resolve, so an invented column can never produce a number. And the evaluation
harness includes twelve questions that cannot be answered, all twelve of which
are currently refused correctly.

**"What would you do if I gave you ten million rows?"**
Ingest is fine, since DuckDB streams it. Profiling is the part that would hurt,
because counting distinct values across every column at once is not free. I would
profile a sample using `USING SAMPLE` and record in the profile that the numbers
are estimates, so the schema context can say so.

**"What is the worst thing about this design?"**
One process. DuckDB allows one writer, so this scales up and not out. If two
teams needed it at once I would move the storage to something with a server, and
the seam for that is the same one that already separates the executor from
everything else.

**"What are you least confident about?"**
The two parser problem in the validator. sqlglot decides what tables a statement
reads and DuckDB decides what it runs. They agree today. I have no proof they
agree on every statement.
