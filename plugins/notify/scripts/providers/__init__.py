"""claude-workbench notify providers.

Each provider module exposes a single ``send(config, title, message, priority,
event_type, url=None) -> bool`` function. ``config`` is the already-env-expanded
provider stanza from notify-config.json. Return True on success, False on
recoverable failure; raise on programmer errors.
"""
