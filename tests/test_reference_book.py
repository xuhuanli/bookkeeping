import base64
from copy import deepcopy
import io

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'data', tmp_path / 'images', tmp_path / 'frontend')) as client:
        yield client


def book():
    return {'orders': [{'id': 'source-1', 'no': 'DD20261024-03', 'date': '2026-10-24',
                        'customer': '测试顾客', 'style': '测试包 ×2', 'price': 100, 'deposit': 25,
                        'final': 0, 'cut': 0, 'status': '已收定金-待制作',
                        'phone': '', 'address': '测试收货信息', 'tracking': '', 'note': '', 'ph': []}],
            'cash': [], 'styles': [{'name': '测试包', 'price': 50}], 'seq': {'o20261024': 3}}


def save(client, data, revision=None):
    if revision is None:
        revision = client.get('/api/book').json()['revision']
    return client.put('/api/book', json=data, headers={'X-Ledger-Revision': str(revision)})


def test_orders_and_cash_are_independent_and_persist_across_restart(client, tmp_path):
    response = save(client, book())
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data == book()
    native = client.get('/api/ledger').json()['data']
    assert native['orders'][0]['received'] == 25
    assert native['transactions'] == []
    data['cash'].append({'id': 'cash-1', 'date': '2026-10-23', 'type': '收入-定金',
                         'orderNo': 'DD20261024-03', 'desc': '实际收款', 'inc': 20, 'exp': 0, 'note': ''})
    response = save(client, data)
    assert response.status_code == 200, response.text
    assert response.json()['data']['orders'][0]['deposit'] == 25
    data['orders'][0]['deposit'] = 35
    response = save(client, data)
    assert response.status_code == 200, response.text
    assert response.json()['data']['cash'][0]['inc'] == 20
    with TestClient(create_app(tmp_path / 'data', tmp_path / 'images', tmp_path / 'frontend')) as restarted:
        assert restarted.get('/api/book').json() == client.get('/api/book').json()
        native = restarted.get('/api/ledger').json()['data']
        assert native['accountingMode'] == 'manual' and native['sequence'] == {'o20261024': 3}


def test_delete_and_rename_order_preserve_cash_and_original_number(client):
    data = book()
    data['cash'] = [{'id': 'cash-1', 'date': '2026-10-24', 'type': '收入-定金',
                     'orderNo': 'DD20261024-03', 'desc': '定金', 'inc': 25, 'exp': 0, 'note': ''}]
    assert save(client, data).is_success
    data['orders'][0]['no'] = '新单号'
    assert save(client, data).is_success
    saved = client.get('/api/book').json()['data']
    assert saved['cash'][0]['orderNo'] == 'DD20261024-03'
    assert saved['orders'][0]['id'] == 'source-1'
    saved['orders'] = []
    assert save(client, saved).is_success
    assert client.get('/api/book').json()['data']['cash'] == data['cash']
    assert client.get('/api/ledger').json()['data']['transactions'][0]['orderId'] == ''


def test_reference_monthly_summary_uses_order_month_and_current_order_amounts(client):
    data = book()
    data['orders'][0].update(date='2026-09-28', final=74, cut=1, status='已完成')
    data['cash'] = [{'id': 'cash-1', 'date': '2026-10-01', 'type': '收入-尾款',
                     'orderNo': 'DD20261024-03', 'desc': '尾款', 'inc': 74, 'exp': 0, 'note': ''}]
    assert save(client, data).is_success
    reports = client.get('/api/reports').json()
    months = {r['month']: r for r in reports['months']}
    assert months['2026-09']['completed'] == 1
    assert months['2026-09']['discount'] == 1 and months['2026-09']['pending'] == 0
    assert months['2026-10']['completed'] == 0 and months['2026-10']['income'] == 74
    assert reports['total']['income'] == 74 and reports['total']['pending'] == 0


def test_existing_import_keeps_database_ids_and_source_ids_when_edited(client):
    source = book()
    source['cash'] = [{'id': 'original-cash', 'date': '2026-10-24', 'type': '收入-定金',
                       'orderNo': 'DD20261024-03', 'desc': '原定金', 'inc': 25, 'exp': 0, 'note': ''}]
    restored = client.post('/api/restore', json=source)
    assert restored.is_success, restored.text
    native = restored.json()['data']
    assert native['orders'][0]['id'] == 'DD20261024-03'
    data = client.get('/api/book').json()['data']
    assert data['orders'][0]['id'] == 'source-1'
    assert data['seq']['o20261024'] == 3
    data['orders'][0]['note'] = '补充定制细节'
    response = save(client, data)
    assert response.is_success, response.text
    saved = client.get('/api/ledger').json()['data']
    assert saved['orders'][0]['id'] == native['orders'][0]['id']
    assert saved['orders'][0]['legacyImport']['sourceId'] == 'source-1'
    assert saved['transactions'][0]['id'] == 'original-cash'
    assert saved['transactions'][0]['amount'] == 25
    assert saved['styles'] == native['styles']


def test_phone_survives_restore_and_editing_order_date_does_not_require_completion_date(client):
    data = book()
    data['orders'][0].update(phone='01012345678', status='已完成')
    assert save(client, data).is_success
    assert client.get('/api/book').json()['data']['orders'][0]['phone'] == '01012345678'
    def historical_completion(state):
        state['orders'][0]['completedDate'] = '2026-10-24'
        return state
    client.app.state.database.mutate(historical_completion)
    data['orders'][0]['date'] = '2026-10-25'
    response = save(client, data)
    assert response.is_success, response.text
    assert response.json()['data']['orders'][0]['phone'] == '01012345678'
    assert client.get('/api/ledger').json()['data']['orders'][0]['completedDate'] == ''


def test_photo_backup_restore_and_previous_native_backup_are_portable(client, tmp_path):
    output = io.BytesIO()
    Image.new('RGB', (40, 40), '#B7DFC8').save(output, 'PNG')
    data = book()
    data['orders'][0]['ph'] = ['data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()]
    response = save(client, data)
    assert response.is_success, response.text
    saved = response.json()
    url = saved['data']['orders'][0]['ph'][0]
    assert saved['imageSizes'][url] > 0 and client.get(url).status_code == 200
    portable = client.get('/api/book/backup').json()
    assert portable['orders'][0]['ph'][0].startswith('data:image/jpeg;base64,')
    with TestClient(create_app(tmp_path / 'other-data', tmp_path / 'other-images', tmp_path / 'missing')) as other:
        assert save(other, portable).is_success
        assert other.get('/api/book').json()['data']['orders'][0]['deposit'] == 25
        assert save(other, client.get('/api/backup').json()).is_success
    assert save(client, {'orders': [], 'cash': [], 'styles': [], 'seq': {}}).is_success
    # Undo also restores the mode and sequence metadata with the rows.
    assert client.post('/api/undo').is_success
    assert client.get('/api/book').json()['data'] == saved['data']


@pytest.mark.parametrize('damage', ['money', 'date', 'ids', 'cash', 'image', 'seq'])
def test_invalid_snapshot_and_revision_conflict_do_not_overwrite_data(client, damage):
    assert save(client, book()).is_success
    initial = client.get('/api/book').json()
    broken = deepcopy(initial['data'])
    if damage == 'money':
        broken['orders'][0]['deposit'] = -1
    elif damage == 'date':
        broken['orders'][0]['date'] = 'bad-date'
    elif damage == 'ids':
        broken['orders'].append(deepcopy(broken['orders'][0]))
    elif damage == 'cash':
        broken['cash'] = [{'id': 'cash-1', 'date': '2026-10-24', 'type': '采购-布料',
                           'orderNo': '', 'desc': '错误金额', 'inc': 1, 'exp': 2, 'note': ''}]
    elif damage == 'image':
        broken['orders'][0]['ph'] = ['/images/../../private.jpg']
    elif damage == 'seq':
        broken['seq'] = {'o20261024': -1}
    assert save(client, broken).status_code == 400
    assert client.get('/api/book').json() == initial
    assert save(client, initial['data'], revision=0).status_code == 409
    assert client.get('/api/book').json() == initial
