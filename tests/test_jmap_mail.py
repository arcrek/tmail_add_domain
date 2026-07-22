from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.jmap_client import JmapClient, JmapUpstreamError


MAIL_CAPABILITY = "urn:ietf:params:jmap:mail"


def response(json_body: dict) -> MagicMock:
    result = MagicMock()
    result.json.return_value = json_body
    result.raise_for_status = MagicMock()
    return result


@pytest.fixture
def client() -> JmapClient:
    return JmapClient("https://mail.example/jmap", "token123", "admin@example.com")


@pytest.fixture
def mocked_post():
    with patch("src.jmap_client.httpx.post") as mocked:
        yield mocked


@pytest.fixture
def mocked_get():
    with patch("src.jmap_client.httpx.get") as mocked:
        yield mocked


def test_discovers_personal_mail_account_from_session(client, mocked_get):
    mocked_get.return_value = response({
        "primaryAccounts": {MAIL_CAPABILITY: "mail-account"},
        "accounts": {"mail-account": {"isPersonal": True}},
        "downloadUrl": "https://mail.example/download/{accountId}/{blobId}/{name}",
    })

    assert client.discover_mail_account_id() == "mail-account"


def test_list_messages_queries_recipient_and_returns_query_total(client, mocked_post):
    mocked_post.return_value = response({"methodResponses": [
        ["Email/query", {"ids": ["m1"], "total": 1}, "q"],
        ["Email/get", {"list": [{"id": "m1", "subject": "Code", "to": [{"email": "box@example.com"}]}]}, "g"],
    ]})

    total, messages = client.list_messages("mail-account", "box@example.com", 15, 0)

    assert total == 1
    assert messages[0]["id"] == "m1"
    query = mocked_post.call_args.kwargs["json"]["methodCalls"][0][1]
    assert query["filter"] == {
        "operator": "OR",
        "conditions": [
            {"to": "box@example.com"},
            {"header": ["Delivered-To", "box@example.com"]},
        ],
    }


def test_get_message_requests_full_body_and_attachment_fields(client, mocked_post):
    mocked_post.return_value = response({"methodResponses": [
        ["Email/get", {"list": [{
            "id": "m1",
            "bodyValues": {"text": {"value": "plain"}, "html": {"value": "<p>html</p>"}},
            "textBody": [{"partId": "text"}],
            "htmlBody": [{"partId": "html"}],
            "attachments": [{"blobId": "a1", "name": "file.txt"}],
        }]}, "0"],
    ]})

    message = client.get_message("mail-account", "m1")

    assert message["bodyValues"]["text"]["value"] == "plain"
    assert message["bodyValues"]["html"]["value"] == "<p>html</p>"
    assert message["attachments"][0]["blobId"] == "a1"
    properties = mocked_post.call_args.kwargs["json"]["methodCalls"][0][1]["properties"]
    assert {"bodyValues", "textBody", "htmlBody", "attachments", "bodyStructure"} <= set(properties)
    arguments = mocked_post.call_args.kwargs["json"]["methodCalls"][0][1]
    assert arguments["fetchTextBodyValues"] is True
    assert arguments["fetchHTMLBodyValues"] is True


def test_get_set_delete_use_mail_account(client, mocked_post):
    mocked_post.side_effect = [
        response({"methodResponses": [["Email/get", {"list": [{"id": "m1", "blobId": "b1"}]}, "0"]]}),
        response({"methodResponses": [["Email/set", {"updated": {"m1": None}}, "0"]]}),
        response({"methodResponses": [["Email/set", {"destroyed": ["m1"]}, "0"]]}),
    ]
    assert client.get_message("mail-account", "m1")["blobId"] == "b1"
    assert client.set_seen("mail-account", "m1", True)
    assert client.delete_message("mail-account", "m1")

    calls = [call.kwargs["json"]["methodCalls"][0][1] for call in mocked_post.call_args_list]
    assert calls[1]["accountId"] == "mail-account"
    assert calls[1]["update"]["m1"]["keywords/$seen"] is True
    assert calls[2] == {"accountId": "mail-account", "destroy": ["m1"]}


def test_download_blob_substitutes_type_and_streams_inside_owned_context():
    events = []

    class StreamResponse:
        headers = {"content-type": "message/rfc822; charset=binary"}

        def raise_for_status(self):
            events.append("status")

        def iter_bytes(self):
            assert "closed" not in events
            yield b"ra"
            yield b"w"

    class StreamingClient:
        def get(self, *_args, **_kwargs):
            return response({
                "primaryAccounts": {MAIL_CAPABILITY: "mail-account"},
                "accounts": {"mail-account": {"isPersonal": True}},
                "downloadUrl": "https://mail.example/download/{accountId}/{blobId}/{name}?type={type}",
            })

        @contextmanager
        def stream(self, method, url, **kwargs):
            events.append((method, url, kwargs))
            events.append("entered")
            yield StreamResponse()
            events.append("closed")

    client = JmapClient(
        "https://mail.example/jmap", "token123", "admin@example.com", client=StreamingClient()
    )

    chunks, content_type = client.download_blob(
        "mail-account", "b1", "message.eml", "message/rfc822"
    )

    assert events[1:3] == ["entered", "status"]
    assert b"ra" not in events
    assert b"".join(chunks) == b"raw"
    assert content_type == "message/rfc822"
    assert events[0][0:2] == (
        "GET",
        "https://mail.example/download/mail-account/b1/message.eml?type=message%2Frfc822",
    )
    assert events[-1] == "closed"


def test_download_blob_closes_preopened_stream_when_status_fails():
    events = []

    class FailedResponse:
        def raise_for_status(self):
            raise RuntimeError("private upstream detail")

    class StreamingClient:
        def get(self, *_args, **_kwargs):
            return response({"downloadUrl": "https://mail.example/download/{blobId}"})

        @contextmanager
        def stream(self, *_args, **_kwargs):
            try:
                yield FailedResponse()
            finally:
                events.append("closed")

    client = JmapClient("https://mail.example/jmap", "token", "admin@example.com", StreamingClient())

    with pytest.raises(JmapUpstreamError, match="JMAP upstream request failed"):
        client.download_blob("mail-account", "b1", "name")

    assert events == ["closed"]


def test_download_blob_consumes_lazily_and_early_close_releases_stream():
    events = []

    class StreamResponse:
        def raise_for_status(self):
            events.append("status")

        def iter_bytes(self):
            events.append("first chunk")
            yield b"first"
            events.append("second chunk")
            yield b"second"

    class StreamingClient:
        def get(self, *_args, **_kwargs):
            return response({"downloadUrl": "https://mail.example/download/{blobId}"})

        @contextmanager
        def stream(self, *_args, **_kwargs):
            try:
                events.append("entered")
                yield StreamResponse()
            finally:
                events.append("closed")

    client = JmapClient("https://mail.example/jmap", "token", "admin@example.com", StreamingClient())
    chunks, _ = client.download_blob("mail-account", "b1", "name")

    assert events == ["entered", "status"]
    assert next(chunks) == b"first"
    assert events == ["entered", "status", "first chunk"]
    chunks.close()
    assert events[-1] == "closed"


def test_download_blob_closes_and_sanitizes_iteration_errors():
    events = []

    class StreamResponse:
        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"first"
            raise RuntimeError("private upstream detail")

    class StreamingClient:
        def get(self, *_args, **_kwargs):
            return response({"downloadUrl": "https://mail.example/download/{blobId}"})

        @contextmanager
        def stream(self, *_args, **_kwargs):
            try:
                yield StreamResponse()
            finally:
                events.append("closed")

    client = JmapClient("https://mail.example/jmap", "token", "admin@example.com", StreamingClient())
    chunks, _ = client.download_blob("mail-account", "b1", "name")

    assert next(chunks) == b"first"
    with pytest.raises(JmapUpstreamError, match="JMAP upstream request failed"):
        next(chunks)
    assert events == ["closed"]


@pytest.mark.parametrize("method_response", [
    ["error", {"type": "serverFail", "description": "private upstream detail"}, "0"],
    ["Email/set", {"updated": {"m1": None}}, "wrong-call-id"],
    ["Email/query", {"total": 1}, "0"],
])
def test_jmap_method_errors_and_mismatches_raise_sanitized_error(
    client, mocked_post, method_response
):
    mocked_post.return_value = response({"methodResponses": [method_response]})

    with pytest.raises(JmapUpstreamError) as caught:
        client.set_seen("mail-account", "m1", True)

    assert str(caught.value) == "JMAP upstream request failed"
    assert "private upstream detail" not in str(caught.value)


def test_jmap_unexpected_method_payload_raises_sanitized_error(client, mocked_post):
    mocked_post.return_value = response({
        "methodResponses": [["Email/get", {"list": {"private": "detail"}}, "0"]]
    })

    with pytest.raises(JmapUpstreamError, match="JMAP upstream request failed"):
        client.get_message("mail-account", "m1")


def test_message_counts_uses_total_queries_for_stored_today_and_seven_days(client, mocked_post, monkeypatch):
    now = datetime(2026, 7, 22, 14, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("src.jmap_client.datetime", MagicMock(now=MagicMock(return_value=now)))
    mocked_post.return_value = response({"methodResponses": [
        ["Email/query", {"total": 12}, "stored"],
        ["Email/query", {"total": 3}, "today"],
        ["Email/query", {"total": 8}, "sevenDays"],
    ]})

    assert client.message_counts("mail-account") == {"stored": 12, "today": 3, "sevenDays": 8}

    calls = mocked_post.call_args.kwargs["json"]["methodCalls"]
    assert [call[1]["calculateTotal"] for call in calls] == [True, True, True]
    assert calls[1][1]["filter"]["after"] == "2026-07-22T00:00:00Z"
    assert calls[2][1]["filter"]["after"] == "2026-07-15T14:30:00Z"
