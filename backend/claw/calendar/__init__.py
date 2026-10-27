"""Calendars: reading them, writing them, and finding time in them.

Local `.ics` files are the only source today. `store.CalendarSource` is the
interface another source would satisfy — a CalDAV server (Radicale, Nextcloud,
Fastmail, iCloud) is the intended next one, which is why the format on disk is
the one those servers already speak.
"""
