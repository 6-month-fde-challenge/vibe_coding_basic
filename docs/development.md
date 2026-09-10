# Development

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install -e ".[dev]"
pre-commit install
cp .env.example .env            # optional; the defaults work

python main.py --help           # the CLI
python scripts/seed_data.py --days 90 --yes
streamlit run app/main.py       # the optional web UI
```

## The loop

```bash
ruff check . && ruff format .   # lint and format
mypy                            # type-check app, scripts and tests
pytest -m "not slow"            # the fast suite, a few seconds
pytest                          # everything, including the 100k-row tests
pytest --cov=app --cov-report=term-missing
```

CI runs exactly these, in this order, and fails the build on any of them.

## Adding a feature

Work down the stack, not across it. Each step is testable before the next
exists.

```
domain rule  →  schema  →  model  →  repository  →  service  →  CLI command / page  →  tests
```

Both front ends stop at the service layer. A feature that needs a new business
rule does not touch either of them until the last step.

Worked example — adding a "mood streak":

1. **Domain.** A pure function in `app/domain/analytics/`, taking a list of
   `(date, rating)` pairs. Unit-test it with a hand-written list; no database.
2. **Schema.** A read model in `app/schemas/analytics.py` for what the UI
   receives.
3. **Model.** Nothing needed — journal entries already store mood. If a column
   were required: add it, `alembic revision --autogenerate`, then
   `ruff format` the generated file.
4. **Repository.** A narrow query returning only the columns the rule needs.
   Bounded by a date range; aggregated in SQL if it can be.
5. **Service.** Gathers the inputs inside one unit of work, calls the domain
   function, converts to the read model.
6. **Component.** If it draws, add it to `app/ui/components/charts.py` so it
   inherits the palette and the mark rules.
7. **Page.** Call the service, hand the result to the component. No logic.
8. **Tests.** Unit for the rule, integration for the service, and the UI smoke
   test already covers the page rendering.

## Conventions

**Type hints everywhere.** `mypy` runs with `disallow_untyped_defs`. A
`type: ignore` needs a comment saying why.

**Docstrings on every public function, class and module**, checked by ruff's
pydocstyle rules in Google convention. Say *why*, not what the signature
already says.

**No magic numbers.** A threshold gets a module-level constant with a comment
explaining the choice — `NOTABLE_PERCENT`, `STREAK_WORTH_MENTIONING`,
`MIN_SLEEP_MINUTES`, `OVERDUE_WINDOW_DAYS`.

**Errors carry two messages.** `message` and `details` for the log,
`user_hint` for the screen. Never let a traceback reach a user.

**Never log user text.** Journal entries, reflections and notes are the most
private thing in the database. Log ids, dates and counts. `safe_preview` exists
for the rare diagnostic case and is bounded.

**Log with `%s`, not f-strings.** `logger.info("Task %s created", task.id)`
defers formatting until the record is actually emitted.

## Things that will trip you up

**Alembic disables your loggers.** `logging.config.fileConfig()` defaults to
`disable_existing_loggers=True`, and startup runs migrations. `env.py` passes
`False` explicitly; if you ever see the log file stop after one line, that is
where to look.

**Global CLI flags need a parent parser.** `--plain` and `--quiet` are declared
on the main parser *and* on every subcommand via `_global_flags()`, with
`SUPPRESS` so the subparser default cannot overwrite a value given before the
subcommand. Without both, only one of `habits --plain list` and
`habits list --plain` works.

**Argparse type converters run before your try block.** A converter that raises
anything but `ValueError` or `ArgumentTypeError` prints a traceback. `parse_day`
raises `CommandError`; `day_argument` translates it.

**Streamlit reruns the whole script on every interaction.** So:

* The container is `@st.cache_resource` — it owns a connection pool, and one
  copy per rerun would exhaust it.
* Query results, if cached, are `@st.cache_data` and only ever hold immutable
  schema objects. Never an ORM row; never a session.
* Two widgets with the same auto-generated id crash the page. Anything rendered
  more than once needs an explicit `key`. The date navigator is called **once
  per page**, above the tabs, for exactly this reason.

**`list(SomeStrEnum)` is `list[str]` to the type checker.** A `StrEnum` member
*is* a string, so the member type is lost. Use `members(SomeEnum)` from
`app.models.enums`, and `enum_select` from `app.ui.components.forms` for a
select box that hands the enum back.

**A read-only unit of work is closed, not rolled back.** `rollback()` expires
every loaded instance; `close()` leaves their values readable. If you add a
code path that reads ORM rows and uses them after the `with` block, this is why
it works.

**Alembic's post-write hook is off.** Run `ruff format
app/database/migrations/versions` yourself after autogenerating.

## Charts

Every figure goes through `app/ui/components/charts.py`, which enforces:

* **One y-axis.** Never two scales on one plot — two measures become two
  charts, or are indexed to a common base.
* **Colour follows the entity, not the rank.** `series_colors` maps names to
  slots by sorted name, so filtering a series out never repaints the survivors.
* **Categorical hues in fixed order, never cycled.** A ninth series folds into
  "Other" rather than generating a hue.
* **One hue for magnitude.** The heatmap is a single blue ramp, light to dark.
* **Thin marks, hairline grid, selective direct labels.** Never a number on
  every point.
* **A table beside the chart** wherever colour is doing work, so identity never
  rests on colour alone.

The palette lives in `app/ui/theme.py` and is validated for colour-vision
deficiency separation; `.streamlit/config.toml` holds the matching page
surfaces so the two cannot drift.

## Project layout

```
main.py              CLI shim, so `python main.py` works from a clone
app/
  cli/               the command-line interface
    parser.py          the grammar (argparse)
    commands.py        one handler per verb
    formatters.py      terminal rendering, ASCII fallback
    __main__.py        try/except/finally and the exit code
  main.py            Streamlit navigation only
  bootstrap.py       the object graph, in one place
  config/            settings
  core/              errors, logging, time
  database/          engine, base, types, migrations
  models/            ORM tables and enums
  schemas/           pydantic DTOs
  domain/            pure logic by subject
  repositories/      the only SQL
  services/          business rules and transactions
  notifications/     the reminder seam
  export/            CSV / JSON / Excel
  ui/                pages, components, theme, state
docs/                this documentation
scripts/             seed_data.py, backup.py
tests/               unit, integration, fixtures
```
