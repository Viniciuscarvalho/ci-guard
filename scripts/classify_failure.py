#!/usr/bin/env python3
# Deprecated shim — logic moved to ci_guard.classify. Use: ci-guard classify
import sys
from ci_guard.classify import main
sys.exit(main())
