"""Persistence layer — pluggable backends (Redis, MongoDB, Postgres/Supabase, memory).

``interfaces`` defines the contracts; ``store``/``mongo_store``/``postgres_store``
implement them; ``factory.build_database`` selects the configured backend; ``local_store``
is the file-backed fallback used by every backend via a circuit breaker.
"""
