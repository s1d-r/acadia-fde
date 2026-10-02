# Learn this project

A guide for someone who knows a little Python and has never written SQL, never
built a web API, and never used a database.

Everything here was checked against the code in this repository. File names and
function names are given so you can open them and look.

Read it in order the first time. After that, use it to look things up.

---

## 1. The big picture

### The problem, in three sentences

A shop keeps a big spreadsheet of everything it sold. People keep asking
questions about it, like "what sold best last March", and every question means
someone has to sit down and write a database query by hand. This project lets
anyone type the question in ordinary English and get the answer back, along with
the query it used, so they can check the work.

### The parts

```
   You, in a web browser
            |
            v
   +-------------------+
   |   HTTP API        |   checks your request, hands the work off, answers
   +-------------------+
            |
            v
   +-------------------+
   |   Job runner      |   does slow work in the background
   +-------------------+
            |
            v
   +---------------------------------------------------+
   |  THE ENGINE                                        |
   |                                                    |
   |  1. Ingestion     read the file, measure it        |
   |  2. Context       describe it for the model        |
   |  3. Planner       ask the model for a query        |
   |  4. Validator     decide if the query may run      |
   |  5. Executor      run it, with limits              |
   +---------------------------------------------------+
            |
            v
   +-------------------+
   |   DuckDB          |   one file on disk that holds everything
   +-------------------+
```

The model, the thing that writes the query, sits off to one side. The planner
talks to it. Nothing else does.

### The one sentence that matters most

**Nothing in the code knows the name of any column in your file.** Everything the
system knows about a file, it measured from that file when the file arrived.
That is why you can hand it a spreadsheet it has never seen and it still works.

---

## 2. Words I need to know

**CSV**
A plain text file where each line is a row and commas separate the values. Like
a spreadsheet saved in the simplest possible way. Example first line:
`Station,Minutes Used,Fee Charged`.

**Column**
One vertical slice of a table. In the example above, `Fee Charged` is a column.
Every row has a value for it.

**Row**
One horizontal line. One hire, one sale, one loan. One thing that happened.

**Table**
Rows and columns together. A CSV becomes a table once the database has read it.

**Schema**
The list of what columns a table has and what kind of value each one holds. Like
the header row of a spreadsheet, plus a note saying "this one is a date, this one
is a number". In this project the schema is produced by
`src/insights/ingest/profiler.py`.

**Database**
A program that stores tables and answers questions about them quickly. Think of
it as a filing cabinet that can also do arithmetic.

**DuckDB**
The particular database this project uses. Two things make it unusual. It needs
no server, so there is nothing to install and start separately, and the whole
database is one file on your disk. Here that file is `data/warehouse.duckdb`.

**SQL**
The language you use to ask a database a question. Pronounced "sequel" or
"ess cue ell". It reads almost like English. `SELECT "Station" FROM hires` means
"give me the Station column from the hires table".

**Query**
One question written in SQL. The thing you send to the database.

**API**
A way for one program to talk to another over the network. Not a screen, just
addresses you can send data to and get data back from. Short for application
programming interface.

**Endpoint**
One address in an API, with one job. `/api/datasets` is an endpoint. It lives in
`src/insights/api/app.py`.

**HTTP**
The rules browsers and servers use to talk. You already use it every time you
load a web page.

**Status code**
A three digit number that says how a request went. 200 means fine. 404 means
"not found". 500 means "something broke on our side". This project uses 202 for
"I have accepted your work and started it", and 400 for "your request was wrong".

**Job**
A piece of work that takes too long to do while someone waits. You hand it in,
you get a ticket, you come back later. Like dropping clothes at a dry cleaner.
Jobs live in `src/insights/jobs/`.

**Async**
Short for asynchronous. It means "you do not have to wait". The opposite is
synchronous, where you stand there until the work is done. This project is async
for uploads and for questions.

**Poll**
To keep asking "is it ready yet". The browser polls the job endpoint every 600
milliseconds. You can see that in `src/insights/ui/index.html`, in the
`waitForJob` function.

**LLM**
Large language model. A program that has read a lot of text and can produce more
text that fits. Here it reads a description of your data plus your question, and
writes a SQL query.

**Prompt**
Everything you send to the model. In this project the prompt is in two parts. A
fixed set of rules in `SYSTEM_PROMPT`, and the per question part built by
`build_user_prompt`. Both are in `src/insights/planner/prompts.py`.

**Validation**
Checking that something is acceptable before you act on it. This project
validates twice. It validates your HTTP request, and it validates the SQL the
model wrote, in `src/insights/validator.py`.

**Refusal**
When the system says "your data cannot answer that, and here is what is missing".
It is a correct answer, not an error. If you ask about suppliers and the file has
no supplier column, a refusal is the only honest reply.

**CI**
Continuous integration. A robot that runs your tests every time you push code,
so you find out quickly if you broke something. The setup is in
`.github/workflows/ci.yml`.

**Docker**
A way to package a program with everything it needs, so it runs the same
anywhere. A container is one running copy. The recipe is in `Dockerfile`.

---

## 3. SQL crash course, using this project's own queries

Everyday version first, then the real thing.

### SELECT and FROM

Everyday version: "from the hires list, show me the Station column".

```sql
SELECT "Station"
FROM "ds_7b57dd93..."
```

Read it out loud as: **select** these columns **from** this table.

* `SELECT` says which columns you want.
* `"Station"` is the column name. The double quotes matter here. They tell the
  database "this is a name, not a word I should interpret". Column names in a
  file you did not write can contain spaces, like `Fee Charged`, so this project
  always quotes them. The function that does it is `quote_ident` in
  `src/insights/sql_identifiers.py`.
* `FROM` says which table.
* `ds_7b57dd93...` is the table name. The project makes one table per uploaded
  file and names it `ds_` plus a random id. More on why in section 5.

`SELECT *` means "every column".

### WHERE

Everyday version: "only the hires from March".

Real query, from the bike hire evaluation suite in
`eval/suites/bike_hire.json`:

```sql
SELECT sum("Fee Charged")
FROM "ds_7b57dd93..."
WHERE "Hired On" >= DATE '2024-03-01' AND "Hired On" < DATE '2024-04-01'
```

* `WHERE` filters rows. Rows that fail the test are thrown away before anything
  else happens.
* `>=` means "on or after". `<` means "before".
* `DATE '2024-03-01'` is a date written in a way the database understands.
* Notice the shape: **on or after the first of March, and before the first of
  April**. That catches every moment in March, including late on the 31st. It
  never accidentally includes the first of April.
* There is a word `BETWEEN` that looks tidier. Avoid it here. `BETWEEN` includes
  both ends, so on a column that holds a time as well as a date it quietly grabs
  the very start of April too.

### COUNT

Everyday version: "how many hires are there".

```sql
SELECT count(*) FROM "ds_7b57dd93..."
```

* `count(*)` counts rows. The `*` means "every row, whatever is in it".
* `count("Station")` is different. It counts only rows where `Station` has a
  value. The gap between the two is how many values are missing. This project
  uses exactly that trick in `src/insights/ingest/profiler.py` to work out how
  empty each column is.

Counting with a filter:

```sql
SELECT count(*) FROM "ds_7b57dd93..." WHERE "Was Late" = 1
```

That is the real query shape for "how many hires were returned late". `Was Late`
holds only 0 and 1.

### SUM

Everyday version: "add up all the fees".

```sql
SELECT sum("Fee Charged") FROM "ds_7b57dd93..."
```

* `sum` adds a number column up.
* `sum` skips missing values rather than giving up and returning nothing.
* `count` tells you how many. `sum` tells you how much. Mixing them up is one of
  the most common beginner mistakes.

### GROUP BY

This is the one that unlocks most real questions.

Everyday version: "instead of one total for everything, give me one total per
station".

```sql
SELECT "Station", sum("Fee Charged")
FROM "ds_7b57dd93..."
GROUP BY "Station"
```

How to picture it. The database sorts the rows into piles, one pile per distinct
station. Then it runs `sum` separately inside each pile. You get one row out per
pile.

* Anything in your `SELECT` that is not inside a function like `sum` or `count`
  normally has to appear in the `GROUP BY`. Otherwise the database does not know
  which value from the pile you meant.
* `GROUP BY 1` is shorthand for "group by the first thing in the select list".
  You will see it in the evaluation suites.

### ORDER BY and LIMIT

Everyday version: "biggest first, and only show me the top three".

```sql
SELECT "Station", sum("Fee Charged") AS total_fees
FROM "ds_7b57dd93..."
GROUP BY "Station"
ORDER BY total_fees DESC
LIMIT 3
```

* `AS total_fees` gives the computed column a name. That name is an **alias**. It
  is not a column in the file. It exists only for the length of this query.
* `ORDER BY` sorts. `DESC` means descending, largest first. `ASC` is ascending,
  the default.
* `LIMIT 3` keeps the first three rows after sorting.
* **`LIMIT` without `ORDER BY` is a trap.** It gives you three rows, but nobody
  can say which three. That is why the prompt in
  `src/insights/planner/prompts.py` has a rule telling the model to always use
  the two together.

### JOIN

A join glues rows together. The usual case is two different tables. This project
only ever has one table per file, so the interesting case here is a table joined
to **itself**.

Everyday version: "find pairs of products that show up on the same receipt".

Here is the real query, and the real answer it gave on the retail data:

```sql
SELECT a."description" AS product_a,
       b."description" AS product_b,
       count(*) AS times_together
FROM "ds_0109cf5e..." a
JOIN "ds_0109cf5e..." b
  ON a."invoice_no" = b."invoice_no"
 AND a."description" < b."description"
GROUP BY 1, 2
ORDER BY times_together DESC
LIMIT 5
```

```
('JUMBO BAG PINK POLKADOT',        'JUMBO BAG RED RETROSPOT',          853)
('GREEN REGENCY TEACUP AND SAUCER','ROSES REGENCY TEACUP AND SAUCER',  772)
('JUMBO BAG RED RETROSPOT',        'JUMBO STORAGE BAG SUKI',           725)
('JUMBO BAG RED RETROSPOT',        'JUMBO SHOPPER VINTAGE RED PAISLEY',671)
('LUNCH BAG RED RETROSPOT',        'LUNCH BAG SUKI DESIGN',            669)
```

Clause by clause:

* `FROM ... a JOIN ... b` takes the same table twice and gives the two copies
  short names, `a` and `b`. Those are aliases again. Now you can talk about "the
  row from copy a" and "the row from copy b".
* `ON a."invoice_no" = b."invoice_no"` is the glue. Only pair up rows that share
  an invoice number. Same receipt.
* `AND a."description" < b."description"` does two jobs at once, and it is the
  clever bit.
  * It stops a product pairing with itself, because a thing is not less than
    itself.
  * It keeps each pair only once. Without it you would get both "bag and teacup"
    and "teacup and bag". Comparing two pieces of text with `<` is alphabetical,
    so exactly one of the two orderings survives.
* `GROUP BY 1, 2` makes a pile per pair.
* `count(*)` counts how many receipts are in each pile.

This query took 4.2 seconds on 511,395 rows. That is why the executor has a
timeout. See section 7.

### CTE, the WITH clause

Everyday version: "work out a number per customer first, then answer a question
about those numbers".

Real query from `eval/suites/online_retail.json`:

```sql
WITH per_customer AS (
    SELECT "customer_id", count(DISTINCT "invoice_no") AS orders
    FROM "ds_0109cf5e..."
    WHERE "customer_id" IS NOT NULL
    GROUP BY 1
)
SELECT count(*) FROM per_customer WHERE orders = 1
```

* `WITH name AS ( ... )` names a result so the query below can read from it.
  Think of it as a scratch pad. It disappears when the query ends.
* The inner query counts orders for each customer.
* The outer query counts how many of those customers had exactly one.
* `count(DISTINCT "invoice_no")` counts **different** invoice numbers, not rows.
  One order has many lines, one line per product. If you counted rows, almost
  nobody would look like a one time buyer.
* `IS NOT NULL` keeps out rows with no customer id. You cannot say an anonymous
  sale came from a customer who bought once.

### NULL

`NULL` means "no value here". It is not zero and it is not an empty word.

The rule that catches people out: `NULL = NULL` is not true. Nothing equals
`NULL`. To test for it you have to write `IS NULL` or `IS NOT NULL`.

This matters in this project because the profiler reports how much of each column
is missing, and the context builder warns the model when a column is mostly
empty.

---

## 4. Follow one question from start to finish

The question: **"What are the top 10 products by revenue?"**

Everything below is a real run captured from this repository, not an example I
made up.

### Step 1. You press Ask

The page is `src/insights/ui/index.html`. The Ask button handler sends this:

```
POST /api/datasets/0109cf5e01994a3ea9a1a6c32285fc58/questions
Content-Type: application/json

{"question": "What are the top 10 products by revenue?"}
```

### Step 2. The API takes it, and hands it straight back

Handled by the `ask` function in `src/insights/api/app.py`.

It does three things and nothing else.

1. FastAPI checks the body against `AskRequest` in
   `src/insights/api/schemas.py`. The question must be between 1 and 1000
   characters. An empty question never gets past here.
2. It looks up the dataset with `registry.get_profile`. If the id is wrong you
   get a 404 immediately. That is on purpose. A wrong id should not become a job
   that fails a second later.
3. It submits a job and returns.

You get back, with status code 202:

```json
{"job_id": "30667ec8cccc45f29fba1f55833ef88d", "status": "queued"}
```

202 means "accepted, not finished". Your browser is now free. Nothing slow has
happened yet.

### Step 3. A worker thread picks the job up

`JobRunner.submit` in `src/insights/jobs/runner.py` wrote the job row first, then
queued the work. That order matters. If it queued first, your very first poll
could arrive before the row existed and you would get a 404 for a job that is
perfectly fine.

The work itself is built by `question_job` in `src/insights/jobs/work.py`. It is
four lines. It calls `answer_question` and returns the result as a dictionary.

The worker gets its **own** database handle. Handles must not be shared between
threads.

### Step 4. The engine loads what it already measured

`answer_question` in `src/insights/answers.py` runs next.

```python
profile = registry.get_profile(dataset_id, con=connection)
context = build_context(profile)
```

No file is read here. The measuring happened once, at upload time. This is just
looking up what was already learned.

### Step 5. The context builder writes the description

`build_context` in `src/insights/context/builder.py` turns measurements into a
description, then `render_for_prompt` turns that into text.

Here is a real slice of what the model actually received for this dataset:

```
Table: "ds_0109cf5e01994a3ea9a1a6c32285fc58"
Rows: 511,395
Columns: 25

Columns, as: "name" TYPE [role] facts | examples

  "invoice_no" VARCHAR [key] 24,885 distinct, 0% empty | e.g. '573585', '558475', ...
  "invoice_date" TIMESTAMP [temporal] 22,361 distinct, 0% empty, from 2010-12-01T08:26:00
       to 2011-11-30T17:42:00, can be filtered or grouped by day, month, quarter or year
  "description" VARCHAR [key] 3,797 distinct, <1% empty | e.g. 'WHITE HANGING HEART
       T-LIGHT HOLDER', 'REGENCY CAKESTAND 3 TIER', ...
  "line_revenue" DOUBLE [measure] 5,679 distinct, 0% empty, from -77183.6 to 77183.6,
       mean 18.17 | e.g. '15.0', '19.8', ...
  "country" VARCHAR [category] 38 distinct, 0% empty | e.g. 'United Kingdom' (466,653),
       'Germany' (9,140), ...

Roles are inferred from the data, not from the column names: category = a small set of
repeated values; flag = a two-state flag; key = names a group of rows; measure = a number
to aggregate; temporal = a date or time; any day, month, quarter or year can be derived
from it.

Important facts about this file:
  - These columns are mostly empty, so any figure grouped or filtered by them covers only
    part of the data: "operator_note".
```

Three things to notice.

* The **role** in square brackets was worked out from numbers only, never from
  the column name. `infer_role` in `src/insights/context/roles.py` does it.
* The counts in brackets after category examples show how lopsided a column is.
  The United Kingdom is 466,653 rows out of 511,395. Worth knowing before you
  group by country.
* The last block is the **caveats**. They exist so the model can refuse for a
  concrete reason.

### Step 6. The planner asks the model

`plan_query` in `src/insights/planner/planner.py` sends two things.

* `SYSTEM_PROMPT`, the fixed rules, from `src/insights/planner/prompts.py`.
* The user prompt: the schema text above, then the question last.

The question goes last on purpose. Models pay most attention to the end of what
they are given, and the question is the part that changes.

It also sends `PLAN_JSON_SCHEMA`, which forces the reply into a fixed shape. The
model literally cannot reply with anything else.

Here is the **real raw reply**, 11.3 seconds later:

```json
{
  "answerable": true,
  "reason": "The query computes the total revenue for each product and returns the top 10 products by revenue.",
  "sql": "SELECT \"description\", SUM(\"line_revenue\") AS total_revenue FROM \"ds_0109cf5e01994a3ea9a1a6c32285fc58\" GROUP BY \"description\" ORDER BY total_revenue DESC LIMIT 10"
}
```

The field order is deliberate. `reason` comes before `sql`, so the model says in
words what it is about to do, then writes the query with that sentence already in
front of it. When `sql` came first, the model returned an empty `reason` every
single time.

### Step 7. The validator checks it

`validate_sql` in `src/insights/validator.py`. Three checks, in this order.

1. **Is it one statement, and is it a SELECT?** DuckDB's own parser decides.
2. **Does it read only our table?** The query is parsed again, by a library called
   sqlglot, and every table it mentions must be this dataset's table.
3. **Do the columns exist?** The database is asked to plan the query without
   running it, using `EXPLAIN`.

The order is not accidental. Check 2 runs before check 3, because planning a
query that mentions a file would open that file. Section 8 explains why that
matters.

It passed, and returned:

```
tables: ('ds_0109cf5e01994a3ea9a1a6c32285fc58',)
sql: SELECT "description", SUM("line_revenue") AS total_revenue FROM
     "ds_0109cf5e01994a3ea9a1a6c32285fc58" GROUP BY "description"
     ORDER BY total_revenue DESC LIMIT 10
```

That return value is a `ValidatedQuery`. The executor accepts nothing else, so
there is no way to run SQL that skipped this step.

### Step 8. The executor runs it

`run_query` in `src/insights/executor.py`.

It runs the query on a separate thread so the calling thread can cancel it if it
takes too long. It asks for 1001 rows when the limit is 1000, purely to find out
whether there were more, then returns 1000 and sets `truncated` to true.

Real result, 26 milliseconds:

```
columns: ['description', 'total_revenue']
  ['DOTCOM POSTAGE',                     186372.79]
  ['REGENCY CAKESTAND 3 TIER',           158569.32]
  ['WHITE HANGING HEART T-LIGHT HOLDER',  97408.35]
  ['PARTY BUNTING',                       97325.40]
  ['JUMBO BAG RED RETROSPOT',             89980.09]
  ['POSTAGE',                             63505.85]
  ['RABBIT NIGHT LIGHT',                  57058.18]
  ["PAPER CHAIN KIT 50'S CHRISTMAS",      56847.48]
  ['ASSORTED COLOUR BIRD ORNAMENT',       56629.68]
  ['CHILLI LIGHTS',                       51112.67]
row_count: 10 truncated: False ms: 26
```

**Be ready to be asked about the top row.** `DOTCOM POSTAGE` is a delivery
charge, not a product. The model grouped by `description` and that column holds
postage lines too. The system did exactly what it was asked. Deciding that
postage is not a product is a judgement about the business, and the system does
not make those. This is a good honest answer to give, and it is also why the
system shows you the SQL.

### Step 9. The job is marked done, and you poll

The worker writes the answer into the job row. Your browser, which has been
polling `GET /api/jobs/30667ec8...` every 600 milliseconds, sees `succeeded` and
draws the table, the sentence, and the SQL.

### Total time

About 11.4 seconds, and 11.3 of that was the model thinking. The database part
was 26 milliseconds. Worth remembering: the slow part of this system is never the
database.

---

## 5. Follow a CSV upload from start to finish

The file: `eval/data/bike_hire.csv`. 900 rows, 8 columns.

### Step 1. The upload arrives

```
POST /api/datasets
(a file attached)
```

`upload_dataset` in `src/insights/api/app.py` calls `_save_upload`, which does
three protective things.

* Checks the file extension is `.csv`, `.tsv` or `.txt`.
* Writes the file to disk **in one megabyte chunks**, counting as it goes, and
  stops the moment the total goes over the limit. If it read the whole file into
  memory first, anyone could flatten the server by sending a huge file.
* Names the file on disk from a random id, never from the name you uploaded.
  A filename you did not write is not something to trust.

You get a job id back with status 202.

### Step 2. The loader reads it

`load_csv` in `src/insights/ingest/loader.py`.

The SQL it runs:

```sql
CREATE OR REPLACE TABLE "ds_7b57dd93..." AS
SELECT * FROM read_csv(?, auto_detect = true, sample_size = -1)
```

* `CREATE TABLE ... AS SELECT` makes a table and fills it in one go.
* `read_csv` is DuckDB reading the file.
* `auto_detect = true` means "work out the separator, the quoting, whether there
  is a header row, and what type each column is".
* `sample_size = -1` means **read the whole file before deciding the types.**
  The default is to peek at the first 20,000 rows. That is faster. It is also
  how you end up calling a column a number when row 400,000 contains the word
  "unknown". On a 78 megabyte file this cost 0.86 seconds instead of 0.43.
* The `?` is the file path, passed separately rather than glued into the text of
  the query. Gluing user input into SQL is how injection attacks work.

If that fails, `LOAD_ATTEMPTS` has a second attempt that reads every column as
text. The file still loads, and the profile records that the types are not
trustworthy.

### Step 3. How it works out the types

It does not guess. DuckDB reads actual values and picks the narrowest type that
fits all of them. For `bike_hire.csv` it produced:

| Column | Type DuckDB chose |
| --- | --- |
| `Hire Ref` | VARCHAR, text |
| `Hired On` | DATE |
| `Station` | VARCHAR |
| `Minutes Used` | BIGINT, a whole number |
| `Fee Charged` | DOUBLE, a number with decimals |
| `Was Late` | BIGINT |

### Step 4. The profiler measures every column

`profile_table` in `src/insights/ingest/profiler.py`.

It builds **one** query with seven measurements per column. For 8 columns that is
56 measurements in a single pass over the data. Here is the real beginning of the
real query:

```sql
SELECT count("Hire Ref"),
       count(DISTINCT "Hire Ref"),
       NULL,
       NULL,
       NULL,
       avg(length("Hire Ref")),
       max(length("Hire Ref")),
       count("Hired On"),
       count(DISTINCT "Hired On"),
       min("Hired On"),
       max("Hired On"),
       NULL,
       NULL,
       NULL,
       ...
FROM "ds_7b57dd93..."
```

Why it looks like that:

* Seven slots per column, always, even when some are not useful. That way the
  code can pull out column number 5 by counting slots instead of matching names.
* The `NULL` entries are the unused slots. `Hire Ref` is text, so minimum,
  maximum and average mean nothing for it. `Hired On` is a date, so the length
  measurements mean nothing.
* `avg(length(...))` is only for text. It is the only way to tell a short product
  code apart from a sentence when both have thousands of different values.
* One query instead of one per column, so the file is read once rather than eight
  times.

Then one small query per column for example values:

```sql
SELECT CAST("Station" AS VARCHAR) AS value, count(*) AS frequency
FROM "ds_7b57dd93..." WHERE "Station" IS NOT NULL
GROUP BY value ORDER BY frequency DESC, value ASC LIMIT 5
```

Real answer:

```
[('Kings Cross', 365), ('Waterloo', 215), ('Camden Lock', 174),
 ('Shoreditch', 85), ('Peckham Rye', 61)]
```

`ORDER BY frequency DESC, value ASC` sorts by how common, then breaks ties
alphabetically. That tie breaker is not fussiness. These values go into the
prompt, and a prompt that changes between runs makes a wrong answer impossible to
reproduce.

Here is the real profile of one column:

```json
{
  "name": "Station",
  "sql_type": "VARCHAR",
  "logical_type": "text",
  "non_null_count": 900,
  "null_count": 0,
  "null_rate": 0.0,
  "distinct_count": 5,
  "distinct_rate": 0.0055,
  "is_unique": false,
  "mean_length": 10.19,
  "max_length": 11,
  "sample_values": [ {"value": "Kings Cross", "count": 365}, ... ]
}
```

### Step 5. The role is worked out

`infer_role` in `src/insights/context/roles.py` reads those numbers and picks one
of eight roles. First rule that matches wins.

| Role | How it is decided |
| --- | --- |
| `temporal` | the type is a date or a time |
| `flag` | a whole number whose smallest value is 0 and largest is 1 |
| `identifier` | at least 95% of values are different, and there are at least 20 of them |
| `key` | text, many different short values, each repeated |
| `category` | text, 50 or fewer different values |
| `free_text` | text averaging over 40 characters |
| `measure` | any other number |
| `unknown` | completely empty, or a type we do not handle |

`Station` has 5 different values out of 900, so it is a `category`.

**Nothing here looks at the column name.** That is the single most important
design decision in the project, and section 8 explains why.

### Step 6. It is saved, and the table is kept

`ingest_csv` in `src/insights/ingest/service.py` saves the profile with
`registry.save_profile`. The profile is stored as one JSON document in a table
called `meta.datasets`.

The order is: make the table, measure it, save the record. If measuring or saving
fails, the table is deleted before the error is passed on. A table with no record
would be invisible to the list of datasets and still sitting there, answerable by
a query nobody checked.

### Where this can go wrong

**A file with no header row.** This is the nastiest one, because nothing errors.
DuckDB decides there is no header, names the columns `column0`, `column1`, and
treats your header line as data. The loader spots the invented names and records
`header_detected: false`, and the context builder then tells the model the names
are positional and mean nothing. Nothing can recover what the columns were.

**A ragged file**, where rows have different numbers of fields. Same outcome.

**A header and no rows.** Rejected on purpose. A dataset with no rows would sit in
the list and answer every question with nothing.

**A very wide file.** The prompt describes at most 150 columns, set by
`max_context_columns`. Past that, columns are dropped and a caveat says how many.
The model is then working from a partial picture.

**A file that is not UTF-8.** DuckDB assumes UTF-8. A file saved in an older
Western European encoding with accented characters will either come out wrong or
fail. Nothing detects this.

**A file bigger than memory.** Reading it is fine, because it streams. Counting
different values across every column at once is not free. A very large file would
be slow rather than wrong.

---

## 6. Follow a question the system refuses

The question: **"Which supplier delivered the most late shipments?"**

The retail file has 25 columns. None of them is a supplier. None of them is a
delivery date.

Steps 1 to 5 are identical to section 4. The difference is what the model says.

Real raw reply:

```json
{
  "answerable": false,
  "reason": "The question asks for a supplier, but there is no column that identifies suppliers in the given table.",
  "sql": ""
}
```

`plan_query` in `src/insights/planner/planner.py` reads `answerable: false` and
builds a refusal:

```
plan.outcome : refusal
plan.sql     : None
plan.reason  : The question asks for a supplier, but there is no column that
               identifies suppliers in the given table.
```

Then in `answer_question`, `src/insights/answers.py`:

```python
if plan.is_refusal:
    return Answer(..., outcome=PlanOutcome.REFUSAL, reason=plan.reason, ...)
```

It returns straight away. **The validator never runs. The database is never
touched.** A question we declined costs nothing.

### Three things worth saying out loud about this

**A refusal is a success, not an error.** The job status is `succeeded`. The
`outcome` field says `refusal`. Nothing raised an exception. If a refusal were an
error, every caller would have to treat "your data cannot answer that" the same
way as "the server fell over".

**There is a second case that also becomes a refusal.** If the model says
`answerable: true` and then gives no SQL, `plan_query` turns that into a refusal
too. Passing an empty string to the database would produce an error message the
person who asked can do nothing with.

**A refusal is different from a wrong id.** Asking about a dataset that does not
exist gives a 404, not a refusal. A refusal is a statement about the data. If
there is no data, there is nothing to make a statement about.

### How the refusals are kept honest

The evaluation suites in `eval/suites/` contain 12 questions that cannot be
answered. Every one of them is currently refused correctly. That is the number to
quote, because it is the brief's central worry.

---

## 7. Each component, one section each

### Loader, `src/insights/ingest/loader.py`

**Owns** getting rows out of a file and into a table, and reporting honestly how
the types were decided.

**Does not own** any idea of what the data means.

**Key functions** `validate_source`, which checks the file exists, is not empty
and is not too big. `load_csv`, which does the work. `drop_table`, for cleaning
up after a failure.

**If you change it** the risk is type detection. Dropping `sample_size = -1` to
make it faster would reintroduce the bug where a column is typed from its first
20,000 rows.

### Profiler, `src/insights/ingest/profiler.py`

**Owns** measuring. Not null counts, different value counts, ranges, averages,
text lengths, and frequent values.

**Does not own** any conclusion drawn from those measurements.

**Key functions** `profile_table`, `classify_type`, `_column_statistics` for the
wide query, `_frequent_values` for the examples.

**If you change it** remember `_AGGREGATES_PER_COLUMN = 7`. The results are
sliced by position, so if you add a measurement you must change that number too
or every column will read the wrong values.

### Registry, `src/insights/registry.py`

**Owns** remembering each dataset's profile, keyed by id.

**Does not own** interpreting it.

**Key functions** `save_profile`, `get_profile`, `list_datasets`.

The profile is stored as one JSON document rather than as separate columns. The
profile keeps growing, and JSON absorbs that without having to change the table
every time. Nothing ever searches inside it. It is always read whole, by id.

### Context builder, `src/insights/context/` 

**Owns** turning measurements into the description the model sees. Roles,
caveats, and the exact text.

**Does not own** reading the file. It never touches the data again.

**Key functions** `build_context` and `render_for_prompt` in `builder.py`,
`infer_role` in `roles.py`, `_caveats` in `builder.py`.

**If you change it** this is the most sensitive module in the project. The
thresholds live in `src/insights/config.py` so they can be tuned without touching
the logic. Two separate wrong answers were fixed here by moving one sentence
closer to the column it applies to. See section 8.

### LLM client, `src/insights/llm/`

**Owns** talking to one model provider.

**Does not own** anything about questions or SQL.

**Key pieces** `LLMClient` in `base.py` is the shape every client must have. One
method. `OllamaClient` in `ollama.py` is the real one. `FakeLLMClient` in
`fake.py` returns scripted replies for tests. `build_client` in `__init__.py` is
the only place that decides which to build.

**If you change it** nothing above this folder has heard of Ollama, so swapping
provider is a new file plus one line in the provider map.

### Planner, `src/insights/planner/`

**Owns** getting a decision out of the model and turning it into a value.

**Does not own** deciding whether the SQL is safe, or whether it is correct.

**Key pieces** `SYSTEM_PROMPT` and `PLAN_JSON_SCHEMA` in `prompts.py`,
`plan_query` and `_parse` in `planner.py`.

`_parse` is deliberately suspicious. It copes with the model wrapping its answer
in a code fence. It rejects a reply that is not an object. It rejects a reply
that never says whether the question is answerable.

Why bother, when the model server already forces the shape? Because a rule
somebody else enforces is a convenience, never a guarantee. Swap the provider and
that rule is gone.

### Validator, `src/insights/validator.py`

**Owns** deciding whether the model's SQL may run.

**Does not own** running it.

**Key functions** `validate_sql`, and the three private checks
`_assert_single_select`, `_assert_known_tables`, `_assert_columns_resolve`.

**If you change it** the check order is load bearing and there is a test that
fails if you swap it. See section 8.

### Executor, `src/insights/executor.py`

**Owns** running a validated query under a row limit and a time limit.

**Does not own** deciding what is safe.

**Key function** `run_query`. Note its first argument is typed `ValidatedQuery`.
That is the guarantee. You cannot hand it a plain string.

**If you change it** loosening that type annotation would quietly remove the only
thing stopping unchecked SQL from reaching the database. A test watches for it.

### Job layer, `src/insights/jobs/`

**Owns** queueing work, recording what happened, and surviving a restart.

**Does not own** the work itself.

**Key pieces** `JobRunner.submit` and `JobRunner._run` in `runner.py`. The
storage functions in `store.py`, especially `fail_interrupted_jobs`. The two work
builders in `work.py`.

### API, `src/insights/api/`

**Owns** checking requests, status codes, one error shape, turning objects into
JSON.

**Does not own** any business logic. There is none here. That is why the command
line and the API give identical answers.

**Key pieces** `create_app` and the routes in `app.py`, the error handlers in
`errors.py`, the request and response shapes in `schemas.py`.

### Evaluation, `src/insights/evaluation/`

**Owns** measuring whether answers are right and refusals are correct.

**Does not own** anything the running system depends on. You could delete it and
the service would still work.

**Key pieces** `Case` and `Suite` in `suite.py`, `run_suite` and `_judge` in
`runner.py`.

The interesting idea: a test case stores its right answer as **SQL**, not as a
number. The harness runs that SQL and compares. So the expected answer is worked
out from the data every single run.

---

## 8. Every major decision

### Decision 1. DuckDB, with no separate server

**Chosen** DuckDB. It reads CSV files directly, works out the types, is fast at
adding things up, and the whole database is one file.

**Alternatives** PostgreSQL, the usual choice for a real service. SQLite, the
usual choice for a small one. Pandas, a Python library for working with tables.

**Why it won** PostgreSQL needs a server, a container and a separate loading
step, which fights against the promise of setting this up in fifteen minutes.
SQLite cannot read CSV on its own and treats most things as text. Pandas would
mean pulling half a million rows into Python memory to compute what the database
computes without leaving C++.

**The honest downside, and it shapes everything else.** DuckDB allows only one
program to write to the file at a time. That is why the background workers are
threads inside the web server rather than a separate service. A separate worker
program could not write to the same file. This design scales up, meaning a bigger
machine, and not out, meaning more machines.

### Decision 2. Work in the background, with polling

**Chosen** uploads and questions both return a job id straight away. You poll
until it is done.

**Alternatives** do the work while the caller waits. Or push updates to the
browser as they happen, using a technology called server sent events.

**Why it won** reading half a million rows takes seconds, and the model takes ten
seconds or more. A request held open that long gets cut off by something in the
middle, and the person sees a failure for work that actually succeeded.

**The honest downside** polling is slightly wasteful, and the client has to be
written to handle two steps instead of one. Live updates were rejected because
there is no real progress to report between "started" and "finished", and a
progress bar that moves for no reason is a lie.

### Decision 3. A language model writes the SQL

**Chosen** send a description of the data and the question to a model, and let it
write the query.

**Alternatives** build a fixed list of question templates. Or write a small
grammar that turns known phrasings into queries.

**Why it won** templates work until someone phrases a question slightly
differently, and they have to be rewritten for every new file. The whole point is
that a file nobody has seen should work with no code changes.

**The honest downside, and this is the big one.** The model is sometimes wrong,
and it is wrong in a way you cannot predict. The evaluation results: 28 of 33
cases pass. All five failures are questions whose answer must be worked out in
two steps rather than looked up. The same question shapes pass on an 8 column
file and fail on the 25 column one. That is the model's reasoning under a wider
schema, not a fault in the pipeline.

The second downside: answers are not perfectly repeatable, even with the
randomness setting turned to zero.

### Decision 4. Roles come from statistics, never from column names

**Chosen** the role of a column is worked out only from numbers. How many
different values, how many missing, what range, how long the text is.

**Alternative** the obvious one. A list of words. A column whose name contains
"price" is money. A column whose name contains "date" is a date.

**Why it won** this is the argument to have ready, because it is the best
decision in the project.

> The model already reads the column names. Whatever the column is called, the
> model can see what it is called. A list of words adds a **second** opinion
> about the same evidence. It is a worse opinion, it contradicts the name on any
> file not written in English business vocabulary, and somebody has to maintain
> it forever.
>
> What the model cannot see is that a column has 38 different values across half
> a million rows, or that a quarter of it is empty, or that its values average
> six characters. That is what this module adds, and it is all it adds.

**The honest downside, and volunteer it before they find it.** The system cannot
tell a price from a count. Both come out as `measure`. That is a statement about
meaning, and the only evidence for it is the name, which the model already has.
On the retail file, the customer id column is reported as a `measure`, because a
whole number with four thousand repeated values is, statistically, a measure.

### Decision 5. The validator parses the SQL instead of reading it

**Chosen** three checks, each done by whatever is best at it.

| Question | Answered by |
| --- | --- |
| Is it one statement, and is it a SELECT? | DuckDB's own parser |
| Does it read only our table? | sqlglot, walking the parsed query |
| Do the columns exist? | DuckDB's planner, via `EXPLAIN` |

**Alternative** the first version, which searched the text for dangerous words
like `DROP` and `DELETE`.

**Why it won** searching text does not understand text. Here is a perfectly ordinary query the word searcher rejected:

```sql
SELECT * FROM t WHERE "Branch Library" = 'Central;York'
```

It saw the semicolon inside the quotes and decided there were two statements.
There is only one. It also rejected any query touching a column literally named
`drop table t; --`. There is one of those in the test fixtures. **A guard that fires on valid queries
is not a safe guard. It is a broken product.**

The table check is an **allowlist**, not a list of banned things. Every table the
query mentions must be this dataset's table. A banned list would have to think of
every way to point DuckDB at other data, and it only has to miss one. The case it
would never have caught is **another dataset's table**, because that looks exactly
like the table we do allow.

Here are the real rejection messages:

```
reading a file                 Queries may only read the dataset's table, not files
                               or table functions
reading our bookkeeping        Table names may not be qualified with a schema or database
a column that does not exist   The query could not be resolved against this dataset
                                 Binder Error: Referenced column "supplier_name" not
                                 found in FROM clause!
not a SELECT                   Only SELECT queries may be run
reads no table                 The query does not read the dataset
two statements                 Only one statement may be run
```

**The check order is deliberate.** The table check runs before `EXPLAIN`. Here is
why. Asking the database to plan a query that mentions a file makes it open that
file, to see what columns are in it. So doing the checks the other way round
would leak whether a file exists, and what is inside it, without running a single
query. A test pins the order.

**The honest downside** two different parsers look at the query. sqlglot decides
which tables it reads and DuckDB decides what actually runs. They agree today. I
have no proof they agree on every possible query.

### Decision 6. One plain HTML page for the interface

**Chosen** a single file, `src/insights/ui/index.html`, with ordinary JavaScript
and no build step.

**Alternatives** React or a similar framework. Or Streamlit, a Python library
that makes simple data interfaces.

**Why it won** the brief says visual polish is out of scope. A framework brings a
build step, a package manager and hundreds of dependencies for a page with three
buttons. Streamlit would have been quick but it is not a real HTTP API, and the
brief asks for one.

**The honest downside** the page is plain, and all the logic lives in one file.
Past a few more features it would want structure.

---

## 9. What happens when things go wrong

### A bad CSV

| What is wrong | What happens |
| --- | --- |
| Not a `.csv`, `.tsv` or `.txt` file | Rejected immediately, 400, `invalid_file` |
| Empty file | Rejected immediately, 400 |
| Bigger than the limit | Rejected part way through the upload, before memory fills |
| Unreadable as CSV | The upload request succeeds. The **job** fails, with code `ingestion_failed` |
| Header row but no data | Job fails. A dataset with no rows is not useful |
| No header row | It loads. Columns are called `column0` and so on, and the model is told the names mean nothing |

Note the split. If the request was fine but the file was not, the request
succeeds and the job fails. That is the right shape: you did submit a valid
request, and the thing you asked for did not work out.

### The model gives bad SQL

Three different bad things, three different outcomes.

**It names a column that does not exist.** The validator refuses it. The job
fails with `unsafe_query`, and the message carries the database's own explanation.
Nothing runs.

**It writes something dangerous**, like reading a file or dropping a table. Same
path, refused by the validator.

**It writes SQL that is valid but will not run**, for example converting text to
a number when the text is not a number. Validation passes, because the query
makes sense. It fails at run time, and comes back as `query_failed`.

**It writes a query that is valid, safe, fast, and answers the wrong question.**
Nothing catches this. No validator can. This is what the evaluation suites are
for, and it is why the answer always shows the SQL.

A design choice worth defending here. Invalid SQL is reported as an **error**, not
as a refusal. Both show you no number, so nothing is invented either way. The
difference is the diagnosis. A refusal says "your data cannot answer this". An
error says "the planner went wrong". Blurring them would hide model failures
behind language that sounds fine.

### Two users at once

Fine, within limits.

* The job pool runs 4 jobs at a time by default, set by `job_workers`.
* Beyond 4, jobs wait in a queue you can see, instead of piling up invisibly
  inside the database.
* Every job takes its own database handle from `db.session()`. Handles are not
  shared between threads.
* Reading while someone else writes is safe. DuckDB handles that.
* The ceiling is one process. Two copies of the program cannot write to the same
  file.

There is a nice property worth knowing. Cancelling a query cancels only that
query. This was measured, not assumed. Two heavy queries on two handles, cancel
one, and the other finishes normally.

### A query that never finishes

`run_query` runs the query on another thread and waits 30 seconds by default. If
it is still going, it calls `interrupt()`. The query stops within about ten
milliseconds, the caller gets `query_timeout` with status 504, and the database
handle still works afterwards. There is a test that runs a normal query straight
after a cancelled one.

### The server dies mid job

The job rows in the database still say `running`. Nobody is working on them. A
client polling one would wait forever.

So on the next start, `fail_interrupted_jobs` in `src/insights/jobs/store.py`
finds every job still marked queued or running and marks it failed with "the
service restarted while this job was running". This is safe because the new
process has not started any jobs of its own yet, so anything in those states must
belong to the dead one.

The job is **not** resumed. Resuming would mean making every job safe to run
twice and able to restart from the middle, which is a lot of machinery for work
that takes a few seconds.

### Something fails during ingestion

The order is: create the table, measure it, save the record. If measuring or
saving fails, the table is deleted before the error is passed on. Otherwise you
would have a table in the database that the list of datasets knows nothing about.

### The model server is down

`OllamaClient` catches it and raises `LLMUnavailable`, which becomes a 503. The
message says the host it tried. Uploading still works. Only questions fail.

### Anything genuinely unexpected

`src/insights/api/errors.py` has a catch all handler. It writes the full details
to the server log, and sends back only this:

```json
{"error": {"code": "internal_error", "message": "Something went wrong handling this request"}}
```

No stack trace ever leaves the building. A stack trace tells a caller nothing
they can act on, and it can give away file paths and version numbers.

---

## 10. What was cut, and what I would build next

### Cut, and why

**Live progress updates on jobs.** Polling is enough. There is no real progress to
report between "started" and "finished".

**A separate worker service, or a queue server like Celery.** DuckDB allows one
writing program, so a separate worker could not write to the same file. Adding a
queue server would mean two more things to install and would still not solve it.

**Resuming interrupted jobs.** They are marked failed instead. Telling the caller
the truth costs eight lines. Resuming would cost a great deal more.

**Cleaning up orphaned tables.** If the process dies between creating a table and
saving its record, the table is left behind. A sweep would fix it. It has not
mattered yet.

**Login and user accounts.** Out of scope in the brief. Everyone sees everything.

**Charts.** A chart is a second way of being wrong about the same number. The
number and its SQL are what build trust.

**Cost tracking.** The model runs locally. The cost of a question is electricity.

**A synchronous question endpoint.** It would be handy for curl, and it would mean
two code paths to keep in step, plus an invitation to use the one that times out.

### Next, in order

1. **Retry invalid SQL once, showing the model its own error.** The database's
   error messages are precise and actionable. For a small model this is the
   single highest value change, and it only costs anything on the failure path.
2. **A bigger model behind the same interface.** The client is one method. Point
   it at a larger model, run the evaluation suites against two or three, and
   publish the table. That turns "which model" from an opinion into a
   measurement.
3. **A semantic layer.** Let someone say "revenue means this column". Store it
   beside the profile and show it to the model as a stated fact rather than a
   guess. This is what makes files with meaningless column names usable.
4. **Caching.** Same dataset, same question, same answer. Cheap, and it makes a
   demonstration feel instant.
5. **Choosing columns for very wide files**, instead of dropping everything past
   150.
6. **Tracing.** One id that follows a request through every stage, with the prompt
   and the raw reply recorded. Today, working out why an answer was wrong means
   running it again by hand.

---

## 11. Likely panel questions

### Easy

**1. What does this do?**
You upload a spreadsheet, you ask a question in English, and you get an answer
plus the SQL that produced it. It works on a file it has never seen, because it
measures the file when it arrives instead of being told about it in advance.

**2. Why DuckDB?**
It reads CSV directly, works out the types, is fast at adding things up, and
needs no server. The whole database is one file. The trade is that only one
program can write to it at a time.

**3. What is a job and why do you have them?**
Reading half a million rows takes seconds and the model takes about ten. Holding
a web request open that long gets it cut off somewhere in the middle. So you
submit, you get an id, you poll.

**4. Why is the model local?**
No API key, no network call, no cost per question, and nothing to fail in a room
with bad wifi. The trade is a smaller model that is weaker at multi step
reasoning, and the evaluation shows exactly where.

**5. What happens if I ask something the data cannot answer?**
It refuses and names what is missing. A refusal is a successful job with
`outcome: refusal`. It never runs a query.

**6. How do I know the answer is right?**
You do not have to take my word for it. Every answer carries the SQL that
produced it. Beyond that, the evaluation suites check 33 questions against
hand written queries.

**7. Where is the business logic in the API?**
There is none. The API checks the request, calls the engine, and formats the
reply. That is why the command line gives identical answers.

### Medium

**8. Show me where a column name from your dataset appears in the code.**
It does not. There is a test, `tests/test_no_dataset_knowledge.py`, that scans
every file under `src/` for the 27 column names in the development file and fails
if one appears. It runs in CI. It caught me once, in a docstring.

**9. How do you work out that a column is a date?**
I do not. DuckDB reads the whole file and decides the type. I then bucket that
type into a role. A date column becomes `temporal`.

**10. How do you tell a flag from a year? Both have two values.**
The measured smallest and largest value. A flag runs from 0 to 1. A year column
runs from 2010 to 2011. Nothing looks at the name.

**11. What stops the model running a DELETE?**
Three things. DuckDB's own parser says it is not a SELECT, so it is refused
before anything else happens. The executor only accepts a value the validator
produces. And the model is told not to, which is the weakest of the three and the
one I rely on least.

**12. Your profiler runs one query per column for the examples. Why not fold it
into the big one?**
There is a function that would, called `histogram`, but it builds a map of every
different value. On a column with 25,000 different invoice numbers that is a bad
trade. The statistics are one pass. Only the examples are per column.

**13. What happens to a query that runs forever?**
It is cancelled after 30 seconds. I measured three things rather than assuming
them. The query stops in about ten milliseconds, the handle still works
afterwards, and cancelling one query does not disturb another running at the same
time.

**14. Why is an invalid query an error and not a refusal?**
Both show no number, so nothing is invented either way. The difference is
diagnosis. A refusal means your data cannot answer it. An error means my planner
went wrong. If I blurred them, model failures would hide behind language that
sounds correct, and the evaluation could not count them separately.

**15. Why do you read the whole file to work out the types?**
Because reading a sample gets it wrong on a column that looks like a number for
20,000 rows and then contains the word "unknown". On a 78 megabyte file it cost
0.86 seconds instead of 0.43.

**16. What is in the prompt?**
A fixed set of rules that mentions no column, no table and no business. Then the
measured description of this file. Then the question, last, because models attend
most reliably to the end.

**17. How do you test something that has a language model in it?**
I split it in two. Our code is tested against a scripted client that returns
whatever I tell it, including nonsense. Whether the model is any good is a
separate question, answered by the evaluation suites. A test that fails because
the model had an off day is one nobody will trust or fix.

### Hard

**18. Why no name matching heuristics?**
The model already reads the names. A word list adds a second, worse opinion about
the same evidence, it breaks on any file not in English business vocabulary, and
it needs maintaining forever. What the model cannot see is the statistics. That
is what I contribute. The cost is that I cannot tell a price from a count, and I
say so.

**19. Show me you cannot read another dataset.**
The table check is an allowlist. Every table mentioned must be this dataset's
table or a scratch pad defined in the query itself. A banned list would never
have caught this case, because another dataset's table name looks exactly like
the one we allow. There are tests for reading one and for joining to one.

**20. Why check the columns with EXPLAIN rather than yourself?**
Because doing it myself means reimplementing how SQL resolves names.
`SELECT sum(a) AS s FROM t ORDER BY s` refers to `s`, which is not a column, and
it is valid. Scratch pads have the same problem. The database already does it
correctly, and `EXPLAIN` does it without running anything.

**21. Why does the table check come before EXPLAIN?**
Because planning a query that mentions a file makes the database open that file
to see its columns. If I asked the planner first, I would leak whether a path
exists and what is in it, without ever running a query. A test pins the order.

**22. What is the worst thing about this design?**
One process. DuckDB allows one writer, so this scales up and not out. If two
teams needed it at once I would move the storage to something with a server, and
the seam for that already exists between the executor and everything else.

**23. What are you least confident about?**
Two parsers look at the SQL. sqlglot decides which tables it reads and DuckDB
decides what runs. They agree today. I cannot prove they agree on every query.

**24. Your accuracy is 28 out of 33. Why not higher?**
Twelve of twelve unanswerable questions were refused, so it never invented an
answer. All five failures are the same shape: answers that have to be worked out
in two steps rather than looked up. The same shapes pass on the 8 column file and
fail on the 25 column one, so it is the model under a wider schema, not the
pipeline. I tried twice to fix it in the prompt and stopped, because going
further would have meant tuning the prompt to one dataset, which is the thing the
brief warns against.

**25. Your top product is DOTCOM POSTAGE. Is that right?**
The query is right and the answer is not useful. Postage is in the description
column, so grouping by description includes it. Deciding postage is not a product
is a judgement about the business, and the system does not make those. This is
exactly why the answer always shows the SQL. The fix is the semantic layer in my
next steps.

**26. Temperature is zero. Why are answers not identical every time?**
Zero removes one source of randomness, the sampling. It does not remove the
others. Work is batched inside the model server and floating point addition is
not perfectly associative, so identical input can still take a slightly different
path.

### The two live ones

**27. Here is a CSV you have not seen. Load it and answer questions.**

What I would say while doing it:

> I will upload it in the interface. Nothing in the code changes, and nothing
> needs to. Watch the schema panel: that is the system telling you what it worked
> out from the file itself, with no help from me.

Then open **Show the schema the model is given** and talk through a couple of the
roles, pointing out that they came from the numbers. If a question gets refused,
that is a good moment, not a bad one: read out the reason and check it against
the column list.

If it goes wrong, the honest line is: the schema panel is everything the model
knew, so let us look at it together and see what was missing.

**28. Add this feature. Where does it land?**

The general answer, then three worked examples.

> Changes land in exactly one component, because each one owns one thing. Tell me
> which of these the feature is about: reading files, describing data, writing
> SQL, checking SQL, running SQL, or the shape of the API.

*"Let users say revenue means this column."*
A semantic layer. It lands on `ColumnContext` in `src/insights/models/context.py`
as a user supplied override, applied after `infer_role` in
`src/insights/context/roles.py`, and rendered by `render_for_prompt` as a stated
fact rather than a guess. Storage goes next to the profile in the registry. No
other component changes.

*"Support Excel files as well as CSV."*
`src/insights/ingest/loader.py` only, plus the allowed extensions in
`src/insights/api/app.py`. Everything downstream works from the profile, and the
profile does not care where the rows came from.

*"Use a hosted model instead of a local one."*
One new file in `src/insights/llm/` implementing the `LLMClient` shape, one entry
in the provider map in `src/insights/llm/__init__.py`, and one setting. Nothing
above that folder has heard of Ollama.

*"Let people ask follow up questions that refer to the last answer."*
This one is genuinely bigger, and I would say so. The planner is deliberately one
exchange with no history. I would ask the stakeholder one question first: should
a follow up reuse the previous SQL, or just the previous subject?

Then three changes. The previous question and its SQL go into the user prompt in
`build_user_prompt`. The history lives in the job record, not in the planner, so
the planner stays one exchange with no memory of its own. The validator does not
change at all, because it must still check the final SQL on its own merits.

---

## 12. Self test

Answer these out loud before you look. If you need the hint, you have not got it
yet.

**1.** Why does the system read the whole CSV before deciding column types?

<details><summary>Answer</summary>

Because a sample of the first 20,000 rows gets the type wrong when a column turns
messy later in the file. On the 78 megabyte development file this cost 0.86
seconds instead of 0.43. A wrong type is worse than a slow load.

</details>

**2.** What is the difference between `count(*)` and `count("Station")`?

<details><summary>Answer</summary>

`count(*)` counts every row. `count("Station")` counts only rows where `Station`
has a value. The gap between them is how many values are missing, and the
profiler uses exactly that to work out the null rate.

</details>

**3.** In the self join that finds products bought together, what does
`a."description" < b."description"` do?

<details><summary>Answer</summary>

Two things. It stops a product pairing with itself, and it keeps each pair only
once instead of twice in both orders. Comparing text with `<` is alphabetical, so
exactly one ordering survives.

</details>

**4.** A refusal and a 404 both mean you get no data. What is the difference?

<details><summary>Answer</summary>

A refusal is a statement about the data: the file cannot answer this question. It
is a successful job. A 404 means the dataset id does not exist, so there is no
data to make a statement about. That is a bad request.

</details>

**5.** Why does the `reason` field come before `sql` in the model's reply format?

<details><summary>Answer</summary>

Because the format is enforced in order, so the model writes the sentence first
and then writes SQL with that sentence in front of it. When `sql` came first, the
model returned an empty reason every single time, having already said everything
it had to say.

</details>

**6.** Why is there a minimum length on the `reason` field?

<details><summary>Answer</summary>

Because an empty string satisfies "this must be text", and it is the cheapest
thing to produce. The minimum length is enforced while the model generates, so it
cannot take that shortcut even if told to.

</details>

**7.** Why does the table check run before `EXPLAIN`?

<details><summary>Answer</summary>

Because planning a query that mentions a file makes DuckDB open that file to read
its columns. Checking afterwards would leak whether a path exists and what is in
it, without running anything. A test pins the order.

</details>

**8.** What is a `ValidatedQuery` and why does it exist?

<details><summary>Answer</summary>

It is the type the validator returns. The executor accepts nothing else, so there
is no way to run SQL that skipped validation. The type is the guarantee, not a
convention somebody has to remember.

</details>

**9.** The old validator searched the SQL text for dangerous words. Give two
queries it got wrong.

<details><summary>Answer</summary>

A query containing a semicolon inside quoted text, like
`WHERE "Branch Library" = 'Central;York'`, which it called two statements. And
any query touching a column literally named `drop table t; --`, of which there is
one in the test fixtures.

</details>

**10.** Why are the job records stored in the database rather than in memory?

<details><summary>Answer</summary>

So that a process which dies mid job does not leave a client polling a job that
can never change. On the next start, anything still marked running belongs to the
dead process and is marked failed.

</details>

**11.** Why are the background workers threads rather than a separate program?

<details><summary>Answer</summary>

DuckDB allows one writing program at a time, so a separate worker could not write
to the same file. It is a consequence of the storage choice, not a shortcut.

</details>

**12.** Why are roles worked out from statistics rather than column names?

<details><summary>Answer</summary>

Because the model already reads the names. A word list adds a second, worse
opinion about the same evidence, breaks on files not in English business
vocabulary, and needs maintaining forever. The statistics are the thing the model
cannot see.

</details>

**13.** What is the accepted cost of that decision?

<details><summary>Answer</summary>

The system cannot tell a price from a count. Both come out as `measure`. On the
retail file, the customer id column is reported as a measure, because a whole
number with thousands of repeated values is, statistically, a measure.

</details>

**14.** An evaluation case stores its right answer as SQL rather than as a
number. Why?

<details><summary>Answer</summary>

A stored number rots. It was copied from a run that may itself have been wrong,
it breaks when the file changes, and it cannot be reused on a different file.
Stored SQL is recomputed from the data every run, and reviewing a case means
reading a query rather than trusting a figure.

</details>

**15.** Name one thing that could still go wrong that no part of this system
catches.

<details><summary>Answer</summary>

SQL that is valid, safe, fast, and answers the wrong question. No validator can
catch that. It is why the evaluation suites exist and why every answer shows the
SQL that produced it. The `DOTCOM POSTAGE` result is a live example: the query was
right and the answer was not useful.

</details>

---

## Where to go next

| File | What is in it |
| --- | --- |
| `README.md` | How to run it and how to ask it a question |
| `docs/system-design.md` | The design argument, written for the panel |
| `docs/walkthrough-notes.md` | Shorter notes on the same ground, plus every generated query |
| `docs/decisions.md` | The log written as each piece was built, with the bugs found |
| `docs/assumptions.md` | Every judgement call made where the brief did not say |
| `docs/status.md` | What is done, what is not, and what was never verified |
