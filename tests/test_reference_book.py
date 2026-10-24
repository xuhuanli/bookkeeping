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


def save(client, data, revision=None, *, receipt_date=None, restore=False):
    if revision is None:
        revision = client.get('/api/book').json()['revision']
    headers = {'X-Ledger-Revision': str(revision)}
    if receipt_date:
        headers['X-Receipt-Date'] = receipt_date
    if restore:
        headers['X-Book-Restore'] = 'true'
    return client.put('/api/book', json=data, headers=headers)


def test_order_receipts_sync_once_and_persist_across_restart(client, tmp_path):
    response = save(client, book())
    assert response.is_success, response.text
    data = response.json()['data']
    assert len(data['cash']) == 1
    receipt = deepcopy(data['cash'][0])
    assert receipt['type'] == '收入-定金' and receipt['inc'] == 25
    assert receipt['date'] == '2026-10-24' and receipt['orderNo'] == 'DD20261024-03'
    assert save(client, data).json()['data'] == data
    data['orders'][0]['note'] = '只改备注'
    data = save(client, data).json()['data']
    receipt['note'] = '订单定金自动登记 ｜ 只改备注'
    assert data['cash'] == [receipt]
    data['orders'][0]['deposit'] = 35
    response = save(client, data, receipt_date='2026-11-01')
    assert response.is_success, response.text
    data = response.json()['data']
    assert len(data['cash']) == 1
    assert data['cash'][0] == {**receipt, 'inc':35}
    assert client.get('/api/reports').json()['months'][0]['month'] == '2026-10'
    assert save(client, data).json()['data'] == data
    with TestClient(create_app(tmp_path / 'data', tmp_path / 'images', tmp_path / 'frontend')) as restarted:
        assert restarted.get('/api/book').json() == client.get('/api/book').json()
        native = restarted.get('/api/ledger').json()['data']
        assert native['sequence'] == {'o20261024': 3}
        assert native['orders'][0]['received'] == 35


def test_delete_and_rename_order_preserve_cash_and_original_number(client):
    data = book()
    data['cash'] = [{'id': 'cash-1', 'date': '2026-10-24', 'type': '收入-定金',
                     'orderNo': 'DD20261024-03', 'desc': '定金', 'inc': 25, 'exp': 0, 'note': ''}]
    assert save(client, data).is_success
    data['orders'][0]['no'] = '新单号'
    assert save(client, data).is_success
    saved = client.get('/api/book').json()['data']
    assert saved['cash'][0]['orderNo'] == '新单号'
    assert saved['orders'][0]['id'] == 'source-1'
    saved['orders'] = []
    assert save(client, saved).is_success
    assert client.get('/api/book').json()['data']['cash'] == [{**saved['cash'][0], 'orderRef': ''}]
    assert client.get('/api/ledger').json()['data']['transactions'][0]['orderId'] == ''


@pytest.mark.parametrize('delete_first', [False, True])
def test_reusing_deleted_order_number_keeps_receipts_separate_and_portable(client, tmp_path, delete_first):
    data = save(client, book()).json()['data']
    original = deepcopy(data['cash'][0])
    replacement = {**data['orders'][0], 'id': 'replacement', 'customer': '新顾客', 'deposit': 20}
    data['orders'] = []
    if delete_first:
        data = save(client, data).json()['data']
    data['orders'] = [replacement]
    response = save(client, data)
    assert response.is_success, response.text
    data = response.json()['data']
    assert len(data['cash']) == 2
    assert data['cash'][0] == {**original, 'orderRef': ''}
    assert data['cash'][1]['inc'] == 20
    assert data['cash'][1]['desc'] == '新顾客 · 测试包 ×2'
    assert client.get('/api/reports').json()['total']['income'] == 45
    # Correcting historical cash must not change the new order's deposit.
    data['cash'][0]['inc'] = 26
    data = save(client, data).json()['data']
    assert data['orders'][0]['deposit'] == 20
    assert save(client, data).json()['data'] == data
    portable = client.get('/api/book/backup').json()
    with TestClient(create_app(tmp_path / 'restored-data', tmp_path / 'restored-images', tmp_path / 'missing')) as other:
        restored = save(other, portable, restore=True)
        assert restored.is_success, restored.text
        assert restored.json()['data'] == data
        data['orders'][0]['deposit'] = 21
        updated = save(other, data).json()['data']
        assert updated['cash'][0]['inc'] == 26
        assert updated['cash'][1]['inc'] == 21
        assert other.get('/api/reports').json()['total']['income'] == 47


def test_historical_cash_can_be_explicitly_linked_to_reused_number(client):
    data = save(client, book()).json()['data']
    replacement = {**data['orders'][0], 'id': 'replacement', 'deposit': 0}
    data['orders'] = [replacement]
    data = save(client, data).json()['data']
    assert data['cash'][0]['orderRef'] == ''
    data['cash'][0]['orderRef'] = replacement['id']
    data = save(client, data).json()['data']
    assert data['orders'][0]['deposit'] == 25
    assert len(data['cash']) == 1 and 'orderRef' not in data['cash'][0]


def test_invalid_explicit_cash_order_reference_is_rejected(client):
    data = save(client, book()).json()['data']
    data['cash'][0]['orderRef'] = 'missing-order'
    assert save(client, data).status_code == 400
    assert client.get('/api/book').json()['data']['orders'][0]['deposit'] == 25


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
    assert months['2026-09']['income'] == 25
    assert reports['total']['income'] == 99 and reports['total']['pending'] == 0


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


def test_final_payment_is_booked_in_actual_month_and_corrections_keep_dates(client):
    data = book()
    data['orders'][0]['date'] = '2026-09-28'
    data = save(client, data).json()['data']
    original_deposit = deepcopy(data['cash'][0])
    data['orders'][0].update(final=74, cut=1, status='已完成')
    response = save(client, data, receipt_date='2026-10-24')
    assert response.is_success, response.text
    data = response.json()['data']
    assert data['cash'][0] == original_deposit
    final = deepcopy(data['cash'][1])
    assert final['inc'] == 74 and final['type'] == '收入-尾款'
    assert final['date'] == '2026-10-24'
    reports = client.get('/api/reports').json()
    months = {r['month']: r for r in reports['months']}
    assert months['2026-09']['income'] == 25
    assert months['2026-10']['income'] == 74
    assert reports['total']['income'] == 99 and reports['total']['pending'] == 0
    data['orders'][0]['final'] = 73.5
    data = save(client, data, receipt_date='2026-11-02').json()['data']
    assert len(data['cash']) == 2
    assert data['cash'][1]['id'] == final['id'] and data['cash'][1]['date'] == final['date']
    assert data['cash'][1]['inc'] == 73.5
    data['orders'][0]['final'] = 0
    data = save(client, data).json()['data']
    assert data['cash'] == [original_deposit]
    assert client.get('/api/reports').json()['total']['income'] == 25


def test_existing_matching_cash_is_reused_and_expenses_are_untouched(client):
    data = book()
    data['cash'] = [
        {'id': 'old-deposit', 'date': '2026-10-24', 'type': '收入-定金',
         'orderNo': 'DD20261024-03', 'desc': '已登记定金', 'inc': 25, 'exp': 0, 'note': '原记录'},
        {'id': 'expense', 'date': '2026-10-24', 'type': '采购-布料',
         'orderNo': 'DD20261024-03', 'desc': '布料', 'inc': 0, 'exp': 10, 'note': ''},
    ]
    assert save(client, data).json()['data'] == data
    assert save(client, data).json()['data'] == data
    data['orders'][0]['deposit'] = 30
    saved = save(client, data, receipt_date='2026-10-25').json()['data']
    assert saved['cash'][0] == {**data['cash'][0], 'inc':30}
    assert saved['cash'][1] == data['cash'][1]
    assert len(saved['cash']) == 2
    assert client.get('/api/reports').json()['total']['net'] == 20


def test_edit_delete_and_reassign_cash_updates_corresponding_order(client):
    data = save(client, book()).json()['data']
    data['cash'][0]['inc'] = 20
    data = save(client, data).json()['data']
    assert data['orders'][0]['deposit'] == 20
    second = deepcopy(data['orders'][0])
    second.update(id='source-2', no='订单二', customer='另一位顾客', deposit=0)
    data['orders'].append(second)
    data = save(client, data).json()['data']
    data['cash'][0]['orderNo'] = '订单二'
    data = save(client, data).json()['data']
    assert [o['deposit'] for o in data['orders']] == [0, 20]
    data['cash'][0]['type'] = '收入-尾款'
    data = save(client, data).json()['data']
    assert data['orders'][1]['deposit'] == 0 and data['orders'][1]['final'] == 20
    data['cash'] = []
    data = save(client, data).json()['data']
    assert data['orders'][1]['final'] == 0
    assert client.get('/api/reports').json()['total']['income'] == 0


def test_restore_keeps_original_records_without_synthesizing_or_repeating_receipts(client):
    data = book()
    data['cash'] = [{'id': 'historic', 'date': '2026-10-24', 'type': '收入-定金',
                     'orderNo': 'DD20261024-03', 'desc': '历史记录', 'inc': 20, 'exp': 0, 'note': ''}]
    assert save(client, data, restore=True).json()['data'] == data
    assert save(client, data).json()['data'] == data
    data['orders'][0]['deposit'] = 30
    data = save(client, data, receipt_date='2026-10-25').json()['data']
    assert data['cash'][0]['id'] == 'historic' and data['cash'][0]['date'] == '2026-10-24'
    assert sum(r['inc'] for r in data['cash']) == 30 and len(data['cash']) == 1


@pytest.mark.parametrize('receipt_date', ['2026-10-23', 'not-a-date', '20261024'])
def test_invalid_receipt_date_rolls_back_entire_order_and_cash(client, receipt_date):
    initial = client.get('/api/book').json()
    assert save(client, book(), receipt_date=receipt_date).status_code == 400
    assert client.get('/api/book').json() == initial


def test_duplicate_display_order_numbers_are_rejected_before_receipt_linking(client):
    data = book()
    second = deepcopy(data['orders'][0])
    second['id'] = 'source-2'
    data['orders'].append(second)
    assert save(client, data).status_code == 400
    assert client.get('/api/book').json()['data']['cash'] == []


def test_edit_20_90_to_21_90_updates_same_receipt_and_original_month(client):
    data = book()
    data['orders'][0].update(date='2026-09-28', deposit=10, final=20.9, price=31.9)
    data = save(client, data, receipt_date='2026-09-30').json()['data']
    final = next(r for r in data['cash'] if r['type']=='收入-尾款')
    deposit = next(r for r in data['cash'] if r['type']=='收入-定金')
    for amount in (21.9, 19.9, 20.9, 21.9):
        data['orders'][0]['final'] = amount
        response = save(client, data, receipt_date='2026-10-24')
        assert response.is_success, response.text
        data = response.json()['data']
        assert len(data['cash']) == 2
        assert next(r for r in data['cash'] if r['type']=='收入-尾款') == {**final, 'inc':amount}
        assert next(r for r in data['cash'] if r['type']=='收入-定金') == deposit
        assert save(client, data).json()['data'] == data
    reports = client.get('/api/reports').json()
    assert reports['total']['income'] == 31.9
    assert len(reports['months']) == 1 and reports['months'][0]['month'] == '2026-09'
    assert reports['months'][0]['income'] == 31.9


def test_customer_style_and_note_edits_update_linked_income_without_changing_expenses(client):
    data = save(client, book()).json()['data']
    receipt = deepcopy(data['cash'][0])
    expense = {'id':'cloth', 'date':'2026-10-24', 'type':'采购-布料',
               'orderNo':'DD20261024-03', 'desc':'采购说明', 'exp':8, 'inc':0, 'note':'采购备注'}
    data['cash'].append(expense)
    data = save(client, data).json()['data']
    data['orders'][0].update(customer='新顾客', style='新款式', no='新单号', note='改用蓝色布料')
    response = save(client, data)
    assert response.is_success, response.text
    data = response.json()['data']
    updated = next(r for r in data['cash'] if r['id']==receipt['id'])
    assert updated == {**receipt, 'desc':'新顾客 · 新款式', 'orderNo':'新单号',
                       'note':'订单定金自动登记 ｜ 改用蓝色布料'}
    assert next(r for r in data['cash'] if r['id']=='cloth') == {**expense, 'orderNo':'新单号'}
    # Keep a cash-specific note rather than overwriting it with an order note.
    updated['note'] = '收款流水的专用备注'
    data = save(client, data).json()['data']
    data['orders'][0]['note'] = '再次改色'
    data = save(client, data).json()['data']
    assert next(r for r in data['cash'] if r['id']==receipt['id'])['note'] == '收款流水的专用备注'
