# Notes for Claude

- Documentation for the owner is in Russian: `docs/overview.md` (how the system works) and
  `docs/changelog.md` (work log).
- After every new module or notable change, add an entry at the top of `docs/changelog.md`
  (what was done, where in the code, how to use it, notes and limits) and update
  `docs/overview.md` if sections, models, modules or the workflow changed. Commit the docs
  together with the code.
- Interface strings are English with Turkish translations in `locale/tr/LC_MESSAGES/django.po`;
  compile with `python scripts/compile_translations.py` (no gettext needed).
- Run `python manage.py test directory` before committing.
- Never commit real company data (Excel files, `db.sqlite3`).
