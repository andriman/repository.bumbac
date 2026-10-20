# -*- coding: utf-8 -*-
"""Reorder search providers from the Zdroje settings actions."""

import sys

import xbmcgui

from common import PROVIDER_ORDER_LABELS, _ADDON_NAME, move_provider


def _notify(message: str) -> None:
    xbmcgui.Dialog().notification(
        _ADDON_NAME,
        message,
        xbmcgui.NOTIFICATION_INFO,
        4000,
        sound=False,
    )


if __name__ == '__main__':
    direction_name = (sys.argv[1] if len(sys.argv) > 1 else '').strip().lower()
    provider_id = (sys.argv[2] if len(sys.argv) > 2 else '').strip().lower()
    if direction_name == 'up':
        direction = -1
    elif direction_name == 'down':
        direction = 1
    else:
        direction = 0
    if direction == 0 or provider_id not in PROVIDER_ORDER_LABELS:
        _notify('Neznámý zdroj')
    else:
        _order, _moved, message = move_provider(provider_id, direction)
        _notify(message)
