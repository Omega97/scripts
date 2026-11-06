#!/usr/bin/env python3
"""TagStore: Lightweight, Hash-Based Image Tagging & Organization CLI.

Thin entrypoint. The data model lives in ``tagstore.model`` and the
presentation layer lives in ``tagstore.cli``.
"""

import sys

from tagstore.cli import main

if __name__ == "__main__":
    sys.exit(main())
