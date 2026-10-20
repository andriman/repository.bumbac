# -*- coding: utf-8 -*-
import http.cookiejar
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from edna_parse import content_disposition_filename, edna_direct_download_url, is_html_payload, is_titulky_captcha, titulky_captcha_form, titulky_download_delay, titulky_file_url, titulky_zip_url

BASE_URL = "https://www.edna.cz"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
MAX_SUBTITLE_BYTES = 5 * 1024 * 1024
ANTISPAM_MIN_DELAY = 5
CAPTCHA_ATTEMPTS = 5


def _form_created_timestamp(value):
	"""Edna encodes time() by translating digits 0123456789 -> jihgfedcba."""
	try:
		return int(value.translate(str.maketrans("jihgfedcba", "0123456789")))
	except ValueError:
		return None


def _wait_for_form_delay(form_created):
	created = _form_created_timestamp(form_created or "")
	remaining = ANTISPAM_MIN_DELAY + 1
	if created is not None:
		remaining = max(remaining, created + ANTISPAM_MIN_DELAY + 1 - time.time())
	time.sleep(min(remaining, 15))


class LoginFormParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.in_form = False
		self.action = None
		self.inputs = {}

	def handle_starttag(self, tag, attrs):
		attributes = dict(attrs)
		if tag == "form" and attributes.get("id") == "frm-loginForm":
			self.in_form = True
			self.action = attributes.get("action")
		elif self.in_form and tag == "input" and attributes.get("name"):
			self.inputs[attributes["name"]] = attributes.get("value", "")

	def handle_endtag(self, tag):
		if tag == "form" and self.in_form:
			self.in_form = False


class EdnaSession(object):
	def __init__(self, cookie_path=None):
		self.cookie_path = cookie_path
		self.marker_path = (cookie_path + ".ok") if cookie_path else None
		if cookie_path:
			self.jar = http.cookiejar.LWPCookieJar(cookie_path)
			if os.path.exists(cookie_path):
				try:
					self.jar.load(ignore_discard=True, ignore_expires=True)
				except Exception:
					pass
		else:
			self.jar = http.cookiejar.CookieJar()
		self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
		self.opener.addheaders = [("User-Agent", USER_AGENT)]
		self.last_error = None
		self.notify = None
		self.prompt_captcha = None
		self.wait_seconds = None

	def save(self):
		if self.cookie_path and isinstance(self.jar, http.cookiejar.LWPCookieJar):
			parent = os.path.dirname(self.cookie_path)
			if parent and not os.path.isdir(parent):
				os.makedirs(parent)
			self.jar.save(ignore_discard=True, ignore_expires=True)

	def mark_logged_in(self):
		self.save()
		if self.marker_path:
			parent = os.path.dirname(self.marker_path)
			if parent and not os.path.isdir(parent):
				os.makedirs(parent)
			with open(self.marker_path, "w", encoding="utf-8") as handle:
				handle.write("ok")

	def clear_login_marker(self):
		if self.marker_path and os.path.exists(self.marker_path):
			try:
				os.remove(self.marker_path)
			except OSError:
				pass

	def has_login_marker(self):
		return bool(self.marker_path and os.path.exists(self.marker_path))

	def request(self, url, data=None, referer=None, ajax=False):
		headers = {}
		if referer:
			headers["Referer"] = referer
		if ajax:
			headers["X-Requested-With"] = "XMLHttpRequest"
		req = urllib.request.Request(url, data=data, headers=headers)
		try:
			res = self.opener.open(req, timeout=30)
			body = res.read(MAX_SUBTITLE_BYTES + 1)
			return res.status, res.geturl(), res.headers, body
		except urllib.error.HTTPError as error:
			body = error.read(MAX_SUBTITLE_BYTES + 1)
			final = error.geturl() if hasattr(error, "geturl") else url
			return error.code, final, error.headers, body
		except urllib.error.URLError as error:
			log_safe = getattr(error, "reason", error)
			return 0, url, {}, str(log_safe).encode("utf-8", "replace")

	def login(self, username, password):
		if not username or not password:
			return False

		status, final, headers, body = self.request(BASE_URL + "/uzivatel/prihlaseni/")
		page = body.decode("utf-8", "replace")
		parser = LoginFormParser()
		parser.feed(page)
		if not parser.action or "_token_" not in parser.inputs:
			return False

		fields = dict(parser.inputs)
		fields["nick"] = username
		fields["password"] = password
		fields["spam"] = ""
		fields["keep"] = "on"
		_wait_for_form_delay(fields.get("form_created"))
		payload = urllib.parse.urlencode(fields).encode("utf-8")
		action = urllib.parse.urljoin(BASE_URL + "/uzivatel/prihlaseni/", parser.action)
		status, final, headers, body = self.request(action, data=payload, referer=BASE_URL + "/uzivatel/prihlaseni/")
		page = body.decode("utf-8", "replace")
		if status == 200 and "do=logout" in page:
			self.mark_logged_in()
			return True
		self.clear_login_marker()
		return False

	def is_login_wall(self, status, final, body):
		if status == 401:
			return True
		if final and "/uzivatel/prihlaseni" in final:
			return True
		if body and b"<h1>Redirect</h1>" in body and b"prihlaseni" in body:
			return True
		return False

	def fetch_subtitle(self, url):
		"""Resolve an Edna/titulky link to (filename, bytes)."""
		self.last_error = None
		url = edna_direct_download_url(url)
		if "titulky.com" in url and "idown.php" not in url:
			if self.notify:
				self.notify("titulky")
			status, final, headers, body = self.request(url)
			if is_html_payload(body, _content_type(headers)):
				zip_url = titulky_zip_url(body.decode("utf-8", "replace"), final)
				if not zip_url:
					self.last_error = "failed"
					return None
				status, final, headers, body = self.request(zip_url, referer=url)
			else:
				return _file_from_response(headers, body)
			return self._complete_titulky_download(body, headers, final)

		status, final, headers, body = self.request(url)
		return _file_from_response(headers, body)

	def _complete_titulky_download(self, body, headers, page_url):
		if is_html_payload(body, _content_type(headers)):
			page = body.decode("utf-8", "replace")
			if is_titulky_captcha(page):
				solved = self._submit_captcha(page, page_url)
				if not solved:
					return None
				if solved[0] == "file":
					return solved[1]
				page, page_url = solved[1], solved[2]
			file_url = titulky_file_url(page, page_url)
			if not file_url:
				self.last_error = "failed"
				return None
			if self._wait_for_file(titulky_download_delay(page)):
				self.last_error = "limit"
				return None
			status, final, headers, body = self.request(file_url, referer=page_url)
		return _file_from_response(headers, body)

	def _submit_captcha(self, page_html, page_url):
		if not self.prompt_captcha:
			self.last_error = "limit"
			return None
		wrong = False
		for _attempt in range(CAPTCHA_ATTEMPTS):
			form = titulky_captcha_form(page_html, page_url)
			if not form:
				self.last_error = "failed"
				return None
			post_url, fields, image_url = form
			status, final, headers, image = self.request(image_url, referer=page_url)
			if status != 200 or not _is_image(image, _content_type(headers)):
				self.last_error = "failed"
				return None
			code = self.prompt_captcha(image, "wrong" if wrong else "")
			if code is None or not str(code).strip():
				self.last_error = "limit"
				return None
			payload = urllib.parse.urlencode(fields + [("downkod", str(code).strip())]).encode("utf-8")
			status, final, headers, body = self.request(post_url, data=payload, referer=page_url)
			if not is_html_payload(body, _content_type(headers)):
				return ("file", _file_from_response(headers, body))
			page_html = body.decode("utf-8", "replace")
			page_url = final or post_url
			if titulky_file_url(page_html, page_url) or not is_titulky_captcha(page_html):
				return ("page", page_html, page_url)
			wrong = True
		self.last_error = "limit"
		return None

	def _wait_for_file(self, delay):
		seconds = min(int(delay) + 1, 12) if delay else 0
		if seconds <= 0:
			return False
		if self.wait_seconds:
			return bool(self.wait_seconds(seconds, ""))
		time.sleep(seconds)
		return False


def _content_type(headers):
	if not headers:
		return ""
	return headers.get("Content-Type") or ""


def _is_image(data, content_type):
	if not data or is_html_payload(data, content_type):
		return False
	if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
		return True
	if data[:6] in (b"GIF87a", b"GIF89a") or data[:2] == b"BM":
		return True
	return bool(content_type and content_type.lower().startswith("image/"))


def _file_from_response(headers, body):
	if not body or len(body) > MAX_SUBTITLE_BYTES:
		return None
	content_type = headers.get("Content-Type") if headers else ""
	if is_html_payload(body, content_type):
		return None
	filename = content_disposition_filename(headers.get("Content-Disposition") if headers else None)
	if not filename:
		if body[:2] == b"PK":
			filename = "download.zip"
		elif body[:4] == b"Rar!":
			filename = "download.rar"
		else:
			filename = "download.srt"
	return filename, body
