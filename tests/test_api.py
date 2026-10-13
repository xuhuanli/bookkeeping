import base64
from copy import deepcopy
import io
import re

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
import pytest

from backend.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'data', tmp_path/'images', tmp_path/'frontend')) as client:
        yield client


def order(**changes):
    return {'date':'2026-09-28','customer':'测试顾客','style':'拼布包 · 小号','price':66.7,'deposit':25,'receiptDate':'2026-09-28',**changes}


def payload(response):
    assert response.is_success, response.text
    return response.json()['data']


def image_bytes():
    output=io.BytesIO()
    Image.new('RGB',(2200,1000),'#dae4c9').save(output,'PNG')
    return output.getvalue()


def test_deposit_final_discount_and_month_end(client):
    state=payload(client.post('/api/orders',json=order()))
    o=state['orders'][0]
    assert o['id']=='DD20260928-01'
    assert o['received']==25 and o['final']==0
    state=payload(client.post('/api/transactions',json={'date':'2026-10-02','type':'income','category':'收入-尾款','title':'尾款到账','amount':41,'orderId':o['id']}))
    changed={**order(), 'id':o['id'],'final':41,'discount':.7,'receiptDate':'2026-10-02'}
    state=payload(client.put('/api/orders/'+o['id'],json=changed))
    assert state['orders'][0]['received']==66
    assert len(state['transactions'])==2  # Discount is not a receipt.
    reports=client.get('/api/reports').json()
    months={m['month']:m for m in reports['months']}
    assert months['2026-09']['pending']==41.7
    assert months['2026-10']['pending']==0
    assert reports['total']['income']==66


def test_edit_reduces_latest_payment_and_keeps_original_dates(client):
    state=payload(client.post('/api/orders',json=order(price=100)))
    identifier=state['orders'][0]['id']
    for day,value in [('2026-10-01',20),('2026-10-02',30)]:
        payload(client.post('/api/transactions',json={'date':day,'type':'income','category':'收入-尾款','title':'尾款','amount':value,'orderId':identifier}))
    state=payload(client.put('/api/orders/'+identifier,json=order(id='定制-001',price=100,final=35,receiptDate='2026-10-03')))
    assert sorted((t['date'],t['amount']) for t in state['transactions'])==[('2026-09-28',25),('2026-10-01',20),('2026-10-02',15)]
    assert all(t['orderId']=='定制-001' for t in state['transactions'])
    last=next(t for t in state['transactions'] if t['date']=='2026-10-02')
    state=payload(client.delete('/api/transactions/'+last['id']))
    assert state['orders'][0]['final']==20


def test_overpayment_and_bad_dates_do_not_change_state(client):
    initial=payload(client.post('/api/orders',json=order()))
    identifier=initial['orders'][0]['id']
    for body in [order(price=10),order(receiptDate='2026-09-27'),order(deposit=-1),order(price=66.701)]:
        assert client.post('/api/orders',json=body).status_code in (400,422)
    assert client.post('/api/transactions',json={'date':'2026-10-01','type':'income','category':'收入-尾款','title':'超收','amount':50,'orderId':identifier}).status_code==400
    assert payload(client.get('/api/ledger'))==initial


def test_two_devices_revision_conflict_is_atomic(client):
    first=client.post('/api/orders',json=order(),headers={'X-Ledger-Revision':'0'})
    assert first.status_code==201
    second=client.post('/api/orders',json=order(customer='另一台设备'),headers={'X-Ledger-Revision':'0'})
    assert second.status_code==409
    assert client.get('/api/ledger').json()['revision']==1
    assert len(payload(client.get('/api/ledger'))['orders'])==1


def test_delete_order_keeps_expenses_and_can_undo(client):
    state=payload(client.post('/api/orders',json=order()))
    identifier=state['orders'][0]['id']
    before=payload(client.post('/api/transactions',json={'date':'2026-10-01','type':'expense','category':'采购-工具','title':'裁剪工具','amount':15,'orderId':identifier}))
    state=payload(client.delete('/api/orders/'+identifier))
    assert not state['orders'] and len(state['transactions'])==1
    assert state['transactions'][0]['orderId']==''
    assert payload(client.post('/api/undo'))==before
    assert client.post('/api/clear',json={'confirmation':'随便'}).status_code==422
    cleared=payload(client.post('/api/clear',json={'confirmation':'清空'}))
    assert not cleared['orders']
    assert payload(client.post('/api/undo'))==before


def test_image_upload_and_portable_backup(client,tmp_path):
    response=client.post('/api/images',files={'file':('../../escape.png',image_bytes(),'image/png')})
    assert response.status_code==201
    url=response.json()['url']
    assert re.fullmatch(r'/images/[a-f0-9]{32}\.jpg',url)
    served=client.get(url)
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.format=='JPEG' and max(image.size)==1600
    payload(client.post('/api/orders',json=order(photos=[url])))
    backup=client.get('/api/backup').json()
    assert backup['data']['orders'][0]['photos'][0].startswith('data:image/jpeg;base64,')
    with TestClient(create_app(tmp_path/'other-data',tmp_path/'other-images',tmp_path/'missing-ui')) as other:
        state=payload(other.post('/api/restore',json=backup))
        new_url=state['orders'][0]['photos'][0]
        assert new_url!=url and other.get(new_url).status_code==200
        assert state['orders'][0]['deposit']==25
    assert client.post('/api/images',files={'file':('fake.jpg',b'not an image','image/jpeg')}).status_code==400
    assert client.post('/api/orders',json=order(photos=['/images/../../secret'])).status_code==400
    assert client.post('/api/orders',json=order(photos=[url]*7)).status_code==422


def test_restore_invalid_snapshot_rolls_back_and_cleans_files(client,tmp_path):
    initial=payload(client.post('/api/orders',json=order()))
    backup=client.get('/api/backup').json()
    corrupt=deepcopy(backup);corrupt['data']['orders'][0]['received']=999
    assert client.post('/api/restore',json=corrupt).status_code==400
    corrupt_date=deepcopy(backup);corrupt_date['data']['orders'][0]['completedDate']=123
    assert client.post('/api/restore',json=corrupt_date).status_code==400
    assert payload(client.get('/api/ledger'))==initial
    assert client.post('/api/restore',json={'data':{'version':2,'orders':[{}],'transactions':[],'styles':[]}}).status_code==400
    backup['data']['orders'][0]['photos']=['data:image/png;base64,'+base64.b64encode(image_bytes()).decode()]
    count=len(list((tmp_path/'images').glob('*')))
    assert client.post('/api/restore',json=backup,headers={'X-Ledger-Revision':'0'}).status_code==409
    assert len(list((tmp_path/'images').glob('*')))==count
    assert payload(client.get('/api/ledger'))==initial


def test_persist_restart_summary_categories_and_real_excel(tmp_path):
    data,images=tmp_path/'data',tmp_path/'images'
    with TestClient(create_app(data,images,tmp_path/'missing')) as client:
        payload(client.post('/api/styles',json={'name':'束口包','price':None}))
        payload(client.post('/api/orders',json=order(customer='=1+1')))
        for category,amount in [('采购-布料',10),('采购-耗材辅料',5),('采购-工具',3),('每周合并发货运费',2)]:
            payload(client.post('/api/transactions',json={'date':'2026-09-28','type':'expense','category':category,'title':'=HYPERLINK("http://example.com")','amount':amount}))
        saved=payload(client.get('/api/ledger'))
    with TestClient(create_app(data,images,tmp_path/'missing')) as restarted:
        assert payload(restarted.get('/api/ledger'))==saved
        report=restarted.get('/api/reports').json()['total']
        assert report['income']==25 and report['purchase']==18 and report['shipping']==2 and report['net']==5
        export=restarted.get('/api/export.xlsx')
        assert export.content[:2]==b'PK'
        workbook=load_workbook(io.BytesIO(export.content))
        assert workbook.sheetnames==['订单台账','收支明细','月度汇总','常用款式']
        assert workbook['订单台账']['C2'].data_type=='s'
        assert workbook['收支明细']['D2'].data_type=='s'
        assert workbook['月度汇总']['F2'].value==5


def test_style_changes_preserve_order_and_progress_counts(client):
    from backend.models import today
    state=payload(client.post('/api/styles',json={'name':'束口包','price':66.7}))
    style_id=state['styles'][0]['id']
    state=payload(client.post('/api/orders',json=order(date=today(),receiptDate=today(),styleIds=[style_id])))
    identifier=state['orders'][0]['id']
    state=payload(client.put('/api/styles/'+style_id,json={'name':'束口包 · 新款','price':88}))
    assert state['orders'][0]['style']=='拼布包 · 小号' and state['orders'][0]['price']==66.7
    state=payload(client.delete('/api/styles/'+style_id))
    assert not state['styles'] and len(state['orders'])==1
    state=payload(client.patch('/api/orders/'+identifier+'/status',json={'status':'delivered'}))
    assert state['orders'][0]['completedDate']==today()
    assert client.get('/api/reports').json()['total']['completed']==1
    state=payload(client.patch('/api/orders/'+identifier+'/status',json={'status':'making'}))
    assert state['orders'][0]['completedDate']==''
    assert client.get('/api/reports').json()['total']['completed']==0
