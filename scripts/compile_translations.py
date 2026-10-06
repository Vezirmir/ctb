"""Compile locale/*/LC_MESSAGES/django.po into .mo files.

Equivalent to `manage.py compilemessages`, but needs only the `polib` package
instead of GNU gettext (handy on Windows and minimal servers).
"""

from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parent.parent

for po_path in sorted((ROOT / "locale").glob("*/LC_MESSAGES/*.po")):
    polib.pofile(str(po_path)).save_as_mofile(str(po_path.with_suffix(".mo")))
    print(f"compiled {po_path.relative_to(ROOT)}")
