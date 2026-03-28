"""Tests for Flask API routes."""
import io
import os
import xml.etree.ElementTree as ET

import pytest

from app import create_app

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
NS = 'urn:iso:std:iso:20022:tech:xsd:camt.053.001.08'


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def upload(client, endpoint, filename):
    with open(os.path.join(FIXTURES, filename), 'rb') as f:
        data = f.read()
    return client.post(
        endpoint,
        data={'file': (io.BytesIO(data), filename)},
        content_type='multipart/form-data',
    )


class TestIndex:
    def test_get(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'MT940' in resp.data


class TestParseEndpoint:
    def test_parse_single(self, client):
        resp = upload(client, '/api/parse', 'sample_single.mt940')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['errors'] == []
        assert data['statement_count'] == 1
        assert len(data['statements']) == 1

    def test_parse_multi(self, client):
        resp = upload(client, '/api/parse', 'sample_multi.mt940')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['statement_count'] == 2

    def test_parse_no_file(self, client):
        resp = client.post('/api/parse')
        assert resp.status_code == 400

    def test_parse_empty_filename(self, client):
        resp = client.post(
            '/api/parse',
            data={'file': (io.BytesIO(b''), '')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400


class TestConvertEndpoint:
    def test_convert_returns_xml(self, client):
        resp = upload(client, '/api/convert', 'sample_single.mt940')
        assert resp.status_code == 200
        assert 'xml' in resp.content_type
        assert resp.data.startswith(b'<?xml')

    def test_convert_valid_camt053(self, client):
        resp = upload(client, '/api/convert', 'sample_single.mt940')
        root = ET.fromstring(resp.data)
        assert root.tag == f'{{{NS}}}Document'
        entries = root.findall(f'.//{{{NS}}}Ntry')
        assert len(entries) > 0

    def test_convert_download_filename(self, client):
        resp = upload(client, '/api/convert', 'sample_single.mt940')
        disposition = resp.headers.get('Content-Disposition', '')
        assert 'camt053' in disposition

    def test_convert_multi(self, client):
        resp = upload(client, '/api/convert', 'sample_multi.mt940')
        assert resp.status_code == 200
        root = ET.fromstring(resp.data)
        stmts = root.findall(f'.//{{{NS}}}Stmt')
        assert len(stmts) == 2

    def test_convert_no_file(self, client):
        resp = client.post('/api/convert')
        assert resp.status_code == 400
