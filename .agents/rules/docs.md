# Docs and releases

- `docs/` is the documentation site and owns the detail; the README stays a summary with full-URL links into the site.
- Behavior, configuration and API changes update the affected docs page and `CHANGELOG.md` in the same change.
- Key bindings live in `docker/configure-openbox.py`; `docs/keyboard.md` lists them and must match `desktop_keybindings` output.
- CHANGELOG entries use `## [X.Y.Z] YYYY-MM-DD` with Added, Changed and Fixed sections. Versions are set in `pyproject.toml` and `src/autolinuxdesk/__init__.__version__`.
