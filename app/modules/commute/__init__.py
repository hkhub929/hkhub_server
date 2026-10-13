"""Cross-border commute domain package.

Current queue status comes from Immigration Department open data, is sampled by a
standalone collector, and is served from PostgreSQL. No client request reaches an
upstream host directly.
"""
