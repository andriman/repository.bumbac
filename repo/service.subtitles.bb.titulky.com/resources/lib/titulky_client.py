# -*- coding: utf-8 -*-
import os
import re
import json
import hashlib
import urllib.parse
import xbmc
import xbmcgui
import xbmcvfs

from utilities import log
from usage_stats import results_with_stats, mark_start_time
from titulky_session import TitulkySession
from titulky_parse import (
	titulky_query_url, titulky_fulltext_query, titulky_title_matches, titulky_is_series_page, titulky_series_not_found,
	titulky_series_suggestions, titulky_episode_rips, titulky_page_rips, titulky_season_page_url, titulky_season_links, titulky_fulltext_results,
	TITULKY_BASE,
)
from subtitle_cache import SubtitleCache
from captcha_dialog import CaptchaDialog

LANG_FLAGS = {"Czech": "cs", "Slovak": "sk"}
_SEARCH_ABORT = object()
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


class TitulkyClient(object):

	def __init__(self, addon):
		self.addon = addon
		self._t = addon.getLocalizedString
		profile = xbmcvfs.translatePath(self.addon.getAddonInfo("profile"))
		if not os.path.isdir(profile):
			os.makedirs(profile)
		self.session = TitulkySession()
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

	def _read_page(self, url):
		cached = self._cache().read_page(url)
		if cached:
			log(__name__, "Cached page %s" % url)
			return cached

		status, final, headers, body = self.session.request(url)
		if status != 200:
			log(__name__, "HTTP %s for %s" % (status, url))
			return None
		page = body.decode("utf-8", "replace")
		self._cache().write_page(url, final, page)
		return final, page

	def download(self, link, name=None):
		self._cache().purge()
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

	def _result_item(self, filename, link, language_name):
		return {
			"filename": filename,
			"link": link,
			"lang": LANG_FLAGS.get(language_name, language_name),
			"rating": "0",
			"sync": False,
			"lang_flag": self._language_flag(language_name),
		}

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

		if item.get("refine"):
			chosen = self._choose_shorter_title(title, force=True)
			if not chosen:
				return self._restore_last_results(title, item)
			mode = self._choose_search_mode()
			if not mode:
				return self._restore_last_results(title, item)
			title = chosen
			result_subtitles = self._results_for_mode(title, item, mode)
			if result_subtitles is _SEARCH_ABORT:
				return self._restore_last_results(title, item)
			self._save_last_results(result_subtitles)
			log(__name__, ["Search result", 0 if not result_subtitles else len(result_subtitles)])
			return results_with_stats(result_subtitles or None, self.addon, title, item)

		result_subtitles = self._results_for_title(title, item)
		if not result_subtitles:
			chosen = self._choose_shorter_title(title)
			if chosen:
				title = chosen
				result_subtitles = self._results_for_title(title, item)

		self._save_last_results(result_subtitles)
		log(__name__, ["Search result", 0 if not result_subtitles else len(result_subtitles)])
		return results_with_stats(result_subtitles or None, self.addon, title, item)

	def _last_results_path(self):
		return os.path.join(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")), "last-results.json")

	def _save_last_results(self, results):
		try:
			with open(self._last_results_path(), "w", encoding="utf-8") as handle:
				json.dump(results or [], handle)
		except OSError:
			pass

	def _load_last_results(self):
		try:
			with open(self._last_results_path(), "r", encoding="utf-8") as handle:
				results = json.load(handle)
		except (OSError, ValueError):
			return None
		return results if isinstance(results, list) else None

	def _restore_last_results(self, title, item):
		previous = self._load_last_results()
		if previous is not None:
			log(__name__, ["Search result", len(previous)])
			return results_with_stats(previous or None, self.addon, title, item)
		log(__name__, ["Search result", 0])
		return results_with_stats(None, self.addon, title, item)

	def _choose_search_mode(self):
		options = [
			self._label(32961, "Series search"),
			self._label(32962, "Fulltext search"),
		]
		selected = xbmcgui.Dialog().select(self._label(32963, "Search using"), options)
		if selected < 0:
			return None
		return "series" if selected == 0 else "fulltext"

	def _results_for_mode(self, title, item, mode):
		season = str(item.get("season") or "").strip()
		episode = str(item.get("episode") or "").strip()
		if mode == "series":
			return self._episode_results(title, item.get("year"), season, episode, choose_season=True)
		if season and episode:
			return self._fulltext_episode_results(title, season, episode)
		return self._fulltext_title_results(title)

	def _label(self, string_id, fallback):
		text = self._t(string_id)
		return text or fallback

	def _season_label(self, number):
		template = self._t(32964)
		if "%s" not in (template or ""):
			template = "Season %s"
		return template % number

	def _title_words(self, title):
		return [word for word in re.split(r"[\s._+\-]+", title or "") if word]

	def _choose_shorter_title(self, title, force=False):
		words = self._title_words(title)
		if len(words) < 2 and not force:
			return None
		if not words:
			words = [title.strip()] if (title or "").strip() else []
		options = [" ".join(words[:count]) for count in range(1, len(words) + 1)]
		custom_label = self._label(32948, "...Custom search...")
		options.append(custom_label)
		selected = xbmcgui.Dialog().select(self._label(32947, "Select search title"), options)
		if selected < 0:
			return None
		if selected == len(options) - 1:
			typed = xbmcgui.Dialog().input(self._label(32948, "...Custom search..."), title)
			typed = (typed or "").strip()
			if not typed:
				return None
			return typed
		return options[selected]

	def _results_for_title(self, title, item):
		season = str(item.get("season") or "").strip()
		episode = str(item.get("episode") or "").strip()
		if not season and not episode:
			return self._movie_results(title)
		return self._episode_results(title, item.get("year"), season, episode)

	def _selected_languages(self):
		selected = []
		if self._setting_enabled("search_czech"):
			selected.append("Czech")
		if self._setting_enabled("search_slovak"):
			selected.append("Slovak")
		return selected

	def _episode_results(self, show, year, season, episode, choose_season=False):
		query = show.strip()
		year_text = str(year or "").strip()
		if re.fullmatch(r"\d{4}", year_text) and not choose_season:
			query = "%s (%s)" % (query, year_text)
		has_episode = str(season).strip().isdigit() and str(episode).strip().isdigit()
		url = titulky_query_url("serial", query)
		log(__name__, "Titulky.com series search %s" % url)
		opened = self._read_page(url)
		if not opened:
			return self._series_miss(show, season, episode, has_episode, choose_season)
		page_url, page = opened
		if titulky_series_not_found(page):
			suggestions = titulky_series_suggestions(page)
			if not suggestions:
				return self._series_miss(show, season, episode, has_episode, choose_season)
			chosen = self._choose_series_suggestion(suggestions, show, year_text)
			if not chosen:
				return _SEARCH_ABORT if choose_season else []
			opened = self._read_page(chosen)
			if not opened:
				return []
			page_url, page = opened
		elif not titulky_is_series_page(page):
			return self._series_miss(show, season, episode, has_episode, choose_season)

		opened_season = False
		if choose_season:
			picked = self._pick_season(page, page_url, season)
			if picked is _SEARCH_ABORT:
				return _SEARCH_ABORT
			if picked:
				opened_season = True
				log(__name__, "Titulky.com season page %s" % picked["url"])
				opened = self._read_page(picked["url"])
				if not opened:
					return []
				page_url, page = opened
				season = str(picked["season"])

		if has_episode:
			rips = titulky_episode_rips(page, season, episode)
			if not rips and not opened_season:
				season_url = titulky_season_page_url(page, page_url, season)
				if season_url:
					log(__name__, "Titulky.com season page %s" % season_url)
					opened = self._read_page(season_url)
					if opened:
						page_url, page = opened
						rips = titulky_episode_rips(page, season, episode)
			if rips:
				code = "S%02dE%02d" % (int(season), int(episode))
				return self._rip_results(rips, page_url, code)
			if choose_season:
				page_rips = titulky_page_rips(page)
				if page_rips:
					return self._rip_results(page_rips, page_url)
			return self._fulltext_episode_results(show, season, episode)
		return self._rip_results(titulky_page_rips(page), page_url)

	def _series_miss(self, show, season, episode, has_episode, choose_season):
		if choose_season or not has_episode:
			return []
		return self._fulltext_episode_results(show, season, episode)

	def _pick_season(self, page, page_url, season):
		seasons = titulky_season_links(page, page_url)
		if len(seasons) < 2:
			return None
		labels = [self._season_label(item["season"]) for item in seasons]
		preselect = 0
		try:
			wanted = int(season)
		except (TypeError, ValueError):
			wanted = None
		if wanted is not None:
			for index, item in enumerate(seasons):
				if item["season"] == wanted:
					preselect = index
					break
		selected = xbmcgui.Dialog().select(self._label(32965, "Select season"), labels, 0, preselect)
		if selected < 0:
			return _SEARCH_ABORT
		return seasons[selected]

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

	def _fulltext_episode_results(self, show, season, episode):
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

	def _fulltext_title_results(self, title):
		title = titulky_fulltext_query(title)
		url = titulky_query_url("Fulltext", title.strip())
		log(__name__, "Titulky.com fulltext %s" % url)
		opened = self._read_page(url)
		if not opened:
			return []
		page_url, page = opened
		rips = []
		for row in titulky_fulltext_results(page):
			if not titulky_title_matches(title, row["title"]):
				continue
			rips.append({
				"release": row["release"] or row["title"],
				"link": row["link"],
				"lang": row["lang"],
				"episode": row.get("episode") or "",
			})
		return self._rip_results(rips, page_url)

	def _movie_results(self, title):
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
			label = self._rip_label(rip["release"] or link, rip.get("episode") or episode_code)
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
