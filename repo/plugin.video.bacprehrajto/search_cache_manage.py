# -*- coding: utf-8 -*-
"""Clear search result disk cache (invoked from add-on settings)."""

import sys

from cache_manage import _run_clear_search

if __name__ == '__main__':
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'clear').strip().lower()
    if mode == 'clear':
        _run_clear_search()
