import pytest
from starlette.datastructures import URL

from fastdaisy_admin.pagination import PageControl, Pagination

BASE_URL = URL("http://testserver/users/list")


def test_single_page() -> None:
    pagination = Pagination(rows=[], page=1, per_page=5, count=5)
    pagination.add_pagination_urls(BASE_URL)

    assert pagination.has_previous is False
    assert pagination.has_next is False
    with pytest.raises(RuntimeError):
        pagination.next_page
    with pytest.raises(RuntimeError):
        pagination.previous_page


def test_multi_page_first_page() -> None:
    pagination = Pagination(rows=[], page=1, per_page=5, count=15)
    pagination.add_pagination_urls(BASE_URL)

    assert pagination.has_previous is False
    assert pagination.has_next is True
    assert pagination.next_page.url == "http://testserver/users/list?page=2"
    with pytest.raises(RuntimeError):
        pagination.previous_page


def test_multi_page_last_page() -> None:
    pagination = Pagination(rows=[], page=4, per_page=5, count=18)
    pagination.add_pagination_urls(BASE_URL)

    page_control = PageControl(number=4, url="http://testserver/users/list?page=4")
    assert page_control in pagination.page_controls
    assert pagination.has_previous is True
    with pytest.raises(RuntimeError):
        pagination.next_page


def test_has_ellipse_and_on_currentpage() -> None:
    page = 2
    pagination = Pagination(rows=[], page=page, per_page=5, count=50)
    pagination.add_pagination_urls(BASE_URL)

    assert pagination.page_controls[pagination.max_page_controls-2].has_ellipsis is True
    # on current page
    assert pagination.page_controls[page-1].url ==  f"http://testserver/users/list?page={page}"

def test_multi_pages() -> None:
    per_page = 5
    current_page = 2
    count = 50
    total_page = count//per_page
    pagination = Pagination(rows=[], page=current_page, per_page=per_page, count=count)
    pagination.add_pagination_urls(BASE_URL)

    page_controls = [
        PageControl(number=i, url=f"http://testserver/users/list?page={i}")
        for i in range(1, 6)
    ]
    p_max = pagination.max_page_controls
    page_controls.append(PageControl(number=p_max, url=f"http://testserver/users/list?page={p_max}",has_ellipsis=True))
    page_controls.append(PageControl(number=total_page, url=f"http://testserver/users/list?page={total_page}"))

    assert pagination.page_controls == page_controls
