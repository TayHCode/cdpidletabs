# Contributing

Run `python3 -m unittest discover -s tests -q`. Tests mock CDP and use temporary
state files; they must never contact a real browser. Keep the runtime dependency
list empty. Test dry-run and last-page safety when changing tab selection.
Do not commit browser addresses, state, credentials or local deployment details.
