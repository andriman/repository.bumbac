# -*- coding: utf-8 -*-
"""Install / manage the bundled TMDB Helper player (from settings)."""

import sys

from utils.external_integration import install_tmdb_helper_player


if __name__ == '__main__':
    action = (sys.argv[1] if len(sys.argv) > 1 else 'install').strip().lower()
    if action in ('install', 'install_player', ''):
        install_tmdb_helper_player()
