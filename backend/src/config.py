import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pulp:pulp_dev_password@db:5432/pulp_quota")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
SEED_DEMO = os.getenv("SEED_DEMO", "true").lower() == "true"
