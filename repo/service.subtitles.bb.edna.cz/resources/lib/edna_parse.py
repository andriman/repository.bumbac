# -*- coding: utf-8 -*-
import os
import re
import time
import urllib.parse
import html as html_lib
from html.parser import HTMLParser


def parse_show_search(page_html):
	"""Return TV shows from an Edna search results page."""
	shows = []
	parts = re.split(r"<h2\b[^>]*>", page_html, flags=re.IGNORECASE)
	series_html = ""
	for part in parts[1:]:
		heading_html, _, rest = part.partition("</h2>")
		heading = re.sub(r"<[^>]+>", "", heading_html)
		heading = re.sub(r"\s+", " ", heading).strip().lower()
		if heading.startswith("seri"):
			series_html = rest
			break
	if not series_html:
		return shows

	for href, title in re.findall(r"<h3>\s*<a href=\"([^\"]+)\">([^<]+)</a>\s*</h3>", series_html, re.IGNORECASE):
		title = html_lib.unescape(title).strip()
		href = html_lib.unescape(href).strip()
		if not href or not title:
			continue
		shows.append({"url": href, "title": title})
	return shows


def parse_show_hits(page_text, server):
	"""Rows from the Edna search feed: title|image|url|type|count|year."""
	shows = []
	base = (server or "").rstrip("/") + "/"
	for raw_line in (page_text or "").splitlines():
		line = raw_line.strip()
		if line.count("|") < 5:
			continue
		parts = line.split("|")
		year = parts[-1].strip()
		kind = parts[-3].strip()
		href = html_lib.unescape(parts[-4].strip())
		image = html_lib.unescape(parts[-5].strip())
		title = html_lib.unescape("|".join(parts[:-5]).strip())
		if not title or not href or not re.fullmatch(r"(?:19|20)\d{2}", year):
			continue
		if image and not image.startswith("http"):
			image = urllib.parse.urljoin(base, image.lstrip("/"))
		if not href.startswith("http"):
			href = href if href.startswith("/") else "/" + href
		shows.append({
			"title": title,
			"url": href,
			"image": image,
			"kind": kind,
			"year": year,
		})
	return shows


def build_season_url(server, show_url, season):
	if show_url.startswith("http://") or show_url.startswith("https://"):
		base = show_url
	else:
		base = server.rstrip("/") + "/" + show_url.lstrip("/")
	if not base.endswith("/"):
		base += "/"
	return base + "titulky/?season=" + str(int(season))


def movie_subtitle_url(server, show_url):
	if show_url.startswith("http://") or show_url.startswith("https://"):
		base = show_url
	else:
		base = server.rstrip("/") + "/" + show_url.lstrip("/")
	if not base.endswith("/"):
		base += "/"
	return base + "titulky/"


def parse_subtitle_links(page_html):
	"""Language download links on an Edna subtitle page."""
	versions = []
	seen = set()
	for href, lang in re.findall(
		r"<a href=\"([^\"]+)\" class=\"flag[^\"]*\"[\s\S]*?<i class=\"flag-(cz|sk)\">",
		page_html or "",
		re.IGNORECASE,
	):
		link = html_lib.unescape(href).strip()
		if not link or link in seen:
			continue
		seen.add(link)
		versions.append({
			"link": link,
			"lang": "Czech" if lang.lower() == "cz" else "Slovak",
		})
	return versions


def parse_season_subtitles(page_html):
	"""Return episode subtitle entries from a logged-in season page."""
	subtitles = []
	for row in re.findall(r"<li class=\"ed-box-row\">(.*?)</li>", page_html, re.IGNORECASE | re.DOTALL):
		title_match = re.search(
			r"class=\"[^\"]*ed-box-title[^\"]*\"[^>]*>\s*(S0*(\d+)E0*(\d+):\s*([^<]+))</a>",
			row,
			re.IGNORECASE,
		)
		if not title_match:
			continue
		versions = []
		for href, lang in re.findall(
			r"<a href=\"([^\"]+)\" class=\"flag[^\"]*\"[\s\S]*?<i class=\"flag-(cz|sk)\">",
			row,
			re.IGNORECASE,
		):
			lang_name = "Czech" if lang.lower() == "cz" else "Slovak"
			versions.append({
				"link": html_lib.unescape(href).strip(),
				"lang": lang_name,
			})
		if not versions:
			continue
		subtitles.append({
			"full_title": html_lib.unescape(title_match.group(1)).strip(),
			"season": int(title_match.group(2)),
			"episode": int(title_match.group(3)),
			"title": html_lib.unescape(title_match.group(4)).strip(),
			"versions": versions,
		})
	return subtitles


TITULKY_BASE = "https://www.titulky.com"


def titulky_query_url(key, value):
	"""Build a Titulky.com search URL. Spaces and parentheses must be encoded."""
	return TITULKY_BASE + "/?" + urllib.parse.urlencode({key: value})


def titulky_fulltext_query(text):
	"""Fulltext treats a trailing year as part of the title, so drop it."""
	query = re.sub(r"\s+", " ", text or "").strip()
	cleaned = re.sub(
		r"(?:[\s._-]+|\s*\(\s*)(?:19|20)\d{2}\s*\)?\s*$",
		"",
		query,
	).strip(" .-_")
	return cleaned or query


def titulky_title_matches(query, candidate):
	"""True when the show name is the title. Fallout does not match Mission Impossible Fallout."""
	wanted = re.sub(r"[\s._+\-]+", " ", query or "").strip().casefold()
	found = re.sub(r"[\s._+\-]+", " ", candidate or "").strip().casefold()
	found = re.sub(r"\s*s\d+e\d+\s*$", "", found)
	found = re.sub(r"\s*\(\d{4}\)\s*$", "", found).strip()
	if not wanted or not found:
		return False
	# The show name has to be the title, not a later word. Fallout does not match Mission Impossible Fallout.
	return re.match(re.escape(wanted) + r"(?!\w)", found) is not None


def _plain_text(fragment):
	text = re.sub(r"<[^>]+>", "", fragment or "")
	text = html_lib.unescape(text).replace("\xa0", " ")
	return re.sub(r"\s+", " ", text).strip()


def _flag_language(fragment):
	match = re.search(r"alt=\"(CZ|SK)\"|flag-(cz|sk)", fragment or "", re.IGNORECASE)
	if not match:
		return None
	code = (match.group(1) or match.group(2) or "").lower()
	if code == "cz":
		return "Czech"
	if code == "sk":
		return "Slovak"
	return None


def _episode_code(season, episode):
	return "S%02dE%02d" % (int(season), int(episode))


def _heading_episode(text):
	match = re.search(r"S0*(\d+)\s*E0*(\d+)", text or "", re.IGNORECASE)
	if not match:
		return None
	return "S%02dE%02d" % (int(match.group(1)), int(match.group(2)))


def titulky_series_not_found(page_html):
	return "nebyl nalezen" in (page_html or "").lower()


def titulky_is_series_page(page_html):
	if not page_html or titulky_series_not_found(page_html):
		return False
	return 'id="sekceserial"' in page_html and "<h4" in page_html.lower()


def titulky_series_suggestions(page_html):
	"""Shows listed under Další seriály on a not-found page."""
	match = re.search(r"Další seriály", page_html or "", re.IGNORECASE)
	if not match:
		return []
	chunk = page_html[match.end():]
	chunk = chunk.split("</div>")[0]
	suggestions = []
	for href, inner in re.findall(r'<a href="([^"]*serial2=[^"]*)"[^>]*>(.*?)</a>', chunk, re.IGNORECASE | re.DOTALL):
		title = _plain_text(inner)
		if not title:
			continue
		year_match = re.search(r"\((\d{4})\)\s*$", title)
		suggestions.append({
			"title": title,
			"url": html_lib.unescape(href).strip(),
			"year": year_match.group(1) if year_match else "",
		})
	return suggestions


def titulky_episode_rips(page_html, season, episode):
	"""Release links inside one [SxxExx] block on a series page."""
	wanted = _episode_code(season, episode)
	parts = re.split(r"<h4\b[^>]*>", page_html or "", flags=re.IGNORECASE)
	for part in parts[1:]:
		heading, _, rest = part.partition("</h4>")
		if _heading_episode(_plain_text(heading)) != wanted:
			continue
		rips = []
		for block in re.findall(r'<div class="polepiz">(.*?)</div>', rest, re.IGNORECASE | re.DOTALL):
			link_match = re.search(r'<a[^>]+href="([^"]+\.htm)"[^>]*>(.*?)</a>', block, re.IGNORECASE | re.DOTALL)
			if not link_match:
				continue
			language = _flag_language(block)
			if not language:
				continue
			rips.append({
				"release": _plain_text(link_match.group(2)),
				"link": html_lib.unescape(link_match.group(1)).strip(),
				"lang": language,
			})
		return rips
	return []


def titulky_season_page_url(page_html, page_url, season):
	match = re.search(r'href="([^"]*TV-Serial-[^"]*-S%d\.htm)"' % int(season), page_html or "", re.IGNORECASE)
	if not match:
		return None
	return urllib.parse.urljoin(page_url, html_lib.unescape(match.group(1)))


def titulky_fulltext_results(page_html):
	"""Rows from a Titulky.com fulltext search."""
	results = []
	for row in re.findall(r'<tr class="r1?">(.*?)</tr>', page_html or "", re.IGNORECASE | re.DOTALL):
		link_match = re.search(r'<a href="([^"]+\.htm)"[^>]*>(.*?)</a>', row, re.IGNORECASE | re.DOTALL)
		if not link_match:
			continue
		language = _flag_language(row)
		if not language:
			continue
		tip = re.search(r'class="listTip"[^>]*title="([^"]*)"', row, re.IGNORECASE)
		episode = ""
		year = ""
		for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL):
			plain = _plain_text(cell)
			code = _heading_episode(plain)
			if code and plain.upper().startswith("S"):
				episode = code
			elif not year and re.fullmatch(r"(?:19|20)\d{2}", plain):
				year = plain
		results.append({
			"title": _plain_text(link_match.group(2)),
			"release": html_lib.unescape(tip.group(1)).strip() if tip else "",
			"link": html_lib.unescape(link_match.group(1)).strip(),
			"episode": episode,
			"year": year,
			"lang": language,
		})
	return results


def titulky_zip_url(page_html, page_url):
	"""Prefer the ZIP download on a titulky.com detail page."""
	match = re.search(r"href=\"(idown\.php\?[^\"]*zip=z[^\"]*)\"", page_html, re.IGNORECASE)
	if not match:
		match = re.search(r"href=\"(idown\.php\?[^\"]+)\"", page_html, re.IGNORECASE)
	if not match:
		return None
	url = urllib.parse.urljoin(page_url, html_lib.unescape(match.group(1)))
	return titulky_with_timer(page_html, url)


def titulky_with_timer(page_html, url):
	"""The detail page appends T=verTimer-timestamp before opening idown.php."""
	parts = urllib.parse.urlsplit(url)
	query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
	if any(key == "T" for key, value in query):
		return url
	match = re.search(r"\bverTimer\s*=\s*(\d+)", page_html or "")
	timer = match.group(1) if match else "1"
	query.append(("T", "%s-%d" % (timer, int(time.time() * 1000))))
	return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), ""))


def titulky_file_url(page_html, page_url):
	"""The interstitial page points at the one-time file URL."""
	match = re.search(r"href=\"(/idown\.php\?id=\d+)\"", page_html, re.IGNORECASE)
	if not match:
		return None
	return urllib.parse.urljoin(page_url, match.group(1))


def titulky_download_delay(page_html):
	"""Seconds before idown.php?id= becomes valid. The page calls CountDown(n)."""
	match = re.search(r"CountDown\((\d+)\)", page_html)
	if not match:
		return 0
	return int(match.group(1))


def is_titulky_captcha(page_html):
	lowered = page_html.lower()
	return "downkod" in lowered or "captcha.php" in lowered


class _CaptchaFormParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.forms = []
		self._current = None
		self.image = None

	def handle_starttag(self, tag, attrs):
		attributes = dict(attrs)
		if tag == "form":
			self._current = {
				"name": attributes.get("name", ""),
				"action": attributes.get("action"),
				"fields": [],
			}
		elif tag == "input" and self._current is not None and attributes.get("name"):
			self._current["fields"].append((attributes["name"], attributes.get("value", "")))
		elif tag == "img" and "captcha.php" in (attributes.get("src") or ""):
			self.image = attributes.get("src")

	def handle_endtag(self, tag):
		if tag == "form" and self._current is not None:
			self.forms.append(self._current)
			self._current = None


def titulky_captcha_form(page_html, page_url):
	"""Return (post_url, fields, image_url) for the security-code form."""
	parser = _CaptchaFormParser()
	try:
		parser.feed(page_html)
	except Exception:
		return None
	form = None
	for candidate in parser.forms:
		if candidate["name"] == "downform":
			form = candidate
			break
	if form is None:
		for candidate in parser.forms:
			if any(name == "downkod" for name, value in candidate["fields"]):
				form = candidate
				break
	if form is None or not parser.image:
		return None
	post_url = urllib.parse.urljoin(page_url, form["action"] or "idown.php")
	image_url = urllib.parse.urljoin(page_url, parser.image)
	fields = [(name, value) for name, value in form["fields"] if name != "downkod"]
	return post_url, fields, image_url


def edna_direct_download_url(url):
	"""Episode pages start the file download from titulky/?direct=1."""
	parts = urllib.parse.urlsplit(url)
	if "edna.cz" not in parts.netloc.lower():
		return urllib.parse.urlunsplit(parts._replace(fragment=""))
	path = parts.path or ""
	if not path.rstrip("/").endswith("titulky"):
		return urllib.parse.urlunsplit(parts._replace(fragment=""))
	query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
	if any(key == "direct" for key, value in query):
		return urllib.parse.urlunsplit(parts._replace(fragment=""))
	query.append(("direct", "1"))
	return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, urllib.parse.urlencode(query), ""))


SUBTITLE_EXTENSIONS = (".srt", ".sub", ".txt", ".smi", ".ssa", ".ass")


def subtitle_members(archive_bytes):
	"""Subtitle file names stored in a zip archive."""
	import io
	import zipfile
	try:
		with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
			names = []
			for info in archive.infolist():
				if info.is_dir():
					continue
				if os.path.splitext(info.filename)[1].lower() in SUBTITLE_EXTENSIONS:
					names.append(info.filename)
			return names
	except zipfile.BadZipFile:
		return []


def content_disposition_filename(header):
	if not header:
		return None
	encoded = re.search(r"filename\*=([^']*)''([^;]+)", header, re.IGNORECASE)
	if encoded:
		return urllib.parse.unquote(encoded.group(2).strip().strip('"'))
	quoted = re.search(r"filename=\"([^\"]+)\"", header, re.IGNORECASE)
	if quoted:
		return quoted.group(1)
	plain = re.search(r"filename=([^;]+)", header, re.IGNORECASE)
	if plain:
		return plain.group(1).strip().strip('"')
	return None


def is_html_payload(data, content_type):
	if data[:2] == b"PK" or data[:4] == b"Rar!":
		return False
	if content_type and "html" in content_type.lower():
		return True
	start = data[:300].lstrip().lower()
	return start.startswith(b"<!doctype html") or start.startswith(b"<html") or start.startswith(b"<head")
