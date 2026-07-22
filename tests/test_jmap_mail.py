from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.jmap_client import JmapClient


MAIL_CAPABILITY = "urn:ietf:params:jmap:mail"


def response(json_body: dict) -> MagicMock:
    result = MagicMock()
    result.json.return_value = json_body
    result.raise_for_status = MagicMock()
    return result


def blob_response(content: bytes, content_type: str) -> MagicMock:
    result = MagicMock()
    result.content = content
    result.headers = {"content-type": content_type}
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


def test_get_set_delete_and_blob_use_mail_account(client, mocked_post, mocked_get):
    mocked_post.side_effect = [
        response({"methodResponses": [["Email/get", {"list": [{"id": "m1", "blobId": "b1"}]}, "0"]]}),
        response({"methodResponses": [["Email/set", {"updated": {"m1": None}}, "0"]]}),
        response({"methodResponses": [["Email/set", {"destroyed": ["m1"]}, "0"]]}),
    ]
    mocked_get.side_effect = [
        response({"downloadUrl": "https://mail.example/download/{accountId}/{blobId}/{name}"}),
        blob_response(b"raw", "message/rfc822"),
    ]

    assert client.get_message("mail-account", "m1")["blobId"] == "b1"
    assert client.set_seen("mail-account", "m1", True)
    assert client.delete_message("mail-account", "m1")
    assert client.download_blob("mail-account", "b1", "message.eml") == (b"raw", "message/rfc822")

    calls = [call.kwargs["json"]["methodCalls"][0][1] for call in mocked_post.call_args_list]
    assert calls[1]["accountId"] == "mail-account"
    assert calls[1]["update"]["m1"]["keywords/$seen"] is True
    assert calls[2] == {"accountId": "mail-account", "destroy": ["m1"]}
    assert mocked_get.call_args_list[1].args[0] == "https://mail.example/download/mail-account/b1/message.eml"


def test_jmap_method_errors_return_safe_empty_values(client, mocked_post):
    mocked_post.return_value = response({"methodResponses": [["error", {"type": "serverFail"}, "0"]]})

    assert client.list_messages("mail-account", "box@example.com", 15, 0) == (0, [])
    assert client.get_message("mail-account", "m1") is None
    assert client.set_seen("mail-account", "m1", True) is False
    assert client.delete_message("mail-account", "m1") is False


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
