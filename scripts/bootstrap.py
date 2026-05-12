#!/usr/bin/env python3
# Deprecated shim — use: ci-guard init
# For repos with .ci-guard/scripts/ from a pre-v0.5 install, run: ci-guard init --migrate
import sys
print(
    "[ci-guard] bootstrap.py is deprecated as of v0.5.\n"
    "  Use: ci-guard init\n"
    "  To migrate from old per-repo scripts: ci-guard init --migrate",
    file=sys.stderr,
)
from ci_guard.init import main
sys.exit(main())
