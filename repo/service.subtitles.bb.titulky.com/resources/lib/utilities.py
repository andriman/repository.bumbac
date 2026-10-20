# -*- coding: utf-8 -*- 

import os
import xbmc, xbmcvfs, xbmcgui
import struct

def log(module, msg):
    xbmc.log((u"### [%s] - %s" % (str(module), str(msg))), level=xbmc.LOGDEBUG)

def select_file_menu(file_list, dialog_title = "Select file"):
    if not file_list or len(file_list) == 1: return file_list

    log(__name__, "More items in file list, creating dialog")

    menu_dialog = []
    for file_path in file_list: menu_dialog.append(os.path.basename(file_path))
    dialog = xbmcgui.Dialog()

    selected_file_id = dialog.select(dialog_title, menu_dialog)
    if (selected_file_id == -1): return file_list

    selected_file_path = [file_list[selected_file_id]]
    log(__name__, "Item selected %s" % selected_file_path)
    return selected_file_path

def extract_subtitles(archive_dir):
    xbmc.executebuiltin('Extract("%s")' % archive_dir)
    
    xbmc.sleep(1000)
    basepath = os.path.dirname(archive_dir)
    extracted_files = os.listdir(basepath)
    exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass" ]
    extracted_subtitles = []
    if len(extracted_files) < 1 :
        return []
    else:
        for extracted_file in extracted_files:
            if os.path.splitext(extracted_file)[1] in exts:
                extracted_subtitles.append(os.path.join(basepath, extracted_file))
    return extracted_subtitles
