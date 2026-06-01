from typing import Callable, List, Optional, Tuple

import xbmcgui

from common import apply_action_icon

ActionEntry = Tuple[str, str, Callable[[], None]]


def open_icon_action_menu(heading: str, actions: List[ActionEntry]) -> None:
    if not actions:
        return

    list_items = []
    for label, icon_file, _handler in actions:
        item = xbmcgui.ListItem(label=label)
        apply_action_icon(item, icon_file)
        list_items.append(item)

    selected = xbmcgui.Dialog().select(heading, list_items, useDetails=True)
    if selected == -1:
        return
    actions[selected][2]()
