from dataclasses import dataclass, field
from typing import List, Optional

from requests.cookies import RequestsCookieJar

from common import (
    is_prehrajto_premium_subs_if_none_enabled,
    is_prehrajto_premium_subtitles_enabled,
)
from model.StreamData import StreamData
from model.SubData import SubData
from providers.prehrajto.download import _has_cookies, ensure_premium_stream, resolve_premium_download_url
from providers.prehrajto.get_stream_data import (
    merge_subtitle_lists,
    parse_all_subtitles_from_html,
    parse_streams_from_html,
    parse_subtitles_from_html,
)
from providers.prehrajto.premium_subtitles import fetch_subtitles_from_premium_link
from utils.utils import dprint


@dataclass
class PrehrajtoStreamContext:
    page_url: str
    content: bytes
    cookies: Optional[RequestsCookieJar]
    streams: List[StreamData]
    subs: List[SubData]
    premium_subs_attempted: bool = field(default=False)


def build_prehrajto_stream_context(
        page_url: str,
        content: bytes,
        cookies: Optional[RequestsCookieJar],
) -> PrehrajtoStreamContext:
    streams = parse_streams_from_html(content)
    if cookies and 'prehraj' in page_url:
        subs = parse_all_subtitles_from_html(content) or parse_subtitles_from_html(content)
    else:
        subs = parse_subtitles_from_html(content)
    if cookies and 'prehraj' in page_url:
        streams = ensure_premium_stream(streams, page_url, cookies)
    return PrehrajtoStreamContext(
        page_url=page_url,
        content=content,
        cookies=cookies,
        streams=streams,
        subs=subs,
    )


def _has_premium_stream(streams: List[StreamData]) -> bool:
    return any(s.is_premium for s in streams)


def _page_subtitles(ctx: PrehrajtoStreamContext) -> List[SubData]:
    return parse_all_subtitles_from_html(ctx.content) or ctx.subs


def resolve_subtitles_for_selection(
        ctx: PrehrajtoStreamContext,
        selected: StreamData,
) -> List[SubData]:
    page_subs = _page_subtitles(ctx)

    if not is_prehrajto_premium_subtitles_enabled():
        return page_subs

    if selected.is_premium:
        return page_subs

    if not _has_cookies(ctx.cookies):
        dprint('resolve_subtitles_for_selection(): no session cookies')
        return page_subs

    if not _has_premium_stream(ctx.streams):
        dprint('resolve_subtitles_for_selection(): no premium stream in list')
        return page_subs

    if is_prehrajto_premium_subs_if_none_enabled() and len(page_subs) > 0:
        return page_subs

    if ctx.premium_subs_attempted:
        return page_subs

    ctx.premium_subs_attempted = True
    extra = fetch_subtitles_from_premium_link(
        ctx.page_url, ctx.cookies, page_content=ctx.content)
    merged = merge_subtitle_lists(page_subs, extra)
    dprint(
        f'resolve_subtitles_for_selection(): page={len(page_subs)} '
        f'extra={len(extra)} merged={len(merged)}'
    )
    return merged if merged else page_subs


def resolve_stream_path_for_playback(
        ctx: PrehrajtoStreamContext,
        selected: StreamData,
) -> StreamData:
    if not selected.is_premium or not _has_cookies(ctx.cookies) or 'prehraj' not in ctx.page_url:
        return selected
    resolved = resolve_premium_download_url(
        ctx.page_url,
        cookies=ctx.cookies,
        extra_headers=selected.headers,
    )
    if resolved:
        selected.path = resolved
    return selected
