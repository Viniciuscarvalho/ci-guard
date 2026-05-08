import sys
from pathlib import Path

# Make 'import classify_failure', 'import flaky_ledger', etc. work without a
# package install. Runs before any test module imports from scripts/.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
