"""Plugin whose register() fails, for the loader tests."""


def register(registry: object) -> None:
    raise RuntimeError("deliberate failure")
