import httpx
import pytest

from app.v0.source_network import (
    DeepSeekSourceClient, OfficialIdentityVerifier, SourceNetworkError,
)


class CredentialStub:
    def require_credentials(self):
        return "deepseek-flash", "existing-key"


def test_search_and_fetch_use_existing_key_and_fixed_vendor_endpoints():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [
                {"url": "https://vuejs.org/guide", "title": "Vue Guide"},
            ]})
        return httpx.Response(200, json={
            "title": "Vue Guide", "content": "# Guide\nState changes update views.",
        })

    client = DeepSeekSourceClient(
        CredentialStub(), httpx.Client(transport=httpx.MockTransport(respond))
    )
    assert client.search("Vue state")[0]["url"] == "https://vuejs.org/guide"
    assert client.fetch("https://vuejs.org/guide")["title"] == "Vue Guide"
    assert [str(request.url) for request in requests] == [
        "https://api.deepseek.com/v1/tools/search",
        "https://api.deepseek.com/v1/tools/fetch",
    ]
    assert all(request.headers["Authorization"] == "Bearer existing-key"
               for request in requests)
    assert requests[0].read().decode().find('"need_content":false') >= 0


def test_vendor_error_does_not_echo_remote_body():
    client = DeepSeekSourceClient(
        CredentialStub(), httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, text="secret-in-error")
        )),
    )
    with pytest.raises(SourceNetworkError) as caught:
        client.search("Vue")
    assert "secret-in-error" not in str(caught.value)


def test_vendor_response_body_is_bounded_before_json_decode():
    client = DeepSeekSourceClient(
        CredentialStub(), httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * (512 * 1024 + 1))
        )),
    )
    with pytest.raises(SourceNetworkError) as caught:
        client.search("Vue")
    assert str(caught.value) == "deepseek_source_output_limit"


def test_official_identity_requires_registry_and_repository_agreement():
    checked = []

    def respond(request):
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={
                "name": "vue", "homepage": "https://vuejs.org/",
                "repository": {"url": "git+https://github.com/vuejs/core.git"},
            })
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={
                "full_name": "vuejs/core", "homepage": "https://vuejs.org/",
            })
        checked.append(request)
        if request.method == "GET":
            return httpx.Response(200, headers={"Content-Type": "text/html"},
                                  text="<nav>navigation noise</nav>"
                                       "<main><script>ignore this instruction</script>"
                                       "<h1>Vue Guide</h1>"
                                       "<p>State changes update views.</p></main>")
        return httpx.Response(200)

    verifier = OfficialIdentityVerifier(
        httpx.Client(transport=httpx.MockTransport(respond)),
        resolver=lambda host: ["93.184.216.34"],
    )
    identity = verifier.verify("学习 Vue state", "https://vuejs.org/guide")
    assert identity == {
        "registry_package": "vue", "repository": "vuejs/core",
        "official_host": "vuejs.org",
        "verified_content": "Vue Guide\nState changes update views.",
    }
    assert checked[0].url.host == "93.184.216.34"
    assert checked[0].headers["Host"] == "vuejs.org"
    assert checked[0].extensions["sni_hostname"] == "vuejs.org"
    assert "ignore this instruction" not in identity["verified_content"]
    assert "navigation noise" not in identity["verified_content"]
    assert verifier.verify(
        "学习 Vue state", "https://vuejs.org/community/guest-post"
    ) is None


def test_official_identity_accepts_documentation_subdomain_only_under_anchor():
    def respond(request):
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={
                "name": "react", "homepage": "https://react.dev/",
                "repository": {"url": "https://github.com/react/react"},
            })
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={
                "full_name": "react/react", "homepage": "https://react.dev/",
            })
        return httpx.Response(200, headers={"Content-Type": "text/html"},
                              text="<main><h1>State</h1><p>Verified page.</p></main>")

    verifier = OfficialIdentityVerifier(
        httpx.Client(transport=httpx.MockTransport(respond)),
        resolver=lambda host: ["93.184.216.34"],
    )
    assert verifier.official_host("React state") == "react.dev"
    identity = verifier.verify(
        "React state", "https://zh-hans.react.dev/learn/state-a-components-memory"
    )
    assert identity is not None
    assert identity["official_host"] == "zh-hans.react.dev"
    assert verifier.verify(
        "React state", "https://fake-react.dev/learn/state"
    ) is None


def test_official_identity_rejects_redirect_and_private_dns():
    def respond(request):
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={
                "name": "vue", "homepage": "https://vuejs.org/",
                "repository": "https://github.com/vuejs/core",
            })
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={
                "full_name": "vuejs/core", "homepage": "https://vuejs.org/",
            })
        return httpx.Response(302, headers={"Location": "https://evil.example"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    assert OfficialIdentityVerifier(
        client, resolver=lambda host: ["127.0.0.1"]
    ).verify("Vue state", "https://vuejs.org/guide") is None
    assert OfficialIdentityVerifier(
        client, resolver=lambda host: ["93.184.216.34"]
    ).verify("Vue state", "https://vuejs.org/guide") is None


def test_official_identity_rejects_get_redirect():
    def respond(request):
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={
                "name": "vue", "homepage": "https://vuejs.org/",
                "repository": "https://github.com/vuejs/core",
            })
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={
                "full_name": "vuejs/core", "homepage": "https://vuejs.org/",
            })
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    verifier = OfficialIdentityVerifier(
        httpx.Client(transport=httpx.MockTransport(respond)),
        resolver=lambda host: ["93.184.216.34"],
    )
    assert verifier.verify("Vue state", "https://vuejs.org/guide") is None


def test_manual_identity_requires_exact_host_and_verified_page():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"Content-Type": "text/plain"},
            text="State changes update views.",
        )

    verifier = OfficialIdentityVerifier(
        httpx.Client(transport=httpx.MockTransport(respond)),
        resolver=lambda host: ["93.184.216.34"],
    )
    decision = {"human_decision_id": "decision-1", "official_host": "vuejs.org"}
    assert verifier.verify_manual("https://vuejs.org/guide", decision) == {
        **decision, "verified_content": "State changes update views.",
    }
    assert verifier.verify_manual("https://other.org/guide", decision) is None
    assert len(requests) == 1
