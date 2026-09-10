# Daily Habit Tracker

A command-line habit tracker: add habits, tick them off each day, and see your
current and longest streaks. Built with an AI coding assistant **one prompt at a
time**, not one prompt for the whole thing.

```
$ python main.py done "Read 20 pages" --value 24
Read 20 pages: done for 2026-09-10. Streak: 4 days.
```

Everything stays on your machine. Nothing is sent anywhere.

---

## Assignment requirements

| # | Requirement | Where it lives |
|---|---|---|
| 1 | At least 4 Python files/modules | `main.py` + 5 modules in `app/cli/` (the project has ~110 in total) |
| 2 | One package | [`app/cli/`](app/cli/) — and `app/` with ten subpackages |
| 3 | `try` / `except` / `finally` | [`app/cli/__main__.py`](app/cli/__main__.py) `main()`; also `UnitOfWork.__exit__` and `Database.session()` |
| 4 | At least one custom exception | [`app/core/errors.py`](app/core/errors.py) — `AppError` and eight subclasses, including `CommandError` |
| 5 | Logging to a file | [`app/core/logging_config.py`](app/core/logging_config.py) → `logs/habit_tracker.log` (rotating, 2 MB × 5) |
| 6 | Imports between modules | `__main__` → `parser` + `commands`; `commands` → `formatters` + the service layer |
| 7 | README with 5+ AI prompts | [below](#ai-prompts-used) — ten of them, one per step |

---

## Quick start

Requires **Python 3.12+**.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

pip install -e ".[dev]"

python main.py --help
```

No database setup: the first command creates `data/habit_tracker.db` and applies
the migrations itself.

After `pip install -e .` the tool is also on your path as `habits`, so
`habits today` works from anywhere. Every example below uses `python main.py` so
it runs straight from a clone.

---

## Commands

```
add         Create a habit
list        List habits with their streaks
done        Tick a habit off for a day
undo        Remove a habit's log for a day
stats       Streaks and completion rate for one habit
remove      Delete or archive a habit
today       The day's overview and score
week        The weekly review
sleep       Record a night's sleep
time        Log time against a category
categories  List the configurable categories
task        Add a task
tasks       List the day's tasks
complete    Complete a task by its id
```

Two conveniences worth knowing:

- **Habit names take a prefix.** `done "Read"` finds "Read 20 pages". An exact
  match always wins, and an ambiguous prefix lists the candidates rather than
  guessing.
- **`--date` speaks English.** `--date yesterday`, `--date -3`, or
  `--date 2026-09-07`. Typing an ISO date for "the day before yesterday" is
  exactly the friction that stops people backfilling.

---

## Verified run

Captured from a real terminal, not retyped.

```console
$ python main.py add "Read 20 pages" --type count --target 20 --unit pages
Added 'Read 20 pages' - 20 pages.

$ python main.py add "Meditate" --type duration --target 20 --min 10 --unit minutes
Added 'Meditate' - 20 minutes.

$ python main.py add "Wake up early" --type time --at 06:30 --before
Added 'Wake up early' - before 06:30.

$ python main.py list
Habits on 2026-09-10  (last 21 days on the right)

   Habit          Target        Streak  Rate  Recent
-  -------------  ------------  ------  ----  ---------------------
✓  Meditate       20 minutes    6d      29%   ···············✓✓✓✓✓✓
✓  Read 20 pages  20 pages      4d      38%   ············✓✓✓✓·✓✓✓✓
✓  Standup        Done or not   4d      27%   ·················✓✓✓✓
✓  Wake up early  before 06:30  4d      19%   ·················✓✓✓✓

$ python main.py stats "Read 20 pages" --days 14
--------------------------------------------------------
                     READ 20 PAGES
--------------------------------------------------------
Target         20 pages
Current streak 4 days
Longest streak 4 days
Completed      8 of 14 due
Completion     57%          🔴
Missed         6 days
Last 7 days    86%          🟡
Last 30 days   38%          🔴
Last completed 2026-09-10

2026-08-28 to 2026-09-10
·····✓✓✓✓·✓✓✓✓

$ python main.py today
--------------------------------------------------------
                  THURSDAY 2026-09-10
--------------------------------------------------------
Sleep          7h       🟢
Tasks          1 / 2    🔴
Habits         4 / 4    🟢
Exercise       0m
Studying       2h 10m   🟢
Coding         1h 45m   🟢
Teaching       1h       🟢
Free time      12h 05m

--------------------------------------------------------
Daily score: 82/100
  Task completion      + 16.7   50% of tasks
  Habit consistency    + 26.7   100% of habits due
  Sleep                + 18.7   7h of 7h 30m
  Learning             + 20.0   4h 55m of 4h 30m
  (not counted: exercise, focus)
--------------------------------------------------------
```

### Failure cases

```console
$ python main.py done "Jogging"
error: No habit matching 'Jogging'
       Known habits: Meditate, Read 20 pages, Standup, Wake up early.
  exit code: 1

$ python main.py done "Read 20 pages"
error: 'Read 20 pages' records an amount
       Try: habits done "Read 20 pages" --value 20

$ python main.py done "Meditate" --value 25 --date 2026-12-25
error: You can only record a habit for today or a past date.

$ python main.py done "Meditate" --date "next tuesday"
habits done: error: argument --date: 'next tuesday' is not a date I understand.
Use YYYY-MM-DD, 'today', 'yesterday', or '-3' for three days ago.

$ python main.py time Alchemy 60
error: No time category called 'Alchemy'
       Available: Coding, Teaching, Studying, Work, Reading, Exercise, Cricket,
       Personal, Entertainment, Travel, Other
```

No traceback in any of them — that is deliberate, and there is a test for it.

### The log this produced

`logs/habit_tracker.log`, from the two commands above:

```
2026-09-10 18:26:31 | INFO    | habit_tracker.bootstrap | build_container:192 | Container built for profile 1 in Asia/Kolkata (development)
2026-09-10 18:26:31 | INFO    | habit_tracker.cli.commands | dispatch:730 | Running command 'done'
2026-09-10 18:26:31 | WARNING | habit_tracker.services.habit_service | log:209 | Habit 2 already had a log for 2026-09-10; updating it
2026-09-10 18:26:31 | INFO    | habit_tracker.cli.__main__ | main:107 | Command 'done' finished
2026-09-10 18:26:32 | INFO    | habit_tracker.cli.commands | dispatch:730 | Running command 'done'
2026-09-10 18:26:32 | WARNING | habit_tracker.cli.__main__ | main:75 | Command 'done' rejected: No habit matching 'Jogging'
2026-09-10 18:26:32 | INFO    | habit_tracker.cli.__main__ | main:107 | Command 'done' finished
```

Three things to notice. The `Command 'done' finished` line appears after the
*rejected* one too — that is the `finally` block running on the error path. The
WARNING for a habit logged twice in one day is the rule the brief asked for. And
no user text is ever written to the log: ids, dates and counts only.

---

## The `try` / `except` / `finally`

In [`app/cli/__main__.py`](app/cli/__main__.py):

```python
try:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)  # inside the try on purpose
    ...
    container = build_container()
    return dispatch(container, args)

except CommandError as error:  # the user can fix this
    print(f"error: {error.user_message()}", file=sys.stderr)
    if error.hint:
        print(f"       {error.hint}", file=sys.stderr)
    return EXIT_USER_ERROR

except AppError as error:  # a rule or the database refused
    ...
except KeyboardInterrupt:
    return EXIT_INTERRUPTED
except Exception:  # a bug: log it, do not print it
    logger.exception("Command %r crashed", command)
    return EXIT_INTERNAL

finally:
    if container is not None:
        container.dispose()
    logger.info("Command %r finished", command)
```

The `finally` earns its place. A CLI run holds an open SQLite connection with
WAL files beside it; exiting without disposing the pool leaves `-wal` and `-shm`
files behind, and the next command — or the web UI — can find the database
locked. Two tests assert the disposal happens: one on the success path, one when
`dispatch` raises.

`parse_args` is *inside* the try because argparse runs type converters during
parsing. A converter that raised outside this block printed a traceback before
the handler could stop it — see "what the AI got wrong", item 7.

## The custom exceptions

[`app/core/errors.py`](app/core/errors.py):

```
Exception
└── AppError                 message + structured details + a user-facing hint
    ├── ValidationError      a business rule rejected the input
    ├── NotFoundError        no such record, or not owned
    ├── ConflictError        duplicate habit, second log for a day, overlap
    ├── DatabaseError        the database refused or is unreachable
    ├── ConfigurationError   the app cannot start correctly
    ├── DataImportError      unreadable or invalid import file
    ├── DataExportError      an export could not be produced
    └── CommandError         a CLI invocation argparse cannot catch
```

Every one carries two messages: `message` plus `details` for the log, and
`user_message()` for the screen. `CommandError` adds a `hint` — the line that
tells you what to type instead.

The import/export errors are deliberately **not** called `ImportError` and
`ExportError`. Defining a class named `ImportError` shadows the builtin in every
module that imports it, which turns an unrelated failed import into a baffling
bug report.

---

## AI prompts used

The assignment asks for at least five. These are the ten, one per step of the
vibe-coding loop, in the order they were used. The note under each says why that
prompt and what it changed.

### Step 1 — Understand the requirement

> **Prompt 1.** I have to build a command-line Daily Habit Tracker in Python as a
> college assignment. The requirements are: at least 4 Python files, one package,
> try/except/finally, at least one custom exception, logging to a file, and
> imports between modules. Before writing any code, ask me the questions you need
> answered to get the design right — especially about how streaks should be
> counted and where the data is stored. Do not write code yet.

*Why first:* it forces the ambiguity into the open. "Streak" has at least three
reasonable definitions and picking one is my decision, not the assistant's. The
answer I gave — today counts if it is still in progress, a rest day is not a
miss — is the reason `current_streak` has a `grace_today` parameter.

### Step 2 — Suggest the structure

> **Prompt 2.** Based on those answers, propose a package/module structure. I want
> the package to contain only reusable logic and `main.py` to be the CLI outside
> it. For each module give me one sentence on what it is responsible for, and tell
> me the import direction between them so we do not end up with a circular import.
> Structure only — still no code.

*What changed:* the first proposal stored everything in a JSON file. I pushed
back — streaks over months want date-range queries, not a full file read — and
the structure that came out uses SQLite behind a repository layer. `main.py`
stayed outside the package, as asked.

### Step 3 — Generate one module

> **Prompt 3.** Write only the streaks module. It takes a list of dates a habit was
> completed on and returns current streak, longest streak, and completion rate. No
> file I/O, no printing, no logging — pure functions, so I can test it on its own.
> Add three or four cases including an empty list.

*Why streaks first:* it is the only module with logic worth getting wrong, and it
has no dependencies, so it can be run immediately. It is now
[`app/domain/habits/streaks.py`](app/domain/habits/streaks.py) and still imports
nothing from the database.

### Step 4 — Run it

*(No prompt. Run it and read the output.)*

### Steps 5 and 6 — Find an error, and get it fixed

> **Prompt 4.** Running the streaks module gives me **[the real output]** for
> **[this input]**. Explain what is actually happening before you change anything,
> then give me the smallest fix — not a rewrite of the module.

*Why "explain before you change":* a fix I cannot explain is a fix I cannot defend
on camera. This caught the completion rate going over 100% — see item 4 below.

### Step 7 — Exception handling

> **Prompt 5.** Now write the errors module: a base class and subclasses for "not
> found", "duplicate", "invalid date" and "storage failed". Each one should carry
> the relevant data as attributes (habit name, the bad date) rather than only a
> message string, so callers can branch on the type and still get at the detail.
> Then use `try/except/finally` in the entry point and the database session so a
> failure part-way through cannot leave things half-written.

### Step 8 — Logging

> **Prompt 6.** Add a logging module with `setup_logging()` and `get_logger(name)`,
> writing to a file. Use a named logger with child loggers per module, not
> `basicConfig`. Then add log calls: INFO for a habit added or ticked, WARNING for
> a habit logged twice on the same day, ERROR for a save that failed. Do not log
> inside the streaks module — it stays pure.

*Why not `basicConfig`:* it attaches handlers to the *root* logger, so every
library's chatter lands in the application's log file too.

### Step 9 — Refactor

> **Prompt 7.** Review the CLI entry point and tell me what is wrong with it before
> changing anything. I think the command dispatch is a long if/elif chain and the
> argument parsing is duplicated. Propose the refactor, wait for me to agree, then
> apply it.

*Result:* the if/elif chain became the `COMMANDS` dict in
[`app/cli/commands.py`](app/cli/commands.py), and the duplicated date parsing
became one `--date` converter.

> **Prompt 8.** The package `__init__.py` is empty. Make it the front door: re-export
> the names the entry point actually needs, add `__all__`, and explain in a comment
> what this file gives me that four loose modules would not.

### Step 10 — Test

> **Prompt 9.** Give me a list of the inputs that should break this program — bad
> dates, duplicate names, a habit that does not exist, a date in the future,
> unicode in a habit name, an ambiguous prefix. For each one tell me what the
> program *should* do. I will run them myself and tell you which ones are wrong.

> **Prompt 10.** These cases behaved wrongly: **[the real results]**. Fix them one at
> a time, smallest change first, and tell me which exception class each case
> should raise.

*Result:* the failure cases in the "Verified run" section above, plus items 7, 8
and 9 below.

---

## What the AI got wrong

The honest list. This is the part that proves the project was driven rather than
pasted, and every item below has a fix you can point at in the code.

**1. It built the wrong kind of application.** Given the full brief, the
assistant produced a *Streamlit web app* — polished, tested, and not what the
assignment asked for. The requirement said "command-line". Nothing in the
architecture was wasted, because the business rules were already out of the
presentation layer, so the CLI in `app/cli/` is about 600 lines calling the same
services. But it is the biggest single thing it got wrong, and no amount of test
coverage would have caught it: only re-reading the brief did.

**2. `list(SomeStrEnum)` silently loses the type.** A `StrEnum` member *is* a
string, so the type checker widens `list(TaskPriority)` to `list[str]` and every
call site quietly stops being type-safe. Fourteen of them. Fixed once with
`members()` in [`app/models/enums.py`](app/models/enums.py); mypy found it, not a
test.

**3. Completion rates over 100%.** A habit due on weekdays, completed on a
Saturday, reported "123% of days due" — bonus completions were counted against
the number of days the habit was actually due. Fixed in `summarize()`: only
completions on expected days count towards the rate.

**4. A read-only transaction destroyed its own results.** Rolling back a unit of
work that only *read* expired every loaded row, so the caller got
`DetachedInstanceError` the moment it touched one. `UnitOfWork.__exit__` now
closes a read-only block instead of rolling it back.

**5. 1,110 queries to draw one calendar.** Scoring a year called
`get_or_create` per day: two round trips × 365. Replaced with one range read and
two bulk writes. A test asserts the query *count*, not just the wall-clock time —
a full-table scan on an SSD is still fast enough to pass a timing test.

**6. A day's task list showed 134 overdue items.** "Include overdue tasks" with
no bound is fine on day one and unusable after three months. Now capped at 14
days with a line saying how many older ones are hidden.

**7. A bad `--date` printed a traceback.** Argparse runs type converters *during
parsing*, before the entry point's `try` block exists. The converter raised
`CommandError`, argparse let it through, and the user got a stack trace — with
the "never show a traceback" rule written in the same file. Fixed with an
adapter that re-raises `argparse.ArgumentTypeError`.

**8. `--plain` only worked in one position.** `habits --plain list` worked;
`habits list --plain` was a usage error. Nobody types the first one. Fixed with a
shared parent parser, and `SUPPRESS` so the subparser's default cannot overwrite
a value given earlier.

**9. Nothing could be backfilled.** `add` set the habit's start date to today, and
the service correctly refuses to log a habit before it existed — so a new habit
could never record last week. Found by trying to build the demo above. Fixed with
`--since`, and the error now names the flag that fixes it.

**10. The log file stopped after the first line.** Startup runs Alembic, and
Alembic's `env.py` calls `logging.config.fileConfig()` — whose
`disable_existing_loggers` argument defaults to **True**. Every `habit_tracker.*`
logger was switched off a fraction of a second after being configured, so the
log held one migration message and nothing else. Found by reading the log to
paste into this README, not by any test. Fixed in
[`app/database/migrations/env.py`](app/database/migrations/env.py), with a
regression test that asserts the loggers survive a migration.

**11. Charts with junk on them.** The calendar heatmap had a stray axis rule and
tick marks across it. Nothing catches that but rendering the page and looking at
it, which is the only reason it was found.

---

## How it is built

```
main.py                    thin shim so `python main.py` works from a clone
app/cli/                   the command-line interface
  parser.py                the grammar (argparse)
  commands.py              one handler per verb, calling services
  formatters.py            terminal rendering, with an ASCII fallback
  __main__.py              parsing, try/except/finally, exit codes
app/services/              business rules, one unit of work per operation
app/domain/                pure functions: streaks, sleep, scoring, insights
app/repositories/          the only place SQL is written
app/models/                SQLAlchemy tables, constraints, indexes
app/core/                  errors, logging, timezone-aware dates
app/ui/                    the optional Streamlit front end
```

Two rules hold everywhere:

- **Nothing outside `app/ui` imports Streamlit** — which is why adding the CLI
  needed no changes to any service.
- **Nothing in `app/domain` imports SQLAlchemy** — the streak engine takes a list
  of dates and returns numbers, so its edge cases are three-line unit tests.

Full detail in [docs/architecture.md](docs/architecture.md).

### A note on the streak engine

Answering "what is my current streak" does not read the whole history.
`current_streak` consumes a **lazy, descending** iterator of completion dates and
abandons it at the first gap; the repository backs it with a paged query. A habit
with four years of history and a two-day streak costs one query of 64 rows, and a
test asserts the iterator is not drained.

---

## The web UI (optional extra)

The same data, same services, in a browser:

```bash
python scripts/seed_data.py --days 90 --yes   # 90 days of demo history
streamlit run app/main.py
```

Eleven pages — dashboard, tasks, habits, sleep, activities, time tracking, goals,
journal, analytics, health metrics, settings — with a calendar heatmap, weekly
review and charts. It is not required by the assignment; it exists because the
architecture made it cheap, and it is the clearest demonstration that the
presentation layer really is replaceable.

---

## Development

```bash
ruff check .            # lint
ruff format .           # format
mypy                    # type-check app, scripts and tests
pytest                  # the whole suite
pytest -m "not slow"    # skip the 100k-row performance tests
pytest --cov=app        # with coverage
pre-commit install
```

507 tests, 90% statement coverage of `app`:

- **unit** — the domain layer, no database at all
- **integration** — services and the CLI against a temporary database and a
  frozen clock
- **UI smoke** — every Streamlit page rendered headlessly
- **performance** (`-m slow`) — 100,000 tasks and 100,000 habit logs, asserting
  query counts as well as wall-clock budgets

### Data and backup

```bash
python scripts/backup.py            # SQLite copy + portable JSON export
python main.py categories           # what you can log time and activity against
```

Export and import (CSV, JSON, Excel) are on the Settings page of the web UI, and
in `container.exports` / `container.imports` for scripting.

---

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Layers, dependency rules, decisions and their trade-offs |
| [docs/database.md](docs/database.md) | Schema, constraints, indexes, migrations |
| [docs/development.md](docs/development.md) | Conventions, adding a feature end to end |
| [docs/testing.md](docs/testing.md) | Strategy, fixtures, what is and is not covered |
| [docs/roadmap.md](docs/roadmap.md) | Extension points and what would come next |
| [docs/vibe_coding_brief.md](docs/vibe_coding_brief.md) | The original plan this was built against |

---

## Submission links

- **GitHub Repository:** `<your-public-github-repository-link>`
- **YouTube Explanation:** `<your-youtube-video-link>`

## Licence

MIT — see [LICENSE](LICENSE).
