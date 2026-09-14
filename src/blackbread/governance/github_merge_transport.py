"""Read-only GitHub API transport pinned to the exact api.github.com origin.

Fail-closed read transport for governance evidence collection. REST permits
GET only; GraphQL accepts explicit ``query`` documents posted to the fixed
``/graphql`` endpoint. There is no generic HTTP method, redirects are never
followed and Authorization is never forwarded, every pagination ``next`` link
is revalidated against the same origin, each response is bounded to 8 MiB, and
every failure raises a sanitized ``TransportError`` that never carries the
token, a response body, a GraphQL document, or credential material.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

_API_ORIGIN = "https://api.github.com"
_API_HOST = "api.github.com"
_API_VERSION = "2022-11-28"
_GRAPHQL_URL = f"{_API_ORIGIN}/graphql"
_MAX_BODY_BYTES = 8 * 1024 * 1024
_SUCCESS_MIN = 200
_REDIRECT_MIN = 300
_REDIRECT_MAX = 400
_USER_AGENT = "blackbread-governance-read/1"
_DEFINITION_KEYWORDS = frozenset({"query", "fragment"})
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[{}()]")
_LINK_SEGMENT_RE = re.compile(
    r"<(?P<url>[^<>]+)>(?P<params>(?:\s*;\s*[^\s;,=]+(?:\s*=\s*(?:\"[^\"]*\"|[^\s;,]+))?)*)"
)
_REL_RE = re.compile(r'rel\s*=\s*(?:"([^"]*)"|([^\s;,]+))', re.IGNORECASE)
_VISIBLE_ASCII_RE = re.compile(r"[\x21-\x7e]+")

Opener = Callable[[urllib.request.Request, float], Any]


class TransportError(Exception):
    """Sanitized transport failure.

    Carries a fixed message and at most an HTTP status code. It never embeds
    the token, a response body, a GraphQL document, or credential material.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class TransportResult:
    status: int
    body: Any
    next_url: str | None


class GitHubReadTransport(Protocol):
    """Read-only surface exposed to the evidence collector."""

    def rest_get(
        self, path_or_url: str, params: Mapping[str, str] | None = None
    ) -> TransportResult: ...

    def graphql_query(
        self, document: str, variables: Mapping[str, Any] | None = None
    ) -> TransportResult: ...


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Disable redirect following so Authorization can never be forwarded."""

    # Signature fixed by urllib.request.HTTPRedirectHandler; returning None
    # makes urllib raise the redirect as an HTTPError instead of following it.
    def redirect_request(  # noqa: PLR0913, PLR0917
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


def _build_opener() -> Opener:
    director = urllib.request.build_opener(_RejectRedirects())

    def _open(request: urllib.request.Request, timeout: float) -> Any:
        return director.open(request, timeout=timeout)

    return _open


class UrllibGitHubReadTransport:
    """Standard-library implementation of the read-only transport contract."""

    def __init__(
        self,
        token: str,
        *,
        opener: Opener | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise TransportError("blank token")
        if _VISIBLE_ASCII_RE.fullmatch(token) is None:
            raise TransportError("invalid token characters")
        if timeout <= 0:
            raise TransportError("non-positive timeout")
        self._authorization = f"Bearer {token}"
        self._timeout = timeout
        self._opener = opener if opener is not None else _build_opener()

    def rest_get(
        self, path_or_url: str, params: Mapping[str, str] | None = None
    ) -> TransportResult:
        url = _resolve_rest_url(path_or_url, params)
        request = urllib.request.Request(url, method="GET")  # noqa: S310
        self._attach_headers(request)
        return self._send(request)

    def graphql_query(
        self, document: str, variables: Mapping[str, Any] | None = None
    ) -> TransportResult:
        _validate_query_document(document)
        payload: dict[str, Any] = {"query": document}
        if variables is not None:
            payload["variables"] = dict(variables)
        try:
            body = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError):
            raise TransportError("payload not JSON-serializable") from None
        request = urllib.request.Request(_GRAPHQL_URL, data=body, method="POST")  # noqa: S310
        request.add_header("Content-Type", "application/json")
        self._attach_headers(request)
        return self._send(request)

    def _attach_headers(self, request: urllib.request.Request) -> None:
        request.add_header("Authorization", self._authorization)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", _API_VERSION)
        request.add_header("User-Agent", _USER_AGENT)

    def _send(self, request: urllib.request.Request) -> TransportResult:
        try:
            with contextlib.closing(self._opener(request, self._timeout)) as response:
                status = getattr(response, "status", None)
                if not isinstance(status, int) or not _SUCCESS_MIN <= status < _REDIRECT_MIN:
                    raise TransportError(
                        _status_message(status), status=status if isinstance(status, int) else None
                    )
                raw = response.read(_MAX_BODY_BYTES + 1)
                link = _header_get(response, "Link")
        except TransportError:
            raise
        except urllib.error.HTTPError as exc:
            code = exc.code if isinstance(exc.code, int) else None
            fp = getattr(exc, "fp", None)
            if fp is not None:
                with contextlib.suppress(Exception):
                    fp.close()
            raise TransportError(_status_message(code), status=code) from None
        except (OSError, http.client.HTTPException, ValueError):
            raise TransportError("network request failed") from None
        if len(raw) > _MAX_BODY_BYTES:
            raise TransportError("response exceeds byte bound")
        if not raw:
            raise TransportError("empty response body")
        try:
            body = json.loads(raw)
        except ValueError:
            raise TransportError("malformed JSON body") from None
        next_url = _validated_next_url(link)
        return TransportResult(status=status, body=body, next_url=next_url)


def _status_message(status: Any) -> str:
    if isinstance(status, int) and _REDIRECT_MIN <= status < _REDIRECT_MAX:
        return "redirect rejected"
    return "unexpected HTTP status"


def _header_get(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return value if isinstance(value, str) else None


def _resolve_rest_url(path_or_url: str, params: Mapping[str, str] | None) -> str:
    if not isinstance(path_or_url, str) or not path_or_url.strip():
        raise TransportError("empty API path")
    candidate = path_or_url.strip()
    parsed = _split(candidate)
    if parsed.scheme or parsed.netloc:
        _require_api_origin(parsed)
        url = f"{_API_ORIGIN}{urllib.parse.urlunsplit(('', '', parsed.path, parsed.query, ''))}"
    else:
        if not candidate.startswith("/"):
            raise TransportError("relative API path must start with '/'")
        url = f"{_API_ORIGIN}{candidate}"
    if params:
        separator = "&" if parsed.query else "?"
        url = f"{url}{separator}{urllib.parse.urlencode(params, doseq=True)}"
    _require_api_origin(_split(url))
    return url


def _split(url: str) -> urllib.parse.SplitResult:
    try:
        return urllib.parse.urlsplit(url)
    except ValueError:
        raise TransportError("malformed URL rejected") from None


def _require_api_origin(parsed: urllib.parse.SplitResult) -> None:
    if parsed.scheme != "https":
        raise TransportError("non-HTTPS URL rejected")
    if parsed.hostname != _API_HOST:
        raise TransportError("URL outside api.github.com rejected")
    if parsed.username is not None or parsed.password is not None:
        raise TransportError("userinfo in URL rejected")
    try:
        port = parsed.port
    except ValueError:
        raise TransportError("invalid port rejected") from None
    if port is not None:
        raise TransportError("non-default port rejected")
    if parsed.fragment:
        raise TransportError("URL fragment rejected")


def _validated_next_url(link_header: str | None) -> str | None:
    if link_header is None:
        return None
    next_urls: list[str] = []
    for segment in link_header.split(","):
        match = _LINK_SEGMENT_RE.fullmatch(segment.strip())
        if match is None:
            raise TransportError("malformed Link header")
        rels = [
            relation.lower()
            for found in _REL_RE.finditer(match.group("params"))
            for relation in (found.group(1) or found.group(2) or "").split()
        ]
        if "next" in rels:
            _require_api_origin(_split(match.group("url")))
            next_urls.append(match.group("url"))
    if len(next_urls) > 1:
        raise TransportError("duplicate next link relation")
    return next_urls[0] if next_urls else None


def _validate_query_document(document: str) -> None:
    if not isinstance(document, str) or not document.strip():
        raise TransportError("blank GraphQL document")
    # Conservative lexical subset: carriage returns would end comments for a
    # real GraphQL parser but not this scanner, so they are rejected outright
    # together with block strings. Comments are rejected after ordinary
    # string literals are stripped so a literal containing '#' still passes.
    if "\r" in document or '"""' in document:
        raise TransportError("unsupported GraphQL lexical form")
    stripped = _strip_strings(document)
    if "#" in stripped:
        raise TransportError("unsupported GraphQL lexical form")
    tokens = [match.group(0) for match in _TOKEN_RE.finditer(stripped)]
    _check_query_only(tokens)


def _strip_strings(document: str) -> str:
    out: list[str] = []
    index = 0
    length = len(document)
    while index < length:
        if document[index] == '"':
            end = index + 1
            while end < length and document[end] != '"':
                end += 2 if document[end] == "\\" else 1
            out.append(" ")
            index = end + 1
        else:
            out.append(document[index])
            index += 1
    return "".join(out)


class _QueryOnlyScanner:
    """Token scanner requiring every top-level definition to be a query.

    ``fragment`` definitions are accepted as part of an explicit query
    document; shorthand ``{ ... }`` selections, ``mutation``,
    ``subscription``, and any other top-level definition are rejected before
    the document can reach the network.
    """

    def __init__(self) -> None:
        self.depth = 0
        self.paren = 0
        self.expect_definition = True
        self.saw_query = False

    def feed(self, symbol: str) -> None:
        if symbol == "(":
            self.paren += 1
            return
        if symbol == ")":
            self._close_paren()
            return
        if self.paren > 0:
            return
        if symbol == "{":
            self._open_brace()
            return
        if symbol == "}":
            self._close_brace()
            return
        self._word(symbol)

    def finish(self) -> None:
        if self.depth != 0 or self.paren != 0 or not self.expect_definition:
            raise TransportError("malformed GraphQL document")
        if not self.saw_query:
            raise TransportError("no explicit query operation")

    def _close_paren(self) -> None:
        if self.paren == 0:
            raise TransportError("malformed GraphQL document")
        self.paren -= 1

    def _open_brace(self) -> None:
        if self.expect_definition:
            raise TransportError("shorthand GraphQL operation rejected")
        self.depth += 1

    def _close_brace(self) -> None:
        self.depth -= 1
        if self.depth < 0:
            raise TransportError("malformed GraphQL document")
        if self.depth == 0:
            self.expect_definition = True

    def _word(self, symbol: str) -> None:
        if self.depth != 0 or not self.expect_definition:
            return
        self.expect_definition = False
        if symbol == "query":
            self.saw_query = True
        elif symbol not in _DEFINITION_KEYWORDS:
            raise TransportError("non-query GraphQL operation rejected")


def _check_query_only(tokens: list[str]) -> None:
    scanner = _QueryOnlyScanner()
    for symbol in tokens:
        scanner.feed(symbol)
    scanner.finish()
