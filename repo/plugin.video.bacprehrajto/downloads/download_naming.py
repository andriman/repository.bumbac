import os
import re
from typing import Optional, Tuple
from urllib.parse import unquote, urlparse

from utils.StrUtils import find_pattern, find_pattern_groups

_LISTING_SIZE_RE = re.compile(
    r'\s\|\s\d+(?:[.,]\d+)?\s*(?:B|KB|MB|GB|TB)\s*$',
    re.IGNORECASE,
)
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _hellspy_stream_name(page_url: str, content: Optional[str]) -> Optional[str]:
    """Video title from the page. This is the search result name without the appended size."""
    if 'hellspy' not in (page_url or '').lower() or not content:
        return None
    from providers.hellspy.payload import extract_initial_data, video_record
    record = video_record(extract_initial_data(content))
    if not record:
        return None
    title = record.get('title')
    if not isinstance(title, str):
        return None
    title = _LISTING_SIZE_RE.sub('', title).strip()
    title = _UNSAFE_FILENAME_RE.sub('', title)
    title = re.sub(r'\s+', ' ', title).strip('. ')
    if not title:
        return None
    return title[:180]


def get_name_ext(
        page_url: str,
        content: bytes,
        stream_url: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    name_wo_ext: Optional[str] = None
    extension: Optional[str] = None
    source_url = stream_url or page_url

    filename_groups = find_pattern_groups(source_url, r'filename=(([^&\?]+)\.([^&\?]+))')
    if filename_groups is not None:
        name_wo_ext = filename_groups.group(2)
        extension = filename_groups.group(3)

    content_str = None
    if content is not None:
        content_str = content.decode('utf-8', errors='replace')
        if name_wo_ext is None:
            name_wo_ext = find_pattern(content_str, r'N.zev souboru:<\/span>\s*?<span>([^<]+?)<\/span>')
            if name_wo_ext is None:
                name_wo_ext = find_pattern(
                    content_str,
                    r'N.zev souboru</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>([^<]+)</td>',
                )

        if extension is None:
            extension = find_pattern(source_url, r'\.([a-zA-Z0-9]+)[&\?]token')
            if extension is None:
                extension = find_pattern(content_str, r'Form.t:</span>\s*?<span>([^<]+?)</span>')
            if extension is None:
                extension = find_pattern(
                    content_str,
                    r'Form.t</td>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*>([^<]+)</td>',
                )

    if name_wo_ext is None and 'sledujteto' in page_url:
        path_parts = urlparse(page_url).path.strip('/').split('/')
        if len(path_parts) >= 3 and path_parts[0] == 'file':
            slug = path_parts[2]
            if slug.endswith('.html'):
                slug = slug[:-5]
            name_wo_ext = slug

    if name_wo_ext is None:
        parsed1 = urlparse(page_url).path
        segments = [segment for segment in parsed1.split('/') if segment]
        if segments and not (len(segments) >= 2 and segments[-2] == 'player'):
            name_wo_ext = segments[-1].replace('.html', '')

    if name_wo_ext is not None:
        name_wo_ext = unquote(name_wo_ext).strip('. ').replace(' ', '.')

    hellspy_name = _hellspy_stream_name(page_url, content_str)
    if hellspy_name:
        name_wo_ext = hellspy_name

    if extension is None:
        path_ext = os.path.splitext(urlparse(source_url).path)[1].lstrip('.')
        if path_ext and path_ext.isalnum():
            extension = path_ext
        else:
            extension = find_pattern(source_url, r'\.([a-zA-Z0-9]{2,5})(?:[&\?]|$)')

    if extension is None:
        extension = 'mp4'

    return name_wo_ext, extension
