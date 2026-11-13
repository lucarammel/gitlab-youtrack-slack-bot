"""Collectors turn API data into Notifications. Add a source by writing a module with
`collect(ctx) -> list[Notification]` and registering it in COLLECTORS."""

from . import my_mrs, new_mrs, todos, youtrack
from .base import Collector, Context

COLLECTORS: tuple[Collector, ...] = (
    Collector("todos", lambda c: c.cfg.notify_todos, todos.collect),
    Collector("new_mrs", lambda c: c.cfg.notify_new_mrs, new_mrs.collect),
    Collector("my_mr_activity", lambda c: c.cfg.notify_my_mr_activity, my_mrs.collect),
    Collector("youtrack", lambda c: c.yt is not None and c.cfg.notify_youtrack, youtrack.collect),
)

__all__ = ["COLLECTORS", "Collector", "Context"]
