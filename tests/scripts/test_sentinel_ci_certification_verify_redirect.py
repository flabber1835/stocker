import urllib.request

from scripts import sentinel_ci_certification_verify as verify


def _redirect(handler, source, destination):
    request = urllib.request.Request(
        source,
        headers={"Authorization": "Bearer secret", "Accept": "application/json"},
        method="GET",
    )
    return handler.redirect_request(
        request,
        fp=None,
        code=302,
        msg="Found",
        headers={},
        newurl=destination,
    )


def test_cross_origin_redirect_drops_authorization():
    redirected = _redirect(
        verify._AuthorizationStrippingRedirect(),
        "https://api.github.com/repos/flabber1835/stocker/actions/artifacts/1/zip",
        "https://productionresultssa0.blob.core.windows.net/actions-results/file.zip?sig=x",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Accept") == "application/json"


def test_same_origin_redirect_keeps_authorization():
    redirected = _redirect(
        verify._AuthorizationStrippingRedirect(),
        "https://api.github.com/repos/flabber1835/stocker/actions/artifacts/1/zip",
        "https://api.github.com/repos/flabber1835/stocker/actions/artifacts/2/zip",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") == "Bearer secret"
