# Testing

```bash
pytest                          # everything
pytest -m "not slow"            # skip the 100k-row performance tests
pytest -m slow                  # only those
pytest tests/unit -q            # the domain layer, no database
pytest --cov=app --cov-report=term-missing
```

507 tests, 90% statement coverage of `app` (the UI layer and `main.py` are
excluded from the coverage figure and covered by a smoke suite instead).

## The layers of the suite

| Layer | What it proves | Speed |
|---|---|---|
| `tests/unit` | Every business rule, including its edge cases | milliseconds — no database at all |
| `tests/integration` | Services against a real schema, a temporary file and a frozen clock | seconds |
| `tests/integration/test_cli.py` | Every command, its output, and the exit codes | seconds |
| `tests/integration/test_ui_smoke.py` | Every page renders and produces widgets | seconds |
| `tests/integration/test_performance.py` | Query counts and wall-clock budgets at 100k rows | a minute or two, marked `slow` |

The split follows the architecture: because the domain layer is pure, most of
the interesting logic is tested with three lines of setup and no fixture.

## Fixtures

`tests/conftest.py`:

| Fixture | Gives you |
|---|---|
| `clock` | A `FixedClock` pinned to 2026-09-10 12:00 UTC |
| `today` | The frozen local date, so no test depends on when it runs |
| `settings` | Configuration pointing at a `tmp_path` database and log directory |
| `database` | A fresh schema built from the models |
| `container` | The whole wired object graph against that database |
| `populated` | One deliberately imperfect week of data — fixed, not random |
| `time_categories`, `activity_categories` | `{name: id}` for the seeded categories |

`populated` is fixed rather than generated: a test that asserts a score of 84
cannot fail usefully if its input moves between runs.

`tests/helpers.py` provides `not_none`, which asserts presence and narrows the
type — better than scattering `assert x is not None` before every attribute
access.

## What is covered

The brief names specific cases. Each one has a test.

### BMR

Male and female against the published constants; the 166 kcal gap between them;
Harris-Benedict close to but distinct from Mifflin; Katch-McArdle rising as
body fat falls; `UNSPECIFIED` sex refused *with the reason*; every input
boundary accepted at the edge and refused outside it; a missing height named in
the error; age arithmetic before, on and after a birthday, including a leap-day
birthday in a common year.

### Sleep

The brief's worked example (23:30 → 06:30 = 7h); a night entirely after
midnight; exactly midnight to eight; bedtime before midnight with sleep after
it; the same clock times in two timezones giving the same length but different
instants; a twenty-minute "night" and a twenty-hour one both refused; circular
clock statistics, where 23:50 and 00:10 are twenty minutes apart; sleep debt
positive and negative; a 7-day average that uses only the last seven.

### Habits

The README's worked streak (current 2, longest 4); today unlogged not breaking
the run, with and without the grace rule; a gap yesterday ending it; a weekday
habit surviving the weekend; a rest day not counting as a miss; a completion on
a day the habit was not due neither helping nor breaking; a future-dated log
ignored; a flexible "three times a week" habit counting weeks; the streak
stopping at the habit's start date; **and a test that the lazy iterator is
abandoned after three rows rather than drained**.

### Tasks

Every legal and illegal status transition; cancelled tasks leaving the
denominator; priority weighting; estimate accuracy from only the tasks that
recorded both figures; daily, weekly, fortnightly and monthly recurrence;
31 January + 1 month clamping to 28 February and to 29 February in a leap year;
an anchor years in the past landing on the right phase.

### Analytics

Empty, single-day and multi-day datasets; missing values; week and month
grouping; the heatmap grid's coordinates; rolling totals; every statistical
helper returning `None` rather than raising on empty input; each insight rule
firing and staying quiet.

### Productivity

Weight validation, including a set that does not sum to one and an all-zero
rescale; a perfect day scoring 100; an empty day scoring 0 without raising; the
breakdown summing to the total; missing components rescaled rather than scored
as zero; a *tracked* zero scoring worse than an untracked component;
overshooting a target capped.

### Integrity and data

The unique constraint refusing a second habit log for a day; the `CHECK`
constraint refusing an impossible sleep duration; foreign keys actually
enforced; a cascade deleting logs with a habit; a rejected create leaving
nothing behind; a full export/import round trip; a malformed file reported by
row number; an oversized upload refused; a backup from a newer format version
refused.

## Performance

`test_performance.py` builds 100,000 tasks, 100,000 habit logs and 50,000 time
entries once per module, then asserts both a time budget and — more usefully —
a **query count**, via a `QueryCounter` listening on the engine.

Wall-clock alone would not catch a regression: a full-table scan over 100,000
rows on an SSD still finishes in well under a second. The query count does.

| Assertion | Budget |
|---|---|
| Current streak, one habit | ≤ 6 queries |
| Time allocation, 90 days | ≤ 3 queries |
| Count overdue tasks | ≤ 2 queries |
| Full dashboard | < 120 queries |
| 365-day heatmap | < 60 queries |

These caught two real defects during development: `get_or_create` per day when
scoring a range (1,110 queries for a year of heatmap), and a per-habit query
inside the dashboard's habit loop.

## The CLI

`test_cli.py` drives `dispatch` against a real temporary database and captures
stdout, so it asserts what a user actually sees: the exit code, the message, and
the state left behind. Covered: every verb; prefix matching and the ambiguous
case; each habit type's own input; backdating and the `--since` guard; the date
words; the ASCII fallback being pure ASCII; and a global flag working on either
side of the subcommand.

`main()` is tested separately for the two things only it owns — the exception
funnel (`CommandError` → 1, a crash → 70 *without* the message leaking, Ctrl-C →
130) and the `finally`, with one test per path asserting the connection pool was
disposed.

## UI smoke tests

Streamlit's `AppTest` runs each page headlessly and asserts nothing was raised.
The pages are thin, but thin is not correct — a renamed field or a duplicated
widget key breaks a page in a way no service test would catch. That is exactly
how the journal page's three duplicate date navigators were found.

One test also confirms the error boundary swallows an exception, shows a
message, and does **not** leak the original text.

## What is not covered

* **Visual regression.** Pages are asserted to render, not to look right. The
  charts were checked by screenshotting the running app.
* **Concurrency.** Single-user and local; two writers at once is out of scope,
  though WAL and a busy timeout are configured for it.
* **DST arithmetic beyond `day_bounds_utc`.** One test pins a 25-hour London
  day. Sleep stored as instants is immune by construction.
* **Streamlit's own behaviour.** Widget semantics are assumed correct.
