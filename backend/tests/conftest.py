import os

# Keep the suite fully offline: disable online enrichment before app.config is
# imported (settings is a module-level singleton). Enrichment logic is covered
# directly in test_enrich.py with the HTTP seam monkeypatched.
os.environ.setdefault("EMENDATOR_ENRICH_ONLINE", "0")
