import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test-sps-dashboard.db")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough")  # gitleaks:allow
os.environ.setdefault("BOOTSTRAP_PASSWORD", "test-bootstrap-password")
