# Assumptions

Every judgement call made where the brief did not say, and the reason for it.
Listed so that a reviewer can disagree with the call rather than guess at it.

## About the model

**The model runs locally, through Ollama, on `qwen2.5-coder:7b`.**
The brief allows any stack the author can explain. A local model needs no API
key, costs nothing per question, and cannot fail because the wifi in the room is
bad. The cost is real and is stated plainly in the design document: a 7B model
is weaker at multi step reasoning than a frontier model, and the evaluation
numbers show exactly where.

**The machine has 8 GB of video memory, which set the model size.**
The 7B model at four bit quantisation is about 4.7 GB and leaves room for a long
schema prompt. The 14B model does not fit and would answer in tens of seconds
from the CPU.

**A provider swap is one file.** Everything above `src/insights/llm/base.py` is
written against a protocol with one method. Moving to the Anthropic API or to
OpenAI means one new client and one changed setting.

## About the data

**One table per file. No joins across datasets.**
Every question is answered from a single ingested file. The brief describes a
transactional CSV, not a warehouse. Allowing joins across datasets would mean
solving relationship inference with no schema to go on, and the validator
deliberately refuses it.

**Returns are left in when revenue is summed.**
The evaluation suites define net revenue as the sum of the revenue column with
returns included, because a return is a real reduction in revenue. This is a
business judgement, so it is written into the truth SQL of each case where a
reviewer can see it and argue with it.

**Growth means the absolute change, not the percentage.**
A percentage rewards whichever group started nearest to zero. Stated in the
evaluation cases that measure growth.

**The development CSV is not committed.**
It is 78 MB. The README says where to get it. Two smaller datasets are
committed, so the tests and two of the three evaluation suites run from a clean
clone with no downloads.

## About evaluation

**Expected answers are written as SQL, not as numbers.**
A recorded number rots. It is copied from a run that may itself have been wrong,
it breaks when the file changes, and it cannot be reused on a second file. Truth
SQL is read and argued with, and it is recomputed from the data on every run.

**The library loans suite has no ranking cases.**
That fixture was built for unit tests and its categories are perfectly uniform:
75 loans at each of four branches, five loans of each catalogue item. Every
ranking over it is a tie with no single right order, so a ranking case there
would grade the model on a coin toss. Ranking is covered by the bike hire suite,
whose data is deliberately skewed.

**The market basket question is graded on the first product of the top pair.**
Grading the pair itself would mean insisting on a column order and a naming
convention that the model has no way to guess. The case would then fail for
reasons that are not about correctness.

## About the service

**Ingestion and questions are both jobs, with no synchronous option.**
The brief requires that neither blocks the caller. Offering a synchronous path
as well would mean two code paths to keep in step and would invite callers to
use the one that times out.

**Jobs are stored in DuckDB, not in memory.**
So that a process which dies mid job does not leave a client polling a job that
can never change. Any job still marked running at startup belongs to a dead
process and is closed out.

**Workers are threads inside the API process, not a separate service.**
DuckDB allows one writing process, so a separate worker process could not write
to the same file. This is a consequence of the storage engine, not a shortcut.

**There is no authentication and no multi tenancy.**
Out of scope in the brief. Every caller sees every dataset.

## About the environment this was built on

These are facts about the machine, checked rather than assumed. Each one changed
a decision.

**Docker is not installed here, so the Docker path is written but unverified.**
The `Dockerfile` and `docker-compose.yml` are complete and reviewed, and the
compose file starts the model server, pulls the model, and waits for the pull
before starting the API. Neither has been run. The Python path in
`scripts/run.ps1` was verified from a clean clone and is the path the README
recommends first. This is stated again in `docs/status.md`, because claiming a
verified setup that was never run is the kind of thing a walkthrough finds out.

**Node is not installed, so the architecture PNG is drawn with Pillow.**
Mermaid needs Node to render. The Mermaid source is in `docs/architecture.mmd`
and GitHub renders it inline in the design document. The PNG is produced by
`scripts/render_architecture.py`, so it can be regenerated rather than being a
binary nobody can change.

**ffmpeg is not installed, so the GIFs are assembled with Pillow.**
Playwright drives the real UI in a headless browser and takes screenshots.
Pillow writes the animated GIF. Runs of identical frames are collapsed, which is
what keeps each file under 300 KB.

**The GitHub CLI is installed but not logged in, and no token is present.**
The session that produced this work could not create a repository or push. Every
commit is on `main` locally. The exact commands to finish are in
`docs/status.md`.

**Git identity was set to `rsidd` with the email on this machine.**
No full name was available to use. Change it with `git config user.name` and
amend if the commits should carry a different author.
