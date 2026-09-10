# Roadmap

The point of the architecture is that none of the following needs a rewrite.
Each entry names the seam it plugs into.

## Ready to build

**Reminders.** `NotificationService` is a `Protocol`, `Notification` is a value
object, and `NullNotificationService` is the default. An email or Telegram
channel is one class plus its configuration, passed to `build_container()`.
Nothing in the seam imports Streamlit, so a scheduler could deliver reminders
with no UI process running at all. What is missing is the *scheduler* and the
rules that decide when a reminder is due.

**A REST API.** The services take plain values and return pydantic models, and
none of them knows a browser exists. A FastAPI app would call
`build_container()` and expose the same methods. The read models are already
the response bodies.

**PostgreSQL.** Change `HABIT_DATABASE_URL`. The schema uses no SQLite-specific
types, the enums are non-native with `CHECK` constraints, and the migrations
apply unchanged. `pool_pre_ping` is already configured for a networked
database.

**Multiple users.** Every user-owned table carries an indexed `user_id` and
every scoped repository filters on it. What is needed is authentication and a
way to choose the profile — not a schema change.

## Needs design first

**An AI coach.** `PersonalCoach` is a `Protocol` with three methods, and
`RuleBasedCoach` implements it deterministically today. An LLM-backed version
would satisfy the same interface and be *selected* in the container, never
required. Two things to settle before writing it:

* **Privacy.** Section 42 of the brief says nothing leaves the machine by
  default. An LLM coach must be opt-in, must say what it sends, and the
  deterministic coach must remain the default.
* **Provenance.** Every sentence the rule-based coach produces traces to a
  number in the database. A generated one should carry the same evidence, or
  be visibly marked as generated.

**Wearables and calendars.** Apple Health, Google Fit, Google Calendar. The
import path already validates every row through the same schemas the forms
use, so a sync becomes a source that produces `SleepInput`, `ActivityInput` and
`TimeEntryInput` objects. The open questions are conflict resolution — whose
sleep record wins — and how to mark a record as externally sourced so a resync
does not duplicate it.

**Cloud synchronisation.** Would need conflict resolution, and would break the
"everything stays on this machine" promise, so it needs to be an explicit,
reversible choice rather than a default.

## Smaller improvements

| Improvement | Where |
|---|---|
| Recompute scores in the background rather than on first view | `ProductivityService.ensure_scored` |
| Cursor pagination for very long histories | `BaseRepository.paginate` |
| A materialised daily rollup for multi-year analytics | `AnalyticsRepository` |
| Custom insight rules written by the user | `INSIGHT_RULES` is already a tuple of functions |
| Per-habit reminder times | The column exists; nothing reads it yet |
| Undo for destructive actions | Would need a soft-delete column |
| Keyboard shortcuts for Quick Add | Streamlit component |

## Deliberately not planned

**Gamification beyond streaks.** Points and badges change what people optimise
for. Streaks already risk this; the rest-day and minimum-target features exist
specifically to reduce the harm.

**Social features.** The data is private. Sharing it is a different product.

**Medical interpretation.** BMR, TDEE and BMI are estimates from population
equations, labelled as such everywhere they appear. Turning them into advice
would need clinical input this project does not have.

**A mobile app.** A responsive web view reached from a phone covers the actual
need — logging quickly — without a second codebase. If a native app were built,
it would talk to the FastAPI backend above, not reimplement the domain.
