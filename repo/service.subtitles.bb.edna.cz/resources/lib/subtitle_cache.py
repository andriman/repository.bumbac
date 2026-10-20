# -*- coding: utf-8 -*-
import hashlib
import os
import time


class SubtitleCache(object):
	def __init__(self, root, ttl_seconds):
		self.root = root
		self.ttl_seconds = max(1, int(ttl_seconds))
		self.page_dir = os.path.join(root, "pages")

	def purge(self):
		self._purge_aged(self.root, ".zip", lambda path: path + ".url")
		self._purge_aged(self.page_dir, ".html", lambda path: path[:-5] + ".final")

	def clear_all(self):
		if not os.path.isdir(self.root):
			return
		for dirpath, dirnames, filenames in os.walk(self.root, topdown=False):
			for name in filenames:
				self._remove(os.path.join(dirpath, name))
			if os.path.abspath(dirpath) != os.path.abspath(self.root):
				try:
					os.rmdir(dirpath)
				except OSError:
					pass

	def read_page(self, url):
		html_path = self._page_path(url, ".html")
		final_path = self._page_path(url, ".final")
		if not self._fresh(html_path) or not os.path.isfile(final_path):
			return None
		with open(final_path, "r", encoding="utf-8") as handle:
			final_url = handle.read().strip()
		with open(html_path, "r", encoding="utf-8") as handle:
			return final_url, handle.read()

	def write_page(self, url, final_url, html):
		os.makedirs(self.page_dir, exist_ok=True)
		with open(self._page_path(url, ".html"), "w", encoding="utf-8") as handle:
			handle.write(html)
		with open(self._page_path(url, ".final"), "w", encoding="utf-8") as handle:
			handle.write(final_url)

	def read_zip(self, digest):
		path = self.zip_path(digest)
		if not self._fresh(path):
			return None
		with open(path, "rb") as handle:
			return handle.read()

	def write_zip(self, digest, data, source_url):
		os.makedirs(self.root, exist_ok=True)
		path = self.zip_path(digest)
		with open(path, "wb") as handle:
			handle.write(data)
		with open(path + ".url", "w", encoding="utf-8") as handle:
			handle.write(source_url)

	def zip_path(self, digest):
		return os.path.join(self.root, digest + ".zip")

	def _page_path(self, url, suffix):
		digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
		return os.path.join(self.page_dir, digest + suffix)

	def _fresh(self, path):
		if not os.path.isfile(path):
			return False
		return (time.time() - os.path.getmtime(path)) <= self.ttl_seconds

	def _purge_aged(self, directory, suffix, companion_path):
		if not os.path.isdir(directory):
			return
		now = time.time()
		for name in os.listdir(directory):
			if not name.endswith(suffix):
				continue
			path = os.path.join(directory, name)
			if not os.path.isfile(path):
				continue
			try:
				expired = (now - os.path.getmtime(path)) > self.ttl_seconds
			except OSError:
				continue
			if not expired:
				continue
			self._remove(path)
			self._remove(companion_path(path))

	def _remove(self, path):
		try:
			if os.path.isfile(path):
				os.remove(path)
		except OSError:
			pass
