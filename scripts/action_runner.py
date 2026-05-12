#!/usr/bin/env python3
# Deprecated shim — logic moved to ci_guard.actions. Use: ci-guard run-actions
import sys
from ci_guard.actions import main
sys.exit(main())
