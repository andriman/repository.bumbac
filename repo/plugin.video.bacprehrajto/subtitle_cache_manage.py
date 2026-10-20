# -*- coding: utf-8 -*-
"""Refresh or clear the playback subtitle cache (invoked from add-on settings)."""

import sys

from cache_manage import _run_clear_subtitles, _run_refresh

if __name__ == '__main__':
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'refresh').strip().lower()
    if mode == 'clear':
        _run_clear_subtitles()
    else:
        _run_refresh()
