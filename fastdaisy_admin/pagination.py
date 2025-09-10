from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from starlette.datastructures import URL


@dataclass
class PageControl:
    number: int
    url: str
    has_ellipsis:bool=False #"..."


@dataclass
class Pagination:
    rows: list[Any]
    page: int
    per_page: int
    count: int
    page_controls: list[PageControl] = field(default_factory=list)
    max_page_controls: int = 7

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        next_page = (self.page + 1) * self.per_page
        return next_page <= self.count or next_page - self.count < self.per_page

    @property
    def previous_page(self) -> PageControl:
        for page_control in self.page_controls:
            if page_control.number == self.page - 1:
                return page_control

        raise RuntimeError("Previous page not found.")

    @property
    def next_page(self) -> PageControl:
        for page_control in self.page_controls:
            if page_control.number == self.page + 1:
                return page_control

        raise RuntimeError("Next page not found.")

    def __post_init__(self) -> None:
        # Clamp page
        self.page = min(self.page, max(1, self.count // self.per_page + 1))
        self.total_pages = (self.count + self.per_page - 1) // self.per_page

    def resize(self, per_page: int) -> Pagination:
        self.page = (self.page - 1) * self.per_page // per_page + 1
        self.per_page = per_page
        return self

    def add_pagination_urls(self, base_url: URL) -> None:
        # upto seven
        if self.total_pages <=self.max_page_controls:
            for p in range(1,self.total_pages+1):
                url = str(base_url.include_query_params(page=p))
                page_control = PageControl(number=p, url=url)
                self.page_controls.append(page_control)
        else:
            first_range = range(1,6)
            last_range = range(self.total_pages,self.total_pages-4,-1)
            # first page
            self._add_page_control(base_url, 1)
            # last page
            self._add_page_control(base_url,self.total_pages)
            if self.page in first_range[:-1]:
                for p in first_range[1:]:
                    self._add_page_control(base_url,p)
                self._add_page_control(base_url,p+2,has_ellipsis=True)
            elif self.page in last_range:
                for p in last_range[1:]:
                    self._add_page_control(base_url,p)
                self._add_page_control(base_url,p-1)
                self._add_page_control(base_url,p-2,has_ellipsis=True)
            else:
                self._add_page_control(base_url,self.page-2,has_ellipsis=True)
                for p in range(self.page-1,self.page+2):
                    self._add_page_control(base_url,p)
                self._add_page_control(base_url,p+1,has_ellipsis=True)

        self.page_controls.sort(key=lambda p: p.number)

    def _add_page_control(self, base_url: URL, page: int,has_ellipsis=False) -> None:
        url = str(base_url.include_query_params(page=page))
        page_control = PageControl(number=page, url=url,has_ellipsis=has_ellipsis)
        self.page_controls.append(page_control)

