# RETIRED 2026-08-11 — EI PDF handbook upload

This module used to browser-automate PDF handbook uploads to
`https://ei.ennead.com/page/964/enneadtab-ecosystem`.

That channel is closed. Handbook distribution is wiki ingest
(`DarkSide/publish/________publish.py` `_generate_wiki_website`). Do not
restore the EI uploader, do not copy `credential.json` onto a publisher
box, and do not wire this folder back into publish.

`main.py` is a stub that raises on import so an accidental call cannot
quietly skip or hang a publish.
