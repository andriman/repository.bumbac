from dataclasses import dataclass


@dataclass
class SearchMeta:
    pages_scraped: int = 0
    cancelled: bool = False
    is_complete: bool = False
