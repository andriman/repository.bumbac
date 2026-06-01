from abc import abstractmethod, ABC
from typing import Tuple, Optional, List

import xbmcgui

from model.SearchMeta import SearchMeta
from model.StreamData import StreamData
from model.SubData import SubData


class _Provider(ABC):

    @abstractmethod
    def search(self, query: str) -> Tuple[List[xbmcgui.ListItem], SearchMeta]:
        pass

    @abstractmethod
    def get_streams_data(self, url: str, src_bytes: bytes) -> Tuple[Optional[List[StreamData]], Optional[List[SubData]]]:
        pass

    @abstractmethod
    def get_premium(self):
        pass