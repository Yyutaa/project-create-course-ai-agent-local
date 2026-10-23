"""DeepSeek Search/Fetch and narrowly bounded public identity checks."""

from ipaddress import ip_address
import json
from html.parser import HTMLParser
import re
import socket
from time import monotonic
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.v0.local_config import ConfigError, LocalConfigStore
from app.v0.source_tools import canonical_public_url


class SourceNetworkError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _timeout(deadline: float | None, cap: float) -> float:
    if deadline is None:
        return cap
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise SourceNetworkError("source_tool_timeout")
    return min(cap, remaining)


class DeepSeekSourceClient:
    def __init__(
        self, config: LocalConfigStore, client: httpx.Client | None = None,
    ):
        self.config = config
        self.client = client or httpx.Client(
            trust_env=False, follow_redirects=False,
        )

    def _post(
        self, endpoint: str, payload: dict, timeout_seconds: float = 20,
    ) -> dict:
        try:
            _, key = self.config.require_credentials()
        except ConfigError:
            raise SourceNetworkError("deepseek_config_required") from None
        try:
            with self.client.stream(
                "POST", f"https://api.deepseek.com/v1/tools/{endpoint}",
                headers={"Authorization": f"Bearer {key}"},
                json=payload, timeout=timeout_seconds,
            ) as response:
                response.raise_for_status()
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 512 * 1024:
                        raise SourceNetworkError("deepseek_source_output_limit")
                    chunks.append(chunk)
            value = json.loads(b"".join(chunks))
            if not isinstance(value, dict):
                raise ValueError("response is not an object")
            return value
        except SourceNetworkError:
            raise
        except httpx.HTTPStatusError as error:
            raise SourceNetworkError(
                f"deepseek_source_http_{error.response.status_code}"
            ) from None
        except (httpx.HTTPError, ValueError):
            raise SourceNetworkError("deepseek_source_unavailable") from None

    def search(self, query: str) -> list[dict]:
        payload = self._post(
            "search", {"query": query, "count": 5, "need_content": False},
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise SourceNetworkError("deepseek_search_invalid_result")
        return [item for item in results[:5] if isinstance(item, dict)]

    def fetch(self, url: str, timeout_seconds: float = 20) -> dict:
        canonical = canonical_public_url(url)
        payload = self._post(
            "fetch", {"url": canonical}, timeout_seconds=timeout_seconds,
        )
        title, content = payload.get("title"), payload.get("content")
        if not isinstance(title, str) or not isinstance(content, str):
            raise SourceNetworkError("deepseek_fetch_invalid_result")
        if not content or len(content.encode("utf-8")) > 64 * 1024:
            raise SourceNetworkError("deepseek_fetch_output_limit")
        return {"title": title[:200], "content": content}


def _public_addresses(host: str) -> list[str]:
    return list({
        item[4][0] for item in socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM,
        )
    })


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main_parts: list[str] = []
        self.ignored = 0
        self.main_depth = 0

    def _append(self, value: str) -> None:
        if not self.ignored:
            self.parts.append(value)
            if self.main_depth:
                self.main_parts.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "nav", "header", "footer", "aside"):
            self.ignored += 1
        elif tag in ("main", "article"):
            self.main_depth += 1
        elif tag in ("p", "div", "li", "br", "pre", "h1", "h2", "h3"):
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "nav", "header", "footer", "aside"):
            self.ignored = max(0, self.ignored - 1)
        elif tag in ("main", "article"):
            self.main_depth = max(0, self.main_depth - 1)
        elif tag in ("p", "div", "li", "pre", "h1", "h2", "h3"):
            self._append("\n")

    def handle_data(self, data: str) -> None:
        self._append(data)

    def text(self) -> str:
        chosen = self.main_parts or self.parts
        return "\n".join(
            line.strip() for line in "".join(chosen).splitlines()
            if line.strip()
        )


class OfficialIdentityVerifier:
    """Anchor documentation hosts in an agreeing npm and GitHub identity chain."""

    def __init__(
        self, client: httpx.Client | None = None, resolver=None,
    ):
        self.client = client or httpx.Client(
            trust_env=False, follow_redirects=False,
        )
        self.resolver = resolver or _public_addresses

    def _pinned(self, canonical: str) -> tuple[str, str] | None:
        host = urlsplit(canonical).hostname
        if host is None:
            return None
        addresses = self.resolver(host)
        if not addresses or not all(
            ip_address(address).is_global for address in addresses
        ):
            return None
        address = ip_address(addresses[0])
        netloc = f"[{address}]" if address.version == 6 else str(address)
        parts = urlsplit(canonical)
        pinned_url = urlunsplit(("https", netloc, parts.path, parts.query, ""))
        return pinned_url, host

    def _read_verified_page(
        self, canonical: str, deadline: float | None = None,
    ) -> str | None:
        pinned = self._pinned(canonical)
        if pinned is None:
            return None
        pinned_url, host = pinned
        with self.client.stream(
            "GET", pinned_url, headers={"Host": host},
            extensions={"sni_hostname": host}, timeout=_timeout(deadline, 20),
            follow_redirects=False,
        ) as response:
            if not 200 <= response.status_code < 300:
                return None
            media_type = response.headers.get("content-type", "text/html").split(";")[0]
            if media_type not in ("text/html", "text/plain", "text/markdown"):
                return None
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 1024 * 1024:
                    return None
                chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        if media_type == "text/html":
            parser = _PageText()
            parser.feed(raw)
            content = parser.text()
        else:
            content = raw.strip()
        if not content:
            return None
        return content.encode("utf-8")[:64 * 1024].decode("utf-8", errors="ignore")

    def verify_manual(
        self, url: str, decision: dict, deadline: float | None = None,
    ) -> dict | None:
        try:
            canonical = canonical_public_url(url)
            host = urlsplit(canonical).hostname
            if (
                not decision.get("human_decision_id")
                or decision.get("official_host") != host
            ):
                return None
            content = self._read_verified_page(canonical, deadline)
            if not content:
                return None
            return {
                "human_decision_id": decision["human_decision_id"],
                "official_host": host,
                "verified_content": content,
            }
        except (ValueError, httpx.HTTPError, OSError):
            return None

    def _official_origin(
        self, topic: str, deadline: float | None = None,
    ) -> tuple[str, str, str] | None:
        try:
            package = re.search(r"[A-Za-z][A-Za-z0-9._-]{0,63}", topic)
            if package is None:
                return None
            name = package.group(0).lower()
            metadata = self.client.get(
                f"https://registry.npmjs.org/{quote(name)}/latest",
                timeout=_timeout(deadline, 4),
            )
            if metadata.status_code != 200:
                return None
            package_record = metadata.json()
            if package_record.get("name", "").lower() != name:
                return None
            homepage = canonical_public_url(package_record["homepage"])
            repository = package_record["repository"]
            repository_url = (
                repository.get("url", "") if isinstance(repository, dict)
                else repository
            )
            match = re.search(
                r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
                repository_url,
            )
            if match is None:
                return None
            owner, repo = match.group(1), match.group(2).removesuffix(".git")
            repository_name = f"{owner}/{repo}"
            repository_response = self.client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                timeout=_timeout(deadline, 4),
            )
            if repository_response.status_code != 200:
                return None
            repository_record = repository_response.json()
            if repository_record.get("full_name", "").lower() != (
                repository_name.lower()
            ):
                return None
            repository_homepage = canonical_public_url(
                repository_record["homepage"]
            )
            if (
                urlsplit(homepage).hostname != urlsplit(repository_homepage).hostname
            ):
                return None
            host = urlsplit(homepage).hostname
            return (name, repository_name, host) if host else None
        except (KeyError, TypeError, ValueError, httpx.HTTPError, OSError):
            return None

    def official_host(self, topic: str) -> str | None:
        origin = self._official_origin(topic)
        return origin[2] if origin else None

    def verify(
        self, topic: str, url: str, deadline: float | None = None,
    ) -> dict | None:
        try:
            canonical = canonical_public_url(url)
            host = urlsplit(canonical).hostname
            first_segment = urlsplit(canonical).path.strip("/").split("/", 1)[0]
            if first_segment not in {
                "guide", "api", "docs", "documentation", "reference",
                "manual", "learn", "tutorial",
            }:
                return None
            origin = self._official_origin(topic, deadline)
            if origin is None or host is None:
                return None
            name, repository_name, root_host = origin
            if host != root_host and not host.endswith(f".{root_host}"):
                return None
            content = self._read_verified_page(canonical, deadline)
            if not content:
                return None
            return {
                "registry_package": name,
                "repository": repository_name,
                "official_host": host,
                "verified_content": content,
            }
        except (ValueError, httpx.HTTPError, OSError):
            return None
