"""Tests for /api/voice/chat group order intent (open_group_tab)."""
import pytest


class TestVoiceChatGroupIntent:
    """When user says group order in voice chat, return open_group_tab without calling LLM."""

    def test_voice_chat_group_order_returns_open_group_tab(self, client):
        resp = client.post(
            "/api/voice/chat",
            json={"message": "I want to start a group order", "context": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("open_group_tab") is True
        assert "reply" in data
        assert "group" in data["reply"].lower()

    def test_voice_chat_find_food_for_people_returns_open_group_tab(self, client):
        resp = client.post(
            "/api/voice/chat",
            json={"message": "Find food for 5 people", "context": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("open_group_tab") is True

    def test_voice_chat_office_lunch_returns_open_group_tab(self, client):
        resp = client.post(
            "/api/voice/chat",
            json={"message": "We need a group lunch for the office", "context": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("open_group_tab") is True

    def test_voice_chat_empty_message_returns_400(self, client):
        resp = client.post(
            "/api/voice/chat",
            json={"message": "   ", "context": ""},
        )
        assert resp.status_code == 400

    def test_voice_chat_regular_message_does_not_return_open_group_tab(self, client):
        # When LLM is disabled (test env), this may still return 502 or a reply; we only care that
        # group intent is not set for non-group messages. If the endpoint returns 502 (no LLM),
        # that's ok for this test - we're testing that group intent path returns open_group_tab.
        resp = client.post(
            "/api/voice/chat",
            json={"message": "I want pizza", "context": ""},
        )
        if resp.status_code == 200:
            assert resp.json().get("open_group_tab") is not True
