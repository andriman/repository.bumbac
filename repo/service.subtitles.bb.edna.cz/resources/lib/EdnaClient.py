# -*- coding: utf-8 -*-
import os
import re
import hashlib
import urllib.parse
import zipfile
import copy
import html
import xbmc
import xbmcgui
import xbmcvfs

from utilities import log
from usage_stats import results_with_stats, mark_start_time
from LoginUtils import EdnaSession, BASE_URL
from edna_parse import (
	parse_show_search, parse_show_hits, parse_season_subtitles, parse_subtitle_links, build_season_url, movie_subtitle_url, subtitle_members,
	titulky_query_url, titulky_fulltext_query, titulky_title_matches, titulky_is_series_page, titulky_series_not_found,
	titulky_series_suggestions, titulky_episode_rips, titulky_season_page_url, titulky_fulltext_results,
	TITULKY_BASE,
)
from subtitle_cache import SubtitleCache
from cache_action import clear_if_titulky_action_changed
from captcha_dialog import CaptchaDialog

LANG_FLAGS = {"Czech": "cs", "Slovak": "sk"}
_SEARCH_ABORT = object()
_TITULKY_LINK_ERROR = "0"
_TITULKY_LINK_FOLLOW = "1"
_TITULKY_LINK_SEARCH = "2"
# A separator before one of these ends the title. The same characters also stand in for spaces.
_RIP_CUT = re.compile(
	r"(?:^|[ _.+\-()]+)(?:"
	r"(?:480|576|720|1080|1440|2160)p|4k|uhd|"
	r"blu[\s._+\-]*ray|bdrip|brrip|bdremux|remux|"
	r"web[\s._+\-]*dl|web[\s._+\-]*rip|hdtv|pdtv|hdrip|dvdrip|dvdscr|hdcam|"
	r"x264|x265|h[\s._+\-]*264|h[\s._+\-]*265|hevc|xvid|divx|"
	r"aac|ac3|eac3|dts|proper|repack|internal|limited|"
	r"s\d{1,2}[\s._+\-]*e\d{1,2}|"
	r"cz|sk|en|subs|sub|titulky|avi|mkv|mp4|srt|rar"
	r")(?=$|[ _.+\-()])",
	re.IGNORECASE,
)
_BRACKET_JUNK = re.compile(
	r"(?i)^(?:"
	r"\d+|(?:19|20)\d{2}|"
	r"(?:480|576|720|1080|1440|2160)p|"
	r"(?:cz|cze|cs|sk|slo|en|eng|de|ger|fr|pl|hu|ru|es|it)"
	r"(?:\s+(?:dab(?:ing)?|titulky|subs?|subtitles|audio))?|"
	r"(?:dab(?:ing)?|titulky|subs?|subtitles)"
	r")$"
)


def _bracket_is_junk(text):
	plain = re.sub(r"[._+\-]+", " ", text or "")
	plain = re.sub(r"\s+", " ", plain).strip()
	if len(plain) < 3:
		return True
	return _BRACKET_JUNK.fullmatch(plain) is not None


def title_from_brackets(title):
	"""Last bracket group that is a real name, not a language, year, or rip tag."""
	chosen = None
	for raw in re.findall(r"[\(\[]([^()\[\]]+)[\)\]]", title or ""):
		candidate = raw.strip()
		if _bracket_is_junk(candidate):
			continue
		chosen = candidate
	return chosen


def cleanup_search_title(title):
	"""Drop brackets, turn _.+- into spaces, and cut the name off at a rip tag."""
	original = title or ""
	cleaned = re.sub(r"(\[|\().+?(\]|\))", " ", original)
	while True:
		match = _RIP_CUT.search(cleaned)
		if not match:
			break
		if match.start() == 0:
			cleaned = cleaned[match.end():]
			continue
		cleaned = cleaned[:match.start()]
		break
	cleaned = re.sub(r"[_.+\-()]+", " ", cleaned)
	cleaned = re.sub(r"\s+", " ", cleaned).strip()
	if cleaned:
		return cleaned
	fallback = re.sub(r"[_.+\-()]+", " ", original)
	return re.sub(r"\s+", " ", fallback).strip() or original.strip()


class EdnaClient(object):

	def __init__(self, addon):
		self.server_url = BASE_URL
		self.addon = addon
		self._t = addon.getLocalizedString
		self._login_attempted = False
		profile = xbmcvfs.translatePath(self.addon.getAddonInfo("profile"))
		if not os.path.isdir(profile):
			os.makedirs(profile)
		self.session = EdnaSession(os.path.join(profile, "cookies.txt"))
		self.session.notify = self._notify_flow
		self.session.prompt_captcha = self._prompt_captcha
		self.session.wait_seconds = self._wait_seconds
		self._captcha_seq = 0
		mark_start_time()

	def _notify(self, message_id):
		xbmc.executebuiltin("Notification(%s,%s,5000,%s)" % (
			self.addon.getAddonInfo("name"),
			self._t(message_id),
			os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("path")), "icon.png"),
		))

	def _notify_flow(self, kind):
		if kind == "titulky":
			xbmcgui.Dialog().notification(
				self.addon.getAddonInfo("name"),
				self._t(32941),
				xbmcgui.NOTIFICATION_INFO,
				4000,
			)

	def _prompt_captcha(self, image_bytes, message):
		path = self._save_captcha_image(image_bytes)
		if not path:
			return None
		heading_id = 32944 if message == "wrong" else 32943
		dialog = CaptchaDialog(
			"DialogCaptcha.xml",
			xbmcvfs.translatePath(self.addon.getAddonInfo("path")),
			"Default",
			"1080i",
			image_path=path,
			heading=self._t(heading_id),
		)
		dialog.doModal()
		code = dialog.code
		del dialog
		return code

	def _save_captcha_image(self, data):
		if not data:
			return None
		dest_dir = os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")), "temp")
		if not os.path.isdir(dest_dir):
			os.makedirs(dest_dir)
		if data[:8] == b"\x89PNG\r\n\x1a\n":
			ext = ".png"
		elif data[:6] in (b"GIF87a", b"GIF89a"):
			ext = ".gif"
		elif data[:2] == b"BM":
			ext = ".bmp"
		else:
			ext = ".jpg"
		self._captcha_seq += 1
		path = os.path.join(dest_dir, "titulky-captcha-%s%s" % (self._captcha_seq, ext))
		with open(path, "wb") as handle:
			handle.write(data)
		return path

	def _wait_message(self, seconds):
		template = self._t(32942) or "Waiting %s seconds. Titulky.com adds this wait for visitors who are not signed in or premium."
		if "%s" not in template and "%d" not in template:
			template = "Waiting %s seconds. Titulky.com adds this wait for visitors who are not signed in or premium."
		try:
			return template % seconds
		except TypeError:
			return "Waiting %s seconds. Titulky.com adds this wait for visitors who are not signed in or premium." % seconds

	def _wait_seconds(self, seconds, message):
		progress = xbmcgui.DialogProgress()
		title = self.addon.getAddonInfo("name")
		progress.create(title, self._wait_message(seconds))
		cancelled = False
		for elapsed in range(seconds):
			if progress.iscanceled():
				cancelled = True
				break
			remaining = seconds - elapsed
			progress.update(int(elapsed * 100 / seconds), self._wait_message(remaining))
			xbmc.sleep(1000)
			if progress.iscanceled():
				cancelled = True
				break
		progress.close()
		return cancelled

	def _credentials(self):
		return self.addon.getSetting("username"), self.addon.getSetting("password")

	def ensure_login(self):
		if self.session.has_login_marker():
			return True
		return self._login()

	def _login(self):
		if self._login_attempted:
			return False
		self._login_attempted = True
		username, password = self._credentials()
		if not username or not password:
			log(__name__, "Missing login details")
			self._notify(32905)
			return False
		if self.session.login(username, password):
			log(__name__, "Logged in")
			return True
		log(__name__, "Login failed")
		self._notify(32905)
		return False

	def _read_page(self, url, ajax=False, use_cache=True):
		if use_cache:
			cached = self._cache().read_page(url)
			if cached:
				log(__name__, "Cached page %s" % url)
				return cached

		status, final, headers, body = self.session.request(url, ajax=ajax)
		if self.session.is_login_wall(status, final, body):
			log(__name__, "Login required for %s" % url)
			self.session.clear_login_marker()
			if self._login():
				status, final, headers, body = self.session.request(url, ajax=ajax)
		if self.session.is_login_wall(status, final, body):
			return None
		if status != 200:
			log(__name__, "HTTP %s for %s" % (status, url))
			return None
		page = body.decode("utf-8", "replace")
		self._cache().write_page(url, final, page)
		return final, page

	def download(self, link, name=None):
		self._cache().purge()
		if link.startswith("edna-cache:"):
			return self._download_cached(link)

		dest_dir = os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")), "temp")
		if not os.path.isdir(dest_dir):
			os.makedirs(dest_dir)

		digest = hashlib.sha1(link.encode("utf-8")).hexdigest()
		cached = self._cache().read_zip(digest)
		if cached:
			log(__name__, "Cached subtitle archive %s" % digest)
			return self._save_download(dest_dir, cached, name, "zip")

		log(__name__, "Downloading subtitles from %s" % link)
		fetched = self.session.fetch_subtitle(link)
		if not fetched:
			if self.session.last_error == "limit":
				log(__name__, "Titulky.com daily download limit")
				self._notify(32906)
			else:
				log(__name__, "Download did not return a subtitle file")
			return None

		filename, data = fetched
		log(__name__, "Filename: %s (%s bytes)" % (filename, len(data)))
		extension = os.path.splitext(filename)[1].lower().lstrip(".")
		if data[:2] == b"PK":
			extension = extension or "zip"
			self._cache().write_zip(digest, data, link)
			log(__name__, "Saved subtitle archive %s" % digest)
		if not extension:
			extension = "srt"
		return self._save_download(dest_dir, data, name, extension)

	def _save_download(self, dest_dir, data, name, extension):
		final_dest = os.path.join(dest_dir, self._download_filename(name, extension))
		with open(final_dest, "wb") as handle:
			handle.write(data)
		log(__name__, "Saving to file %s" % final_dest)
		return final_dest

	def _download_filename(self, name, extension):
		extension = (extension or "srt").lstrip(".").lower()
		cleaned = re.sub(r'[<>:"/\\|?*]', "_", name or "").strip().strip(".")
		if not cleaned:
			cleaned = "download"
		suffix = "." + extension
		if not cleaned.lower().endswith(suffix):
			cleaned += suffix
		return cleaned

	def _cache_dir(self):
		return os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")), "subtitle-cache")

	def _cache_ttl_seconds(self):
		raw = self.addon.getSetting("cache_minutes")
		try:
			minutes = int(raw)
		except (TypeError, ValueError):
			minutes = 10
		if minutes < 1:
			minutes = 10
		return minutes * 60

	def _cache(self):
		return SubtitleCache(self._cache_dir(), self._cache_ttl_seconds())

	def _archive_bytes(self, link, digest):
		cache = self._cache()
		cached = cache.read_zip(digest)
		if cached:
			log(__name__, "Cached subtitle archive %s" % digest)
			return cached

		try:
			fetched = self.session.fetch_subtitle(link)
		except Exception as error:
			log(__name__, "Could not open subtitle archive: %s" % error)
			return None
		if not fetched:
			if self.session.last_error == "limit":
				log(__name__, "Titulky.com daily download limit")
				self._notify(32906)
			return None
		filename, data = fetched
		if data[:2] != b"PK":
			return None
		cache.write_zip(digest, data, link)
		log(__name__, "Saved subtitle archive %s (%s bytes)" % (filename, len(data)))
		return data

	def _results_for_version(self, link, language_name, episode_title):
		fallback = [self._result_item(html.unescape(episode_title), link, language_name)]
		digest = hashlib.sha1(link.encode("utf-8")).hexdigest()
		data = self._archive_bytes(link, digest)
		if not data:
			return fallback

		members = subtitle_members(data)
		if not members:
			return fallback

		results = []
		for member in members:
			display_name = member.replace("\\", "/").split("/")[-1] or member
			results.append(self._result_item(display_name, "edna-cache:%s:%s" % (digest, member), language_name))
		log(__name__, ["Archive files", len(results)])
		return results

	def _result_item(self, filename, link, language_name):
		return {
			"filename": filename,
			"link": link,
			"lang": LANG_FLAGS.get(language_name, language_name),
			"rating": "0",
			"sync": False,
			"lang_flag": self._language_flag(language_name),
		}

	def _download_cached(self, link):
		rest = link[len("edna-cache:"):]
		digest, member = rest.split(":", 1)
		if not re.match(r"^[0-9a-f]{40}$", digest) or ".." in member.replace("\\", "/"):
			log(__name__, "Rejected cached subtitle name")
			return None

		archive_path = self._cache().zip_path(digest)
		source_url = ""
		url_path = archive_path + ".url"
		if os.path.isfile(url_path):
			with open(url_path, "r", encoding="utf-8") as handle:
				source_url = handle.read().strip()
		data = self._archive_bytes(source_url, digest) if source_url else self._cache().read_zip(digest)
		if not data:
			log(__name__, "Cached subtitle archive is missing")
			return None

		dest_dir = os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")), "temp")
		if not os.path.isdir(dest_dir):
			os.makedirs(dest_dir)
		with zipfile.ZipFile(archive_path) as archive:
			if member not in archive.namelist():
				log(__name__, "Subtitle file is not in the archive")
				return None
			data = archive.read(member)
		display_name = member.replace("\\", "/").split("/")[-1] or "subtitle.srt"
		display_name = re.sub(r'[<>:"/\\|?*]', "_", display_name) or "subtitle.srt"
		final_dest = os.path.join(dest_dir, display_name)
		with open(final_dest, "wb") as handle:
			handle.write(data)
		log(__name__, "Selected subtitle %s" % display_name)
		return final_dest

	def normalize_input_title(self, title):
		if self.addon.getSetting("search_title_in_brackets") == "true":
			log(__name__, "Searching title in brackets - %s" % title)
			bracket = title_from_brackets(title)
			if bracket:
				title = bracket

		if re.search(r", The$", title, re.IGNORECASE):
			log(__name__, "Swap The - %s" % title)
			title = "The " + re.sub(r"(?i), The$", "", title)

		if self.addon.getSetting("try_cleanup_title") == "true":
			cleaned = cleanup_search_title(title)
			log(__name__, "Title cleanup - %s -> %s" % (title, cleaned))
			title = cleaned

		return title.strip()

	def _apply_release_episode(self, item):
		"""Streams often leave season and episode empty and put SxxExx in the file title."""
		if str(item.get("season") or "").strip() and str(item.get("episode") or "").strip():
			return
		sources = (item.get("tvshow") or "", item.get("title") or "", item.get("file_original_path") or "")
		pattern = re.compile(r"(?i)(?:^|[\s._+\-])S0*(\d{1,2})[\s._+\-]*E0*(\d{1,3})(?:$|[\s._+\-])")
		for text in sources:
			match = pattern.search(urllib.parse.unquote(text))
			if not match:
				continue
			item["season"] = str(int(match.group(1)))
			item["episode"] = str(int(match.group(2)))
			log(__name__, "Release episode S%sE%s" % (item["season"], item["episode"]))
			return

	def search(self, item):
		log(__name__, "() Start")
		clear_if_titulky_action_changed(self.addon, notify=True)
		self._cache().purge()

		if item["mansearch"]:
			title = item["mansearchstr"]
			dialog = xbmcgui.Dialog()
			item["season"] = dialog.numeric(0, self._t(32111), item["season"])
			item["episode"] = dialog.numeric(0, self._t(32112), item["episode"])
		else:
			self._apply_release_episode(item)
			title = self.normalize_input_title(item.get("tvshow") or "") or self.normalize_input_title(item.get("title") or "")

		season = str(item.get("season") or "").strip()
		episode = str(item.get("episode") or "").strip()
		if not title or (season and not episode) or (episode and not season):
			self._notify(32110)
			log(__name__, ["Input validation error", title, season, episode])
			return results_with_stats(None, self.addon, title, item)

		result_subtitles = self._results_for_title(title, item)
		if result_subtitles is _SEARCH_ABORT:
			return results_with_stats(None, self.addon, title, item)
		if not result_subtitles:
			chosen = self._choose_shorter_title(title)
			if chosen:
				title = chosen
				result_subtitles = self._results_for_title(title, item)
				if result_subtitles is _SEARCH_ABORT:
					return results_with_stats(None, self.addon, title, item)

		log(__name__, ["Search result", 0 if not result_subtitles else len(result_subtitles)])
		return results_with_stats(result_subtitles or None, self.addon, title, item)

	def _label(self, string_id, fallback):
		text = self._t(string_id)
		return text or fallback

	def _choose_shorter_title(self, title):
		words = title.split()
		if len(words) < 2:
			return None
		options = [" ".join(words[:count]) for count in range(1, len(words) + 1)]
		custom_label = self._label(32948, "Custom search")
		options.append(custom_label)
		selected = xbmcgui.Dialog().select(self._label(32947, "Select search title"), options)
		if selected < 0:
			return None
		if selected == len(options) - 1:
			typed = xbmcgui.Dialog().input(self._label(32948, "Custom search"), title)
			typed = (typed or "").strip()
			if not typed or typed == title:
				return None
			return typed
		chosen = options[selected]
		if chosen == title:
			return None
		return chosen

	def _results_for_title(self, title, item):
		season = str(item.get("season") or "").strip()
		episode = str(item.get("episode") or "").strip()
		if not season and not episode:
			if self._titulky_link_action() == _TITULKY_LINK_ERROR:
				show_url = self.search_show_url(title)
				if show_url is _SEARCH_ABORT:
					return _SEARCH_ABORT
				if not show_url:
					return self._no_such_title()
				return self._movie_on_edna(title, show_url)
			return self._titulky_movie_results(title)

		tvshow_url = self.search_show_url(title, reuse=bool(item.get("follow")))
		if tvshow_url is _SEARCH_ABORT:
			return _SEARCH_ABORT
		if not tvshow_url:
			return self._no_such_title()

		if not self.ensure_login():
			return _SEARCH_ABORT

		found_season_subtitles = self.search_season_subtitles(tvshow_url, season)
		log(__name__, ["Season filter", len(found_season_subtitles)])

		episode_subtitle_list = self.filter_episode_from_season_subtitles(found_season_subtitles, season, episode)
		log(__name__, ["Episode filter", episode_subtitle_list["full_title"] if episode_subtitle_list else None])
		if episode_subtitle_list is None:
			return []

		lang_filtered = self.filter_subtitles_by_language(episode_subtitle_list)
		log(__name__, ["Language filter", None if lang_filtered is None else len(lang_filtered["versions"])])
		if lang_filtered is None:
			return []

		result_subtitles = []
		searched_titulky = False
		offer_follow = False
		for episode_subtitle in lang_filtered["versions"]:
			link = episode_subtitle["link"]
			if link.startswith("/"):
				link = self.server_url + link
			if "titulky.com" in link.lower():
				action = _TITULKY_LINK_FOLLOW if item.get("follow") else self._titulky_link_action()
				log(__name__, ["Titulky.com link", action, link])
				if action == _TITULKY_LINK_FOLLOW:
					result_subtitles.extend(self._results_for_version(link, episode_subtitle["lang"], lang_filtered["full_title"]))
				elif action == _TITULKY_LINK_ERROR:
					offer_follow = True
				elif not searched_titulky:
					result_subtitles.extend(self._titulky_episode_results(title, item.get("year"), season, episode))
					searched_titulky = True
				continue
			result_subtitles.extend(self._results_for_version(link, episode_subtitle["lang"], lang_filtered["full_title"]))
		if offer_follow:
			result_subtitles.insert(0, {"follow": True})
		return result_subtitles

	def _no_such_title(self):
		log(__name__, "Edna.cz has no such title")
		message = self._t(32967) or "Edna.cz has no such title"
		xbmcgui.Dialog().notification(self.addon.getAddonInfo("name"), message, xbmcgui.NOTIFICATION_INFO, 5000)
		return []

	def _movie_on_edna(self, title, show_url):
		"""A movie page exists. Only mention Titulky.com when a subtitle link goes there."""
		if not self.ensure_login():
			return _SEARCH_ABORT
		url = movie_subtitle_url(self.server_url, show_url)
		log(__name__, "Movie subtitles %s" % url)
		opened = self._read_page(url)
		if not opened:
			return []
		page_url, page = opened
		selected = set(self._selected_languages())
		versions = [version for version in parse_subtitle_links(page) if version["lang"] in selected]
		if not versions and "titulky.com" in page.lower():
			log(__name__, "Titulky.com action: end in error")
			self._notify(32955)
			return []
		result_subtitles = []
		points_to_titulky = False
		for version in versions:
			link = version["link"]
			if link.startswith("/"):
				link = self.server_url + link
			elif not link.startswith("http"):
				link = urllib.parse.urljoin(page_url, link)
			if "titulky.com" in link.lower():
				points_to_titulky = True
				continue
			result_subtitles.extend(self._results_for_version(link, version["lang"], title))
		if points_to_titulky and not result_subtitles:
			log(__name__, "Titulky.com action: end in error")
			self._notify(32955)
		return result_subtitles

	def _titulky_link_action(self):
		value = self.addon.getSetting("titulky_link_action")
		if value in (_TITULKY_LINK_ERROR, _TITULKY_LINK_FOLLOW, _TITULKY_LINK_SEARCH):
			return value
		return _TITULKY_LINK_SEARCH

	def _selected_languages(self):
		selected = []
		if self._setting_enabled("search_czech"):
			selected.append("Czech")
		if self._setting_enabled("search_slovak"):
			selected.append("Slovak")
		return selected

	def _titulky_episode_results(self, show, year, season, episode):
		query = show.strip()
		year_text = str(year or "").strip()
		if re.fullmatch(r"\d{4}", year_text):
			query = "%s (%s)" % (query, year_text)
		url = titulky_query_url("serial", query)
		log(__name__, "Titulky.com series search %s" % url)
		opened = self._read_page(url)
		if not opened:
			return self._titulky_fulltext_episode_results(show, season, episode)
		page_url, page = opened
		if titulky_series_not_found(page):
			suggestions = titulky_series_suggestions(page)
			if not suggestions:
				return self._titulky_fulltext_episode_results(show, season, episode)
			chosen = self._choose_series_suggestion(suggestions, show, year_text)
			if not chosen:
				return []
			opened = self._read_page(chosen)
			if not opened:
				return []
			page_url, page = opened
		elif not titulky_is_series_page(page):
			return self._titulky_fulltext_episode_results(show, season, episode)

		rips = titulky_episode_rips(page, season, episode)
		if not rips:
			season_url = titulky_season_page_url(page, page_url, season)
			if season_url:
				log(__name__, "Titulky.com season page %s" % season_url)
				opened = self._read_page(season_url)
				if opened:
					page_url, page = opened
					rips = titulky_episode_rips(page, season, episode)
		if not rips:
			return self._titulky_fulltext_episode_results(show, season, episode)
		code = "S%02dE%02d" % (int(season), int(episode))
		return self._rip_results(rips, page_url, code)

	def _choose_series_suggestion(self, suggestions, show, year_text):
		exact = []
		for suggestion in suggestions:
			name = re.sub(r"\s*\(\d{4}\)\s*$", "", suggestion["title"]).strip()
			if titulky_title_matches(show, name) and year_text and suggestion["year"] == year_text:
				exact.append(suggestion)
		if len(exact) == 1:
			log(__name__, "Titulky.com series match %s" % exact[0]["title"])
			return urllib.parse.urljoin(TITULKY_BASE + "/", exact[0]["url"])
		log(__name__, "Titulky.com series suggestions %s" % len(suggestions))
		dialog = xbmcgui.Dialog()
		selected = dialog.select(self._t(32003), [suggestion["title"] for suggestion in suggestions])
		if selected == -1:
			return None
		return urllib.parse.urljoin(TITULKY_BASE + "/", suggestions[selected]["url"])

	def _titulky_fulltext_episode_results(self, show, season, episode):
		show = titulky_fulltext_query(show)
		code = "S%02dE%02d" % (int(season), int(episode))
		url = titulky_query_url("Fulltext", "%s %s" % (show.strip(), code))
		log(__name__, "Titulky.com fulltext %s" % url)
		opened = self._read_page(url)
		if not opened:
			return []
		page_url, page = opened
		rips = []
		for row in titulky_fulltext_results(page):
			if row["episode"] != code or not titulky_title_matches(show, row["title"]):
				continue
			rips.append({
				"release": row["release"] or row["title"],
				"link": row["link"],
				"lang": row["lang"],
			})
		return self._rip_results(rips, page_url, code)

	def _titulky_movie_results(self, title):
		title = titulky_fulltext_query(title)
		url = titulky_query_url("Fulltext", title.strip())
		log(__name__, "Titulky.com movie search %s" % url)
		opened = self._read_page(url)
		if not opened:
			return []
		page_url, page = opened
		rips = []
		for row in titulky_fulltext_results(page):
			if row["episode"] or not titulky_title_matches(title, row["title"]):
				continue
			rips.append({
				"release": row["release"] or row["title"],
				"link": row["link"],
				"lang": row["lang"],
			})
		return self._rip_results(rips, page_url)

	def _rip_results(self, rips, page_url, episode_code=""):
		selected = set(self._selected_languages())
		results = []
		seen = set()
		for rip in rips:
			if rip["lang"] not in selected:
				continue
			link = urllib.parse.urljoin(page_url, rip["link"])
			if link in seen:
				continue
			seen.add(link)
			label = self._rip_label(rip["release"] or link, episode_code)
			results.append(self._result_item(label, link, rip["lang"]))
		log(__name__, ["Titulky.com rips", len(results)])
		return results

	def _rip_label(self, release, episode_code):
		release = (release or "").strip()
		code = (episode_code or "").strip().upper()
		if code and release and not release.upper().startswith(code):
			return "%s %s" % (code, release)
		return release or code

	def _language_flag(self, language_name):
		code = xbmc.convertLanguage(language_name, xbmc.ISO_639_1) or LANG_FLAGS.get(language_name, "")
		if code and not code.endswith(".gif"):
			code += ".gif"
		return code

	def _setting_enabled(self, setting_id):
		value = self.addon.getSetting(setting_id)
		if value == "":
			return True
		return value == "true"

	def filter_subtitles_by_language(self, subtitles_list):
		selected = []
		if self._setting_enabled("search_czech"):
			selected.append("Czech")
		if self._setting_enabled("search_slovak"):
			selected.append("Slovak")
		log(__name__, ["Filter by languages", selected])
		if not selected:
			return None

		filter_subtitles_list = [subtitle for subtitle in subtitles_list["versions"] if subtitle["lang"] in selected]
		if not filter_subtitles_list:
			return None

		filter_results_list = copy.deepcopy(subtitles_list)
		filter_results_list["versions"] = filter_subtitles_list
		return filter_results_list

	def filter_episode_from_season_subtitles(self, season_subtitles, season, episode):
		for season_subtitle in season_subtitles:
			if season_subtitle["episode"] == int(episode) and season_subtitle["season"] == int(season):
				return season_subtitle
		return None

	def search_show_url(self, title, reuse=False):
		log(__name__, "Starting search by TV Show: %s" % title)
		if not title:
			return None
		if reuse:
			remembered = self._reused_show(title)
			if remembered:
				log(__name__, "Reusing show URL: " + remembered)
				return remembered

		url = self.server_url + "/vyhledavani/?" + urllib.parse.urlencode({
			"usersOnly": "0",
			"isOpenSearch": "0",
			"withoutUser": "1",
			"q": title,
		})
		opened = self._read_page(url, ajax=True)
		if opened and not parse_show_hits(opened[1], self.server_url):
			opened = self._read_page(url, ajax=True, use_cache=False)
		if not opened:
			return None
		final_url, page = opened
		log(__name__, "Search URL: %s" % final_url)

		found_tv_shows = parse_show_hits(page, self.server_url)
		if not found_tv_shows and "/vyhledavani/" in final_url:
			found_tv_shows = parse_show_search(page)
		elif not found_tv_shows:
			path = urllib.parse.urlparse(final_url).path
			if not path.endswith("/"):
				path += "/"
			found_tv_shows.append({"url": path, "title": title})

		if len(found_tv_shows) == 0:
			log(__name__, "No TV Show found")
			return None
		log(__name__, ["Show choices", len(found_tv_shows)])
		return self._choose_show(found_tv_shows, title)

	def _choose_show(self, shows, query):
		heading = self._t(32959) or "Select title"
		items = []
		preselect = 0
		wanted = (query or "").casefold()
		for index, show in enumerate(shows):
			details = "  ".join(part for part in (show.get("kind"), show.get("year")) if part)
			listitem = xbmcgui.ListItem(label=show["title"], label2=details)
			image = self._local_poster(show.get("image") or "")
			if image:
				listitem.setArt({"icon": image, "thumb": image, "poster": image})
			items.append(listitem)
			if show["title"].casefold() == wanted:
				preselect = index
		try:
			selected = xbmcgui.Dialog().select(heading, items, 0, preselect, True)
		except TypeError:
			selected = xbmcgui.Dialog().select(heading, ["%s  %s" % (show["title"], show.get("year") or "") for show in shows])
		if selected < 0:
			return _SEARCH_ABORT
		log(__name__, "Selected show URL: " + shows[selected]["url"])
		self._remember_show(query, shows[selected]["url"])
		return shows[selected]["url"]

	def _show_choice_path(self):
		return os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")), "chosen-show.txt")

	def _remember_show(self, title, url):
		try:
			with open(self._show_choice_path(), "w", encoding="utf-8") as handle:
				handle.write((title or "") + "\n" + (url or ""))
		except OSError:
			pass

	def _reused_show(self, title):
		try:
			with open(self._show_choice_path(), "r", encoding="utf-8") as handle:
				lines = handle.read().splitlines()
		except OSError:
			return None
		if len(lines) >= 2 and lines[0] == title and lines[1]:
			return lines[1]
		return None

	def _local_poster(self, url):
		"""Kodi's select dialog shows a local file. The remote poster is saved first."""
		if not url:
			return ""
		folder = os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")), "show-posters")
		os.makedirs(folder, exist_ok=True)
		ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
		if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
			ext = ".jpg"
		path = os.path.join(folder, hashlib.sha1(url.encode("utf-8")).hexdigest() + ext)
		if os.path.isfile(path) and os.path.getsize(path) > 32:
			return path
		status, final, headers, body = self.session.request(url, referer=self.server_url + "/")
		if status != 200 or not body or not body.startswith((b"\x89PNG", b"\xff\xd8", b"GIF8", b"RIFF")):
			log(__name__, "Poster was not downloaded %s" % url)
			return ""
		try:
			with open(path, "wb") as handle:
				handle.write(body)
		except OSError:
			return ""
		return path

	def search_season_subtitles(self, show_url, show_series):
		url = build_season_url(self.server_url, show_url, show_series)
		log(__name__, "URL: " + url)
		opened = self._read_page(url)
		if not opened:
			return []
		final_url, page = opened
		return parse_season_subtitles(page)
