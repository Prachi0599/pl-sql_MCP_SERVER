"""Web UI package for the TCL Finance & Billing assistant.

A lightweight Starlette app (src/web/app.py) serves a single-page chat UI and a
JSON API. All conversation logic lives in src/web/session.py (ChatSession), which
reuses the same agent stack as the terminal client but returns structured data
(so the browser can render approval buttons, recommended-action chips, etc.).
"""
