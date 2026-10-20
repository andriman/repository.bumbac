# -*- coding: utf-8 -*-
"""Context menu: search current ListItem via Přehraj.to Hledat."""

import sys

import xbmcaddon

from utils.external_integration import run_context_search


if __name__ == '__main__':
    # Re-check setting in case visibility condition is unsupported on older Kodi.
    if xbmcaddon.Addon().getSetting('context_menu_search') == 'false':
        sys.exit(0)
    listitem = getattr(sys, 'listitem', None)
    run_context_search(listitem)
