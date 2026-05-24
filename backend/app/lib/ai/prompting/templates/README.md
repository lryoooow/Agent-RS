# Modular Prompt Templates

Each prompt concern lives in its own Jinja file. The renderer selects only the
modules needed for the current request and records selected module IDs in the
context assembly audit data.

