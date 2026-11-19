# Docs and releases

- `docs/` is the documentation site and owns the detail; the README stays a summary with full-URL links into the site.
- Behavior, configuration and API changes update the affected docs page and `CHANGELOG.md` in the same change.
- Key bindings live in `docker/keymap.json`, the complete map; `docker/configure-openbox.py` writes it into rc.xml and prints the `docs/keyboard.md` table (`--markdown`), which a unit test keeps in sync. No binding uses the Super key.
- CHANGELOG entries use `## [X.Y.Z] YYYY-MM-DD` with Added, Changed and Fixed sections. Versions are set in `pyproject.toml` and `src/autolinuxdesk/__init__.__version__`.
