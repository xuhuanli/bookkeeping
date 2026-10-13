import base64
import io

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.main import create_app
from backend.models import OrderInput


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'data', tmp_path / 'images', tmp_path / 'frontend')) as client:
        yield client


def backup():
    output = io.BytesIO()
    Image.new('RGB', (30, 20), '#a8b98b').save(output, 'JPEG')
    photo = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()
    return {
        'orders': [
            {'id': 'old-1', 'no': 'DD20260928-01', 'date': '2026-09-28', 'customer': '测试甲',
             'style': '包包甲', 'price': 71.7, 'deposit': 25, 'final': 47, 'cut': 0,
             'status': '已完成', 'phone': '123456789', 'address': '测试地址', 'tracking': 'TEST001',
             'note': '原订单备注', 'ph': [photo, photo]},
            {'id': 'old-2', 'no': 'DD20261001-01', 'date': '2026-10-01', 'customer': '测试乙',
             'style': '包包乙', 'price': 100, 'deposit': 20, 'final': 0, 'cut': 1,
             'status': '已收定金-待制作', 'note': ''},
        ],
        'cash': [
            {'id': 'cash-1', 'date': '2026-09-28', 'type': '收入-定金', 'orderNo': 'DD20260928-01', 'desc': '原定金', 'inc': 25, 'exp': 0, 'note': ''},
            {'id': 'cash-2', 'date': '2026-10-07', 'type': '收入-尾款', 'orderNo': 'DD20260928-01', 'desc': '原尾款', 'inc': 47, 'exp': 0, 'note': ''},
            {'id': 'cash-3', 'date': '2026-10-01', 'type': '收入-定金', 'orderNo': 'DD20261001-01', 'desc': '另一笔定金', 'inc': 20, 'exp': 0, 'note': ''},
            {'id': 'cash-4', 'date': '2026-09-04', 'type': '采购-布料', 'orderNo': '', 'desc': '布料', 'inc': 0, 'exp': 12.34, 'note': '原流水备注'},
        ],
        'styles': [{'name': '常用包包', 'price': 71.7}], 'seq': {'20260928': 1},
    }


def test_restore_preserves_money_dates_ids_and_photos_without_duplicate_income(client):
    source = backup()
    response = client.post('/api/restore', json=source, headers={'X-Ledger-Revision': '0'})
    assert response.status_code == 200, response.text
    result = response.json()
    state = result['data']
    assert len(state['orders']) == 2 and len(state['transactions']) == 4 and len(state['styles']) == 1
    assert {t['id']: (t['date'], t['amount']) for t in state['transactions']} == {
        c['id']: (c['date'], c['inc'] or c['exp']) for c in source['cash']
    }
    first, second = state['orders']
    assert first['id'] == source['orders'][0]['no'] and first['legacyImport']['sourceId'] == 'old-1'
    assert first['price'] == 71.7 and first['received'] == 72 and first['discount'] == 0
    assert first['legacyImport']['overpaymentCents'] == 30
    assert first['status'] == 'delivered' and first['completedDate'] == ''
    assert first['address'] == '电话：123456789\n测试地址' and first['note'] == '原订单备注'
    assert second['photos'] == [] and second['discountHistory'] == []
    assert second['legacyImport']['undatedDiscount'] == 1
    assert first['photos'][0] == first['photos'][1]
    assert client.get(first['photos'][0]).status_code == 200
    assert len(list(client.app.state.images_dir.glob('*.jpg'))) == 1
    total = result['reports']['total']
    assert (total['income'], total['expense'], total['net'], total['pending']) == (92, 12.34, 79.66, 79)
    assert total['completed'] == total['completedUndated'] == 1
    october = next(r for r in result['reports']['months'] if r['month'] == '2026-10')
    assert october['completed'] == 0 and october['pendingEstimated']
    exported = client.get('/api/backup').json()
    assert client.post('/api/restore', json=exported).status_code == 200
    assert client.get('/api/reports').json()['total'] == total


def test_edit_imported_order_preserves_unknown_dates_and_rejects_larger_overpayment(client):
    state = client.post('/api/restore', json=backup()).json()['data']
    first, second = state['orders']
    fields = {k: v for k, v in first.items() if k in OrderInput.model_fields}
    fields.update(receiptDate='2026-10-13', note='补充备注')
    response = client.put('/api/orders/' + first['id'], json=fields)
    assert response.status_code == 200, response.text
    changed = response.json()['data']['orders'][0]
    assert changed['completedDate'] == '' and changed['legacyImport'] == first['legacyImport']
    assert response.json()['data']['transactions'] == state['transactions']
    fields['final'] = 47.01
    assert client.put('/api/orders/' + first['id'], json=fields).status_code == 400
    fields = {k: v for k, v in second.items() if k in OrderInput.model_fields}
    fields.update(discount=2, receiptDate='2026-10-13')
    response = client.put('/api/orders/' + second['id'], json=fields)
    assert response.status_code == 200, response.text
    changed = response.json()['data']['orders'][1]
    assert changed['legacyImport']['undatedDiscount'] == 1
    assert changed['discountHistory'] == [{'date': '2026-10-13', 'amount': 1}]
    assert client.patch('/api/orders/' + first['id'] + '/status', json={'status': 'making'}).status_code == 200
    fields = {k: v for k, v in changed.items() if k in OrderInput.model_fields}
    fields.update(status='delivered', receiptDate='2026-10-13')
    response = client.put('/api/orders/' + second['id'], json=fields)
    assert response.status_code == 200, response.text
    assert response.json()['data']['orders'][1]['completedDate'] == '2026-10-13'


@pytest.mark.parametrize('damage', ['receipt', 'duplicate', 'category', 'photo', 'date', 'both_amounts'])
def test_invalid_legacy_restore_is_atomic(client, damage):
    original = client.post('/api/restore', json=backup()).json()
    broken = backup()
    if damage == 'receipt':
        broken['cash'][0]['inc'] = 24
    elif damage == 'duplicate':
        broken['cash'][1]['id'] = broken['cash'][0]['id']
    elif damage == 'category':
        broken['cash'][0]['type'] = '未知分类'
    elif damage == 'photo':
        broken['orders'][1]['ph'] = ['data:image/jpeg;base64,bm90LWFuLWltYWdl']
    elif damage == 'date':
        broken['cash'][0]['date'] = '2026-09-27'
    elif damage == 'both_amounts':
        broken['cash'][0]['exp'] = 1
    files_before = set(client.app.state.images_dir.glob('*.jpg'))
    response = client.post('/api/restore', json=broken)
    assert response.status_code == 400, response.text
    assert client.get('/api/ledger').json() == original
    assert set(client.app.state.images_dir.glob('*.jpg')) == files_before


def test_legacy_revision_conflict_keeps_current_state_and_cleans_images(client):
    response = client.post('/api/restore', json=backup(), headers={'X-Ledger-Revision': '9'})
    assert response.status_code == 409
    assert client.get('/api/ledger').json()['data']['orders'] == []
    assert list(client.app.state.images_dir.glob('*.jpg')) == []
