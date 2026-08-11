from __future__ import annotations

import re
from urllib.request import urlopen


LINBPQ_LINKS_URL = "http://127.0.0.1:8088/Node/Links.html"
_LINKS_HEADING = re.compile(r"<h2[^>]*>\s*Links\s*</h2>", re.IGNORECASE)
_ACTIVE_ROW = re.compile(r"<tr[^>]*>\s*<td", re.IGNORECASE)


def parse_rf_session_active(html: str) -> bool:
    """Return whether LinBPQ's Links table contains an active AX.25 link."""
    heading = _LINKS_HEADING.search(html)
    if heading is None:
        raise ValueError("LinBPQ Links heading is missing")
    section = html[heading.end():]
    table_start = section.lower().find("<table")
    if table_start < 0:
        raise ValueError("LinBPQ Links table is missing")
    section = section[table_start:]
    table_end = section.lower().find("</table>")
    if table_end < 0:
        # LinBPQ 6.0.25 omits the closing table tag when the link list is empty.
        table_end = section.lower().find("</body>")
    if table_end < 0 or "Far Call" not in section[:table_end] or "Our Call" not in section[:table_end]:
        raise ValueError("LinBPQ Links table is incomplete")
    return _ACTIVE_ROW.search(section[:table_end]) is not None


def probe_rf_session(url: str = LINBPQ_LINKS_URL, timeout: float = 1.5) -> dict:
    """Probe LinBPQ without credentials; inability to prove idle is unavailable."""
    try:
        with urlopen(url, timeout=timeout) as response:
            html = response.read(262_144).decode("utf-8", errors="replace")
        return {"available": True, "active": parse_rf_session_active(html)}
    except (OSError, TimeoutError, ValueError):
        return {"available": False, "active": None}
