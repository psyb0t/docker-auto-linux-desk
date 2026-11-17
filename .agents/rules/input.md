# Humanized input

- `human_mouse.py`, `human_keyboard.py`, `human_scroll.py` and `system.py` are shared with stealthy-auto-browse. Keep them free of browser and server imports, and port timing fixes to both repositories.
- Input actions in `input_actions.py` take a `Surface`, never a browser page. Anything a page provides goes through a `Surface` method.
- Every humanized default stays overridable per request, with validation, an MCP parameter and documentation.
- Changes to timing need `tests/test_human_input.py` and the integration test that measures input through the event logger.
