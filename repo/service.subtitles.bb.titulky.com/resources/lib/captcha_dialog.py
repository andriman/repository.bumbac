# -*- coding: utf-8 -*-
import xbmc
import xbmcgui


class CaptchaDialog(xbmcgui.WindowXMLDialog):
	def __init__(self, *args, **kwargs):
		self.image_path = kwargs.get("image_path", "")
		self.heading = kwargs.get("heading", "")
		self.code = None
		self._ready = False

	def onInit(self):
		if self._ready:
			return
		self._ready = True
		self.getControl(100).setLabel(self.heading)
		self.getControl(101).setImage(self.image_path.replace("\\", "/"))
		keyboard = xbmc.Keyboard("", self.heading)
		keyboard.doModal()
		if keyboard.isConfirmed():
			self.code = keyboard.getText()
		self.close()
