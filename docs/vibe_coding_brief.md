# Daily Habit Tracker (Vibe Coding Challenge)

A command-line habit tracker — add habits, tick them off each day, and see your current
and longest streaks — built with an AI coding assistant **one prompt at a time**.

> **Status: brief and prompt script.** The code in this folder is written during the
> recorded session, step by step. This README is the plan it is built against, and the
> sections marked **[fill after building]** are completed from the real run rather than
> written in advance.

---

## Project objective

The assignment is not "get a working habit tracker". Copying one prompt into an AI gets
that in thirty seconds. The assignment is:

> Do not ask AI to generate the entire project in one prompt. Use vibe coding
> step-by-step.

So the deliverable is a project that was **argued into existence** — structure agreed
first, one module at a time, run after each one, errors found by running rather than by
reading, and exception handling and logging added deliberately instead of appearing
fully formed.

The measure of success is the video: being able to open any file and say why it is
shaped the way it is.

---

## Why a habit tracker

Of the ten options offered, this one has the most interesting logic that is not
arithmetic. Adding a contact is a dictionary write. Working out that somebody's streak
is 6 days — and that it ended yesterday, not today — needs real date handling:

```
2026-09-03  done      \
2026-09-04  done       |  current streak = 4
2026-09-05  done       |  (today counts, so the run is unbroken)
2026-09-06  done      /
2026-09-07  missed        <- breaks the run
2026-09-08  done      \
2026-09-09  done      /   longest streak = 4, current = 2
```

That is a genuinely explainable ten minutes of video, and it produces natural failure
cases — a date in the future, a habit ticked twice in one day, a corrupt save file —
which is where the exception handling and the custom exception come from.

---

## Requirements checklist

The assignment names seven things the final project must contain:

| # | Requirement | Where it lands |
|---|---|---|
| 1 | at least 4 Python files / modules | `main.py` + 4 modules inside the package |
| 2 | one package | `habits/` with `__init__.py` |
| 3 | `try` / `except` / `finally` | `storage.py` — the save must not corrupt the file |
| 4 | at least one custom exception | `HabitNotFoundError`, `DuplicateHabitError`, `InvalidDateError` |
| 5 | logging to a file | `logs/habits.log` |
| 6 | imports between modules | `tracker.py` imports `storage`, `streaks`, `errors` |
| 7 | a README with 5+ AI prompts | this file — ten of them, below |

---

## Planned structure

Agreed with the assistant in **step 2**, before any code was written:

```
daily_habit_tracker/
├── README.md
├── main.py                 the CLI - menu, argv, printing. NOT part of the package.
├── habits/                 <- the package
│   ├── __init__.py             the public surface
│   ├── errors.py               HabitError and its subclasses
│   ├── models.py               a Habit, and what one looks like on disk
│   ├── storage.py              load and save habits.json, atomically
│   ├── streaks.py              current streak, longest streak, completion rate
│   └── logger_config.py        where log records go
├── data/
│   └── habits.json         the save file
└── logs/
    └── habits.log          every add, tick and failure
```

Same shape as [exercise 25](../../01_python_basics/25_file_organizer/): the package is
the reusable part, `main.py` is the throwaway part that knows about a terminal.

### Planned commands

```bash
python main.py add "Read 20 pages"      # create a habit
python main.py list                     # all habits with their streaks
python main.py done "Read 20 pages"     # tick today off
python main.py done "Read 20 pages" --date 2026-09-07
python main.py stats "Read 20 pages"    # current streak, longest, completion rate
python main.py remove "Read 20 pages"
```

### Planned exceptions

```
Exception
 └── HabitError                  base - one except clause catches all of them
      ├── HabitNotFoundError         "done" on a habit that was never added
      ├── DuplicateHabitError        "add" on a name already taken
      ├── InvalidDateError           a date that is malformed, or in the future
      └── StorageError               habits.json is missing, locked, or corrupt
```

---

## The ten prompts

The assignment asks for at least five. These are the ten, in the order they are used —
one per step of the vibe-coding loop. They are written to be pasted verbatim, so the
recording shows the real conversation.

### Step 1 — Understand the requirement

> **Prompt 1.** I have to build a command-line Daily Habit Tracker in Python as a
> college assignment. The requirements are: at least 4 Python files, one package,
> try/except/finally, at least one custom exception, logging to a file, and imports
> between modules. Before writing any code, ask me the questions you need answered to
> get the design right — especially about how streaks should be counted and where the
> data is stored. Do not write code yet.

*Why this prompt first:* it forces the ambiguity out into the open. "Streak" has at
least three reasonable definitions and picking one is my decision, not the assistant's.

### Step 2 — Suggest the structure

> **Prompt 2.** Based on those answers, propose a package/module structure. I want the
> package to contain only reusable logic and `main.py` to be the CLI outside it. For
> each module give me one sentence on what it is responsible for, and tell me the
> import direction between them so we do not end up with a circular import. Structure
> only — still no code.

### Step 3 — Generate one module

> **Prompt 3.** Write only `habits/streaks.py`. It takes a list of ISO date strings
> (`"2026-09-09"`) that a habit was completed on, and returns current streak, longest
> streak, and completion rate since the first entry. No file I/O, no printing, no
> logging — pure functions, so I can test it on its own. Add an
> `if __name__ == "__main__"` block with three or four cases including an empty list.

*Why streaks first:* it is the only module with logic worth getting wrong, and it has
no dependencies, so it can be run immediately.

### Step 4 — Run it

*(No prompt. `python habits/streaks.py` and read the output.)*

### Step 5 → 6 — Find an error, and get it fixed

> **Prompt 4.** `python habits/streaks.py` gives me this: **[paste the real traceback
> or the wrong number]**. Here is the input that produced it: **[paste it]**. Explain
> what is actually happening before you change anything, then give me the smallest fix
> — not a rewrite of the module.

*Why "explain before you change":* a fix I cannot explain is a fix I cannot defend on
camera, and this is the step the marking scheme is really looking at.

### Step 7 — Exception handling

> **Prompt 5.** Now write `habits/errors.py`: a `HabitError` base class and the
> subclasses `HabitNotFoundError`, `DuplicateHabitError`, `InvalidDateError` and
> `StorageError`. Each one should carry the relevant data as attributes (habit name,
> the bad date) rather than only a message string, so callers can branch on the type
> and still get at the detail. Then update `habits/storage.py` to raise `StorageError`
> when `habits.json` is missing, unreadable, or not valid JSON — and use
> `try/except/finally` so a save that fails part-way cannot leave the file truncated.

### Step 8 — Logging

> **Prompt 6.** Add `habits/logger_config.py` with a `setup_logging()` and a
> `get_logger(name)`, writing to `logs/habits.log`. Use a named logger with child
> loggers per module, not `basicConfig`. Then add log calls to `tracker.py`: INFO for a
> habit added or ticked, WARNING for a habit ticked twice on the same day, ERROR for a
> save that failed. Do not log inside `streaks.py` — it stays pure.

### Step 9 — Refactor

> **Prompt 7.** Review `main.py` and tell me what is wrong with it before changing
> anything. I think the command dispatch is a long if/elif chain and the argument
> parsing is duplicated in three places. Propose the refactor, wait for me to agree,
> then apply it.

> **Prompt 8.** `habits/__init__.py` is empty. Make it the front door for the package:
> re-export the names `main.py` actually needs, add `__all__` and `__version__`, and
> explain in a comment what this file gives me that four loose modules would not.

### Step 10 — Test

> **Prompt 9.** Give me a list of the inputs that should break this program — bad
> dates, duplicate names, a habit that does not exist, an empty `habits.json`, a
> corrupt one, a date in the future, unicode in a habit name. For each one tell me what
> the program *should* do. I will run them myself and tell you which ones are wrong.

> **Prompt 10.** These three cases behaved wrongly: **[paste the real results]**. Fix
> them one at a time, smallest change first, and tell me which exception class each
> case should raise.

---

## What the AI got wrong

**[fill after building]** — the honest list. Every place the assistant produced
something that did not run, or ran and was wrong, and what the actual fix was. This
section is worth more in the video than the code is, because it is the part that proves
the project was driven rather than pasted.

Candidates to watch for, based on exercises 22–24:

- a module named `logging.py`, shadowing the standard library
- `logging.basicConfig()` instead of a configured named logger
- streaks counted from the wrong end of the list, or off by one when today is included
- `except Exception` everywhere, hiding the custom exceptions that were just written
- a save that opens the file for writing before it has something valid to write, so a
  crash mid-save truncates it

---

## Verified run

**[fill after building]** — the real terminal output of `add`, `list`, `done`, `stats`
and at least two failure cases, captured rather than retyped, plus the resulting
`logs/habits.log`.

---

## Learning / outcomes

**[fill after building]** — but the question the video has to answer is this one:

*Which parts of this project could I have written without the assistant, and which
parts did I only understand after arguing with it?*

---

## YouTube demonstration link

<your-youtube-video-link>

---

## Submission links

- **GitHub Repository:** `<your-public-github-repository-link>`
- **YouTube Explanation:** `<your-youtube-video-link>`
