from typing import Dict, List

import xbmcgui

from common import (
    COLOR_LIST_MUTED,
    SEARCH_SOURCE_NO_RESULTS_PROP,
    display_provider_headers,
    get_provider_order,
    icons_path,
    short_provider_names,
)

PROVIDER_ID_PREHRAJTO = 'prehrajto'
PROVIDER_ID_SLEDUJTETO = 'sledujteto'
PROVIDER_ID_HELLSPY = 'hellspy'

PROVIDER_LABEL_PREHRAJTO = 'Prehraj.to'
PROVIDER_LABEL_SLEDUJTETO = 'Sledujteto.cz'
PROVIDER_LABEL_HELLSPY = 'HellSpy'

SEARCH_PROVIDER_PROP = 'SearchProvider'
SEARCH_PROVIDER_HEADER_PROP = 'SearchProviderHeader'

_PROVIDER_ICONS = {
    PROVIDER_ID_PREHRAJTO: 'prehrajto.png',
    PROVIDER_ID_SLEDUJTETO: 'sledujteto.jpg',
    PROVIDER_ID_HELLSPY: 'hellspy.png',
}
_PROVIDER_LABELS = {
    PROVIDER_ID_PREHRAJTO: PROVIDER_LABEL_PREHRAJTO,
    PROVIDER_ID_SLEDUJTETO: PROVIDER_LABEL_SLEDUJTETO,
    PROVIDER_ID_HELLSPY: PROVIDER_LABEL_HELLSPY,
}
_PROVIDER_SHORT_LABELS = {
    PROVIDER_ID_PREHRAJTO: 'P',
    PROVIDER_ID_SLEDUJTETO: 'S',
    PROVIDER_ID_HELLSPY: 'H',
}


def provider_list_label(provider_id: str) -> str:
    full = _PROVIDER_LABELS.get(provider_id, provider_id)
    if short_provider_names():
        return _PROVIDER_SHORT_LABELS.get(provider_id, full)
    return full


def tag_search_provider(item: xbmcgui.ListItem, provider_id: str) -> None:
    if item is not None and provider_id:
        item.setProperty(SEARCH_PROVIDER_PROP, provider_id)


def make_source_no_results_item(provider_id: str) -> xbmcgui.ListItem:
    """Non-playable gray row when an enabled source returned no videos."""
    label = f'[COLOR {COLOR_LIST_MUTED}]{provider_list_label(provider_id)}: No results[/COLOR]'
    item = xbmcgui.ListItem(label=label, path='', offscreen=True)
    item.setProperty('IsPlayable', 'false')
    item.setProperty(SEARCH_SOURCE_NO_RESULTS_PROP, 'true')
    return item


def is_source_no_results_item(item: xbmcgui.ListItem) -> bool:
    return item.getProperty(SEARCH_SOURCE_NO_RESULTS_PROP) == 'true'


def make_provider_header_item(provider_id: str) -> xbmcgui.ListItem:
    """Non-playable section title. Kodi has no disabled row; an empty URL does not play."""
    label = provider_list_label(provider_id)
    item = xbmcgui.ListItem(
        label=f'[COLOR {COLOR_LIST_MUTED}]{label}[/COLOR]',
        path='',
        offscreen=True,
    )
    item.setProperty('IsPlayable', 'false')
    item.setProperty(SEARCH_PROVIDER_HEADER_PROP, 'true')
    item.setProperty(SEARCH_PROVIDER_PROP, provider_id)
    icon_name = _PROVIDER_ICONS.get(provider_id)
    if icon_name:
        item.setArt({'icon': icons_path + icon_name})
    return item


def is_provider_header_item(item: xbmcgui.ListItem) -> bool:
    return item.getProperty(SEARCH_PROVIDER_HEADER_PROP) == 'true'


def group_search_results(items: List[xbmcgui.ListItem]) -> List[xbmcgui.ListItem]:
    """Order provider blocks and optionally insert a header before blocks that have videos."""
    order = get_provider_order()
    buckets: Dict[str, List[xbmcgui.ListItem]] = {provider_id: [] for provider_id in order}
    loose: List[xbmcgui.ListItem] = []
    for item in items or []:
        if not item:
            continue
        provider_id = (item.getProperty(SEARCH_PROVIDER_PROP) or '').strip()
        if provider_id in buckets and not is_provider_header_item(item):
            buckets[provider_id].append(item)
        elif not is_provider_header_item(item):
            loose.append(item)

    show_headers = display_provider_headers()
    ordered: List[xbmcgui.ListItem] = []
    for provider_id in order:
        group = buckets[provider_id]
        if not group:
            continue
        has_videos = any(not is_source_no_results_item(item) for item in group)
        if show_headers and has_videos:
            ordered.append(make_provider_header_item(provider_id))
        for item in group:
            if is_source_no_results_item(item):
                item.setLabel(
                    f'[COLOR {COLOR_LIST_MUTED}]{provider_list_label(provider_id)}: No results[/COLOR]'
                )
        ordered.extend(group)
    ordered.extend(loose)
    return ordered
