import pytest

from confiance.search.base import http_fetch


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/api/setup/config", "http://localhost/", "http://169.254.169.254/", "file:///etc/passwd", "http://10.0.0.1/"])
def test_private_and_non_http_urls_are_refused(url):
    with pytest.raises(ValueError):
        http_fetch(url)
