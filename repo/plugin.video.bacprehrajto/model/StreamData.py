from typing import Optional, Dict


class StreamData(object):
    label: str
    label2: str
    quality: int # height
    path: str
    headers: Optional[Dict[str, str]]
    is_premium: bool
    upload_date: Optional[str]

    def __init__(self, label, label2='', quality = 0, path = '', headers: Optional[Dict[str, str]] = None, is_premium=False,
                 upload_date: Optional[str] = None):
        self.label = label
        self.label2 = label2
        self.quality = quality
        self.path = path
        self.headers = headers
        self.is_premium = is_premium
        self.upload_date = upload_date
