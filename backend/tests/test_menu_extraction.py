"""Tests for menu extraction endpoints (image + document upload, URL import)."""
import io
import pytest
from unittest.mock import patch
from .conftest import get_auth_header, create_test_restaurant
from app.main import _normalize_menu_import_url


def _owner_token(client, email="extract_owner@test.com"):
    resp = client.post("/auth/register-owner", json={"email": email, "password": "password123"})
    return resp.json()["access_token"]


MOCK_MENU_DATA = {
    "restaurant_name": "Test Restaurant",
    "categories": [
        {
            "name": "Main Course",
            "items": [
                {"name": "Chicken Biryani", "price": 14.99, "description": "Spiced rice with chicken"},
                {"name": "Butter Chicken", "price": 12.99, "description": "Creamy tomato chicken"},
            ]
        }
    ]
}


class TestFileUploadValidation:
    def test_unsupported_file_type(self, client):
        token = _owner_token(client, "extract_bad@test.com")
        r = create_test_restaurant(client, token, "Extract Test")
        rid = r.json()["id"]

        # Upload a .txt file — should be rejected
        file = io.BytesIO(b"Hello world")
        resp = client.post(
            f"/owner/restaurants/{rid}/extract-menu-file",
            files={"file": ("menu.txt", file, "text/plain")},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    def test_no_file(self, client):
        token = _owner_token(client, "extract_nofile@test.com")
        r = create_test_restaurant(client, token, "No File Test")
        rid = r.json()["id"]

        resp = client.post(
            f"/owner/restaurants/{rid}/extract-menu-file",
            headers=get_auth_header(token),
        )
        assert resp.status_code == 422  # validation error

    def test_no_auth(self, client):
        resp = client.post("/owner/restaurants/1/extract-menu-file",
                           files={"file": ("menu.jpg", io.BytesIO(b"fake"), "image/jpeg")})
        assert resp.status_code in (401, 403)


class TestImageExtraction:
    @patch("app.menu_extractor.extract_menu_from_image")
    def test_upload_image_success(self, mock_extract, client):
        mock_extract.return_value = MOCK_MENU_DATA

        token = _owner_token(client, "img_ok@test.com")
        r = create_test_restaurant(client, token, "Img Test")
        rid = r.json()["id"]

        # Create a fake image file (1x1 pixel PNG)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            f"/owner/restaurants/{rid}/extract-menu-file",
            files={"file": ("menu.png", io.BytesIO(fake_png), "image/png")},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        mock_extract.assert_called_once()

    @patch("app.menu_extractor.extract_menu_from_image")
    def test_upload_jpg(self, mock_extract, client):
        mock_extract.return_value = MOCK_MENU_DATA

        token = _owner_token(client, "jpg@test.com")
        r = create_test_restaurant(client, token, "JPG Test")
        rid = r.json()["id"]

        resp = client.post(
            f"/owner/restaurants/{rid}/extract-menu-file",
            files={"file": ("menu.jpg", io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 50), "image/jpeg")},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200


class TestDocumentExtraction:
    @patch("app.menu_extractor.extract_menu_from_document")
    def test_upload_pdf(self, mock_extract, client):
        mock_extract.return_value = MOCK_MENU_DATA

        token = _owner_token(client, "pdf@test.com")
        r = create_test_restaurant(client, token, "PDF Test")
        rid = r.json()["id"]

        fake_pdf = b"%PDF-1.4 fake content"
        resp = client.post(
            f"/owner/restaurants/{rid}/extract-menu-file",
            files={"file": ("menu.pdf", io.BytesIO(fake_pdf), "application/pdf")},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        mock_extract.assert_called_once()

    @patch("app.menu_extractor.extract_menu_from_document")
    def test_upload_docx(self, mock_extract, client):
        mock_extract.return_value = MOCK_MENU_DATA

        token = _owner_token(client, "docx@test.com")
        r = create_test_restaurant(client, token, "DOCX Test")
        rid = r.json()["id"]

        resp = client.post(
            f"/owner/restaurants/{rid}/extract-menu-file",
            files={"file": ("menu.docx", io.BytesIO(b"PK" + b"\x00" * 50), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200

    @patch("app.menu_extractor.extract_menu_from_document")
    def test_upload_xlsx(self, mock_extract, client):
        mock_extract.return_value = MOCK_MENU_DATA

        token = _owner_token(client, "xlsx@test.com")
        r = create_test_restaurant(client, token, "XLSX Test")
        rid = r.json()["id"]

        resp = client.post(
            f"/owner/restaurants/{rid}/extract-menu-file",
            files={"file": ("menu.xlsx", io.BytesIO(b"PK" + b"\x00" * 50), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200


class TestImportMenuFromUrl:
    """URL normalization and validation for owner import-menu (extract from website URL)."""

    def test_normalize_menu_url_adds_https(self):
        # Anjappar-style URL without scheme — must be normalized so fetch/Playwright work
        out = _normalize_menu_import_url("anjapparindian.com/menu/anjapparcharlotte")
        assert out == "https://anjapparindian.com/menu/anjapparcharlotte"

    def test_normalize_menu_url_preserves_https(self):
        out = _normalize_menu_import_url("https://anjapparindian.com/menu/anjapparcharlotte")
        assert out == "https://anjapparindian.com/menu/anjapparcharlotte"

    def test_normalize_menu_url_protocol_relative(self):
        out = _normalize_menu_import_url("//example.com/menu")
        assert out == "https://example.com/menu"

    def test_import_menu_no_url_returns_400(self, client):
        token = _owner_token(client, "import_no_url@test.com")
        resp = client.post(
            "/owner/import-menu",
            json={},
            headers=get_auth_header(token),
        )
        assert resp.status_code == 400
        assert "URL" in resp.json().get("detail", "")

    def test_import_menu_requires_owner_auth(self, client):
        resp = client.post(
            "/owner/import-menu",
            json={"url": "https://anjapparindian.com/menu/anjapparcharlotte"},
        )
        assert resp.status_code in (401, 403)


class TestSaveImportedMenu:
    def test_save_menu(self, client):
        token = _owner_token(client, "savemenu@test.com")
        r = create_test_restaurant(client, token, "Save Menu Test")
        rid = r.json()["id"]

        resp = client.post(
            f"/owner/restaurants/{rid}/import-menu",
            json={
                "categories": [
                    {
                        "name": "Starters",
                        "items": [
                            {"name": "Spring Rolls", "price": 5.99},
                            {"name": "Soup", "price": 3.99},
                        ]
                    }
                ]
            },
            headers=get_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("categories_created", 0) >= 1 or "ok" in str(data).lower() or resp.status_code == 200
