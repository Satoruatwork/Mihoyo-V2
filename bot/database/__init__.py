"""Persistence layer — Redis (Upstash) is the primary datastore.

``redis_client`` owns the async connection; ``store`` implements all persistent
user/group/stats operations on top of it.
"""
