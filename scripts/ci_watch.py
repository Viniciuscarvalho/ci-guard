#!/usr/bin/env python3
# Deprecated shim — logic moved to ci_guard.watch. Use: ci-guard watch
import sys
from ci_guard.watch import main
sys.exit(main())
