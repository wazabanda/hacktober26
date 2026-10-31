import os
import tempfile

# isolated DB + mock payments before app.db is imported
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["DEVDRAFT_MODE"] = "mock"
os.environ["CHARGE_SCALE"] = "1"
os.environ["FX_ZMW_PER_USD"] = "26.5"
os.environ.setdefault("DEVDRAFT_WEBHOOK_SECRET", "whsec_test")
