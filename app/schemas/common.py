"""Shared schema building blocks.

Pydantic models are the contract between the UI and the services. The UI may
hand a service a validated object; it may never hand it an ORM instance, and
it never receives a live ORM instance back - only these, which are detached
and safe to hold across a Streamlit rerun.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Refuse to build a page larger than this, whatever the caller asks for.
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 50


class Schema(BaseModel):
    """Base for input models: strict about unknown fields, strips whitespace."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ReadSchema(BaseModel):
    """Base for output models built from ORM rows."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


class DateRange(Schema):
    """An inclusive range of local dates.

    Inclusive because that is how a person reads "1st to 7th". The UTC
    half-open interval a query actually needs is produced by
    :func:`app.core.timeutils.range_bounds_utc`.
    """

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> DateRange:
        """Reject a range that ends before it starts."""
        if self.end < self.start:
            msg = f"End date {self.end} is before start date {self.start}."
            raise ValueError(msg)
        return self

    @property
    def days(self) -> int:
        """Number of days in the range, inclusive."""
        return (self.end - self.start).days + 1

    @classmethod
    def last_n_days(cls, end: date, days: int) -> DateRange:
        """Build a range of ``days`` ending on (and including) ``end``."""
        return cls(start=end - timedelta(days=max(1, days) - 1), end=end)

    def previous(self) -> DateRange:
        """The equally long range immediately before this one.

        Used for every period-on-period comparison, so that "this week
        against last week" is always comparing equal spans.
        """
        length = self.days
        new_end = self.start - timedelta(days=1)
        return DateRange(start=new_end - timedelta(days=length - 1), end=new_end)


class Pagination(Schema):
    """Bounded window over a result set.

    Every history query takes one of these. An unbounded ``SELECT`` over a
    table that will hold a hundred thousand habit logs is the difference
    between a page that loads and a page that does not.
    """

    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)

    def next_page(self) -> Pagination:
        """The window immediately after this one."""
        return Pagination(limit=self.limit, offset=self.offset + self.limit)


class Page[T](BaseModel):
    """One page of results plus the total, for a page-count display."""

    model_config = ConfigDict(frozen=True)

    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        """Whether further pages exist."""
        return self.offset + len(self.items) < self.total

    @property
    def page_number(self) -> int:
        """One-based index of this page."""
        return self.offset // self.limit + 1 if self.limit else 1

    @property
    def page_count(self) -> int:
        """Total number of pages."""
        if not self.limit:
            return 1
        return max(1, -(-self.total // self.limit))
