"""Pure business logic, organised by subject area.

Every function in this package is a plain Python function over plain Python
values. Nothing here imports SQLAlchemy, Streamlit, or anything from
``app.repositories`` / ``app.services`` / ``app.ui``.

That constraint is not decoration. It is what makes the rules testable
without a database, reusable from a future FastAPI process, and fast enough
to run 365 times when the calendar heatmap asks for a year of scores.
"""
