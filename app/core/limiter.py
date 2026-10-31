"""Login rate limiting (FR-01). One limiter instance, shared by every throttled
route. In-memory storage is per process: with --reload each worker has its own
counters, which is acceptable for the local deployment; a shared storage backend
can be configured later for the cloud environment."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
