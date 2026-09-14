"""Proofs for the read-only GitHub API transport bound to api.github.com."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from blackbread.governance.github_merge_transport import (
    GitHubReadTransport,
    TransportError,
    TransportResult,
    UrllibGitHubReadTransport,
)

DUMMY_AUTH = "unit-test-dummy-auth-value"
MAX_BODY = 8 * 1024 * 1024


class _FakeResponse:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"{}",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = dict(headers or {})

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._body
        return self._body[:amount]

    def close(self) -> None:
        pass


class _OpenerSpy:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.requests: list[urllib.request.Request] = []
        self._response = response if response is not None else _FakeResponse()
        self._error = error

    def __call__(self, request: urllib.request.Request, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._response


def _transport(spy: _OpenerSpy) -> UrllibGitHubReadTransport:
    return UrllibGitHubReadTransport(DUMMY_AUTH, opener=spy)


def test_rest_get_sends_exact_read_headers_and_get_method() -> None:
    spy = _OpenerSpy()
    result = _transport(spy).rest_get("/repos/o/r/pulls")
    request = spy.requests[0]
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.full_url == "https://api.github.com/repos/o/r/pulls"
    assert request.get_header("Authorization") == f"Bearer {DUMMY_AUTH}"
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("X-github-api-version") == "2022-11-28"
    assert request.get_header("User-agent") is not None
    assert "python" not in str(request.get_header("User-agent")).lower()
    assert result.status == 200
    assert result.body == {}
    assert result.next_url is None


def test_rest_get_appends_query_params() -> None:
    spy = _OpenerSpy()
    _transport(spy).rest_get("/x", params={"a": "1", "b": "two words"})
    assert spy.requests[0].full_url == "https://api.github.com/x?a=1&b=two+words"


def test_rest_get_accepts_exact_origin_absolute_url() -> None:
    spy = _OpenerSpy()
    _transport(spy).rest_get("https://api.github.com/repos/o/r")
    assert spy.requests[0].full_url == "https://api.github.com/repos/o/r"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/repos/o/r",
        "http://api.github.com/repos/o/r",
        "https://api.github.com:8443/repos/o/r",
        "https://api.github.com:443/repos/o/r",
        "https://user:pw@api.github.com/repos/o/r",
        "https://api.github.com@evil.example.com/x",
        "//evil.example.com/x",
        "https://api.github.com/x#frag",
        "api.github.com/x",
        "x/no-leading-slash",
        "",
        "   ",
    ],
)
def test_rest_get_rejects_hostile_or_malformed_urls(url: str) -> None:
    spy = _OpenerSpy()
    with pytest.raises(TransportError):
        _transport(spy).rest_get(url)
    assert spy.requests == []


def test_graphql_query_posts_explicit_query_to_fixed_endpoint() -> None:
    body = json.dumps({"data": {"viewer": {"login": "octo"}}}).encode()
    spy = _OpenerSpy(_FakeResponse(body=body))
    document = "query Viewer { viewer { login } }"
    result = _transport(spy).graphql_query(document, variables={"n": 1})
    request = spy.requests[0]
    assert request.get_method() == "POST"
    assert request.full_url == "https://api.github.com/graphql"
    assert json.loads(request.data.decode("utf-8")) == {
        "query": document,
        "variables": {"n": 1},
    }
    assert request.get_header("Authorization") == f"Bearer {DUMMY_AUTH}"
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("X-github-api-version") == "2022-11-28"
    assert request.get_header("Content-type") == "application/json"
    assert result.body == {"data": {"viewer": {"login": "octo"}}}


def test_graphql_query_omits_variables_when_absent() -> None:
    spy = _OpenerSpy()
    _transport(spy).graphql_query("query { viewer { login } }")
    payload = json.loads(spy.requests[0].data.decode("utf-8"))
    assert "variables" not in payload


@pytest.mark.parametrize(
    "document",
    [
        "query { viewer { login } }",
        "query GetPr($n: Int!) { pullRequest(number: $n) { title } }",
        "query { a } fragment F on User { login }",
        'query { f(arg: "mutation { x }") }',
        'query { f(arg: "a#b") }',
        "query { mutation }",
        "query A { a } query B { b }",
    ],
)
def test_graphql_accepts_explicit_query_documents(document: str) -> None:
    spy = _OpenerSpy()
    _transport(spy).graphql_query(document)
    assert len(spy.requests) == 1


@pytest.mark.parametrize(
    "document",
    [
        "",
        "   ",
        "{ viewer { login } }",
        "mutation { x }",
        "subscription { x }",
        "mutation M { x } query Q { y }",
        "query { a } mutation { b }",
        "query { a } subscription { b }",
        "schema { query: Q }",
        "query Unbalanced { x ",
        "query Headless",
        "fragment F on User { login }",
        "# mutation in a comment\nquery { x }",
        "query { a } # tail\rmutation { b }",
        "query { a }\r\n",
        'query { f(arg: """triple""") }',
        "query { a } # comment only",
    ],
)
def test_graphql_rejects_documents_without_network(document: str) -> None:
    spy = _OpenerSpy()
    with pytest.raises(TransportError):
        _transport(spy).graphql_query(document)
    assert spy.requests == []


def test_graphql_errors_body_remains_transport_data() -> None:
    body = json.dumps({"errors": [{"message": "boom"}]}).encode()
    spy = _OpenerSpy(_FakeResponse(body=body))
    result = _transport(spy).graphql_query("query { x }")
    assert result.body == {"errors": [{"message": "boom"}]}


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_responses_are_rejected(status: int) -> None:
    response = _FakeResponse(status=status, headers={"Location": "https://api.github.com/x"})
    spy = _OpenerSpy(response)
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status == status


def test_redirect_raised_by_opener_is_rejected() -> None:
    error = urllib.error.HTTPError("https://api.github.com/x", 302, "Found", {}, None)
    spy = _OpenerSpy(error=error)
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status == 302


def test_http_error_is_sanitized_and_carries_status() -> None:
    error = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)
    spy = _OpenerSpy(error=error)
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status == 404
    assert DUMMY_AUTH not in str(excinfo.value)
    assert DUMMY_AUTH not in repr(excinfo.value)


def test_non_success_status_is_error() -> None:
    spy = _OpenerSpy(_FakeResponse(status=500))
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status == 500


def test_network_failure_is_sanitized() -> None:
    spy = _OpenerSpy(error=urllib.error.URLError(f"refused for {DUMMY_AUTH}"))
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status is None
    assert DUMMY_AUTH not in str(excinfo.value)
    assert DUMMY_AUTH not in repr(excinfo.value)


def test_oserror_is_sanitized() -> None:
    spy = _OpenerSpy(error=OSError(f"socket died {DUMMY_AUTH}"))
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert DUMMY_AUTH not in str(excinfo.value)


def test_malformed_json_rejected() -> None:
    spy = _OpenerSpy(_FakeResponse(body=b"{not json"))
    with pytest.raises(TransportError):
        _transport(spy).rest_get("/x")


def test_empty_body_rejected() -> None:
    spy = _OpenerSpy(_FakeResponse(body=b""))
    with pytest.raises(TransportError):
        _transport(spy).rest_get("/x")


def test_oversized_body_rejected() -> None:
    spy = _OpenerSpy(_FakeResponse(body=b" " * (MAX_BODY + 1)))
    with pytest.raises(TransportError):
        _transport(spy).rest_get("/x")


def test_body_at_bound_accepted() -> None:
    body = b'"' + b"a" * (MAX_BODY - 2) + b'"'
    spy = _OpenerSpy(_FakeResponse(body=body))
    result = _transport(spy).rest_get("/x")
    assert result.body == "a" * (MAX_BODY - 2)


def test_safe_next_link_is_returned() -> None:
    headers = {
        "Link": (
            '<https://api.github.com/x?page=2>; rel="next", '
            '<https://api.github.com/x?page=9>; rel="last"'
        )
    }
    spy = _OpenerSpy(_FakeResponse(body=b"[]", headers=headers))
    result = _transport(spy).rest_get("/x")
    assert result.next_url == "https://api.github.com/x?page=2"


@pytest.mark.parametrize(
    "link",
    [
        '<https://evil.example.com/x>; rel="next"',
        '<http://api.github.com/x>; rel="next"',
        '<https://api.github.com:8443/x>; rel="next"',
        '<https://u:p@api.github.com/x>; rel="next"',
        '<https://api.github.com/x#frag>; rel="next"',
    ],
)
def test_hostile_next_link_is_rejected(link: str) -> None:
    spy = _OpenerSpy(_FakeResponse(body=b"[]", headers={"Link": link}))
    with pytest.raises(TransportError):
        _transport(spy).rest_get("/x")


def test_next_url_result_is_accepted_as_input() -> None:
    headers = {"Link": '<https://api.github.com/x?page=2>; rel="next"'}
    first = _OpenerSpy(_FakeResponse(body=b"[]", headers=headers))
    result = _transport(first).rest_get("/x")
    second = _OpenerSpy(_FakeResponse(body=b"[]"))
    assert result.next_url is not None
    _transport(second).rest_get(result.next_url)
    assert second.requests[0].full_url == result.next_url


@pytest.mark.parametrize("token", ["", "   "])
def test_blank_token_rejected(token: str) -> None:
    with pytest.raises(TransportError):
        UrllibGitHubReadTransport(token, opener=_OpenerSpy())


def test_token_absent_from_all_outputs(capsys: pytest.CaptureFixture[str]) -> None:
    transport = _transport(_OpenerSpy(error=OSError(f"leak {DUMMY_AUTH}")))
    assert DUMMY_AUTH not in repr(transport)
    with pytest.raises(TransportError) as excinfo:
        transport.rest_get("/x")
    assert DUMMY_AUTH not in str(excinfo.value)
    assert DUMMY_AUTH not in repr(excinfo.value)
    with pytest.raises(TransportError):
        transport.graphql_query("mutation { x }")
    captured = capsys.readouterr()
    assert DUMMY_AUTH not in captured.out
    assert DUMMY_AUTH not in captured.err


def test_no_generic_http_surface() -> None:
    transport: Any = _transport(_OpenerSpy())
    for name in ("request", "post", "put", "patch", "delete", "head", "options"):
        assert not hasattr(transport, name)


def test_urllib_transport_satisfies_protocol() -> None:
    transport: GitHubReadTransport = _transport(_OpenerSpy())
    result = transport.rest_get("/x")
    assert isinstance(result, TransportResult)


@pytest.mark.parametrize(
    "error",
    [
        http.client.IncompleteRead(b"partial"),
        http.client.BadStatusLine("garbage"),
        http.client.RemoteDisconnected("gone"),
    ],
)
def test_http_protocol_failures_are_sanitized(error: Exception) -> None:
    spy = _OpenerSpy(error=error)
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status is None
    assert DUMMY_AUTH not in str(excinfo.value)


class _ClosableFp:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_http_error_response_is_closed() -> None:
    fp = _ClosableFp()
    error = urllib.error.HTTPError("https://api.github.com/x", 500, "err", {}, fp)
    spy = _OpenerSpy(error=error)
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status == 500
    assert fp.closed


def test_http_error_without_fp_is_safe() -> None:
    error = urllib.error.HTTPError("https://api.github.com/x", 503, "err", {}, None)
    spy = _OpenerSpy(error=error)
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status == 503


def test_http_error_close_failure_keeps_sanitized_error() -> None:
    class _BadClose:
        def __init__(self) -> None:
            self.calls = 0

        def close(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("close broke")

    error = urllib.error.HTTPError("https://api.github.com/x", 503, "err", {}, _BadClose())
    spy = _OpenerSpy(error=error)
    with pytest.raises(TransportError) as excinfo:
        _transport(spy).rest_get("/x")
    assert excinfo.value.status == 503
    assert "close broke" not in str(excinfo.value)


@pytest.mark.parametrize(
    "token",
    ["abc\r\ndef", "abc\ndef", "abc def", "abc\txyz", "tökën"],
)
def test_control_bearing_token_rejected(token: str) -> None:
    spy = _OpenerSpy()
    with pytest.raises(TransportError) as excinfo:
        UrllibGitHubReadTransport(token, opener=spy)
    assert token not in str(excinfo.value)
    assert spy.requests == []


@pytest.mark.parametrize(
    "link",
    [
        "not-a-link",
        "<https://api.github.com/x",
        "https://api.github.com/x; rel=next",
        '<https://api.github.com/x>; rel="next"; ',
        '<https://api.github.com/x>; rel="next", garbage',
        "<https://api.github.com/x>; rel=",
        "",
        '<https://api.github.com/x>; rel="next", <https://api.github.com/y>; rel="next"',
    ],
)
def test_malformed_or_duplicate_link_header_rejected(link: str) -> None:
    spy = _OpenerSpy(_FakeResponse(body=b"[]", headers={"Link": link}))
    with pytest.raises(TransportError):
        _transport(spy).rest_get("/x")


def test_terminal_page_without_next_link_still_accepted() -> None:
    headers = {"Link": '<https://api.github.com/x?page=9>; rel="last"'}
    spy = _OpenerSpy(_FakeResponse(body=b"[]", headers=headers))
    result = _transport(spy).rest_get("/x")
    assert result.next_url is None
