"""Stage the user-supplied Excel data without fabricating historical cash flow."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collections import Counter, defaultdict, deque
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5
from backend.database import Database
from backend.reference_book import from_reference, to_reference
from backend import ledger
from backend.images import check_photos

ROOT=Path(__file__).resolve().parents[2]
FOLDER=Path(__file__).resolve().parent
SOURCE=Path('/Users/xuhuanli/Downloads/手作包包记账表_2026-10-24.xlsx')
SHA='a76ab71986c9872e08be6408091b717cc56c83e72811d749c1f9abdd6bbd45d6'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SHA, 'Excel 已发生变化，请重新读取。'
raw=json.loads((FOLDER/'source-values.json').read_text())
assert raw['订单台账'][1]==['下单日期','订单编号','客户名称/昵称','收货信息（姓名/电话/地址）','快递单号','包包款式/规格','订单报价（元）','已收定金（元）','已收尾款（元）','抹零/优惠（元）','待收尾款（元）','订单状态','备注']
assert raw['收支明细'][1]==['日期','收支类型','对应订单编号（可选）','物品/事项说明','支出金额','收入金额','备注']

def rows(sheet, width):
    for index,row in enumerate(raw[sheet][2:],3):
        if row and row[0]=='合计':
            break
        assert len(row)==width and isinstance(row[0],str), f'{sheet} 第 {index} 行不完整'
        assert date.fromisoformat(row[0]).isoformat()==row[0]
        yield index,row

def text(value):
    return '' if value is None else str(value)

def money(value):
    value=Decimal(str(value or 0))
    rounded=value.quantize(Decimal('0.01'))
    assert value.is_finite() and abs(value-rounded)<Decimal('0.0000001') and value>=0
    return float(rounded)

previous,revision=Database(ROOT/'data/bookkeeping.sqlite3').read()
old_ref=to_reference(previous)
old_by_no=defaultdict(list)
for order in old_ref['orders']:
    old_by_no[order['no']].append(order)
source_orders=list(rows('订单台账',13))
source_cash=list(rows('收支明细',7))
used_numbers={text(row[1]) for index,row in source_orders}
seen=Counter()
renumbered=[]
orders=[]
source_lookup=defaultdict(list)
for index,row in source_orders:
    original_no=text(row[1]); number=original_no
    assert original_no
    if seen[original_no]:
        prefix='DD'+row[0].replace('-','')+'-'
        serial=1
        while prefix+f'{serial:02}' in used_numbers:
            serial+=1
        number=prefix+f'{serial:02}'
        used_numbers.add(number)
        renumbered.append({'sheetRow':index,'date':row[0],'customer':row[2],'oldNumber':original_no,'newNumber':number})
    seen[original_no]+=1
    old_matches=[o for o in old_by_no[original_no] if o['date']==row[0] and o['customer']==row[2]]
    if not old_matches and len(old_by_no[original_no])==1 and seen[original_no]==1:
        old_matches=old_by_no[original_no]
    assert len(old_matches)<=1
    old=old_matches[0] if old_matches else {}
    order={
        'id':old.get('id') or str(uuid5(NAMESPACE_URL,'handmade-bags/excel/order/'+number)),
        'no':number,'date':row[0],'customer':text(row[2]),'address':text(row[3]),
        'tracking':text(row[4]),'style':text(row[5]),'price':money(row[6]),
        'deposit':money(row[7]),'final':money(row[8]),'cut':money(row[9]),
        'status':text(row[11]),'note':text(row[12]),'phone':old.get('phone',''),
        'ph':deepcopy(old.get('ph',[])),
    }
    assert abs(max(0,order['price']-order['deposit']-order['final']-order['cut'])-money(row[10]))<0.0000001
    orders.append(order)
    source_lookup[original_no].append(order)

# Reuse stable transaction identities for unchanged rows or unique corrections.
base_keys=lambda row:(row['date'],row['type'],row['orderNo'],row['desc'])
old_exact=defaultdict(deque)
old_base=defaultdict(list)
for row in old_ref['cash']:
    old_exact[(*base_keys(row),ledger.cents(row['exp']),ledger.cents(row['inc']),row['note'])].append(row['id'])
    old_base[base_keys(row)].append(row['id'])
used_ids=set(); occurrences=Counter(); unresolved=[]; cash=[]; reassigned=[]
for index,row in source_cash:
    original_no=text(row[2]); number=original_no
    income=money(row[5]); expense=money(row[4])
    candidates=source_lookup.get(original_no,[])
    if len(candidates)>1:
        # Date plus distinct installment amount uniquely identify this file's
        # three deposits using the repeated number. Do not infer unknown matches.
        kind='deposit' if row[1]=='收入-定金' else 'final'
        same_day=[o for o in candidates if o['date']==row[0] and ledger.cents(o[kind])==ledger.cents(income)]
        assert len(same_day)==1, f'收支明细 第 {index} 行的重复订单编号无法唯一关联'
        number=same_day[0]['no']
        if number!=original_no:
            reassigned.append({'sheetRow':index,'oldNumber':original_no,'newNumber':number,'amount':income})
    elif number and not candidates:
        unresolved.append({'sheetRow':index,'orderNo':number})
    rec={'date':row[0],'type':text(row[1]),'orderNo':number,'desc':text(row[3]),
         'exp':expense,'inc':income,'note':text(row[6])}
    # Compare against the source number before renumbering.
    old_key=(row[0],text(row[1]),original_no,text(row[3]))
    exact=(*old_key,ledger.cents(expense),ledger.cents(income),text(row[6]))
    pool=old_exact[exact]
    while pool and pool[0] in used_ids: pool.popleft()
    identifier=pool.popleft() if pool else None
    if identifier is None:
        remaining=[i for i in old_base[old_key] if i not in used_ids]
        identifier=remaining[0] if len(remaining)==1 else None
    if identifier is None:
        packed=json.dumps([*old_key,ledger.cents(expense),ledger.cents(income),text(row[6])],ensure_ascii=False)
        occurrences[packed]+=1
        identifier=str(uuid5(NAMESPACE_URL,'handmade-bags/excel/cash/'+packed+'/'+str(occurrences[packed])))
    assert identifier not in used_ids
    used_ids.add(identifier)
    rec['id']=identifier
    cash.append(rec)

book={'orders':orders,'cash':cash,'seq':old_ref['seq'],'styles':old_ref['styles']}
state=from_reference(book,previous,synchronize=False)
check_photos(state,ROOT/'images')
assert len(state['orders'])==len(source_orders)==37
assert len(state['transactions'])==len(source_cash)==128
assert len(state['styles'])==len(previous['styles'])==21
# Exact source data is authoritative; preserve historical inconsistencies rather
# than assigning unknown payment dates or creating income absent from the sheet.
report=ledger.summary(state)
assert report['income']==1411.50 and report['expense']==1440.17 and report['net']==-28.67
assert report['pending']==407.90 and report['count']==37 and report['completed']==28
assert report['discount']==22.40
assert [o['photos'] for o in state['orders'][:34]]==[o['photos'] for o in previous['orders']]
# Verify a subsequent ordinary save does not generate duplicate/missing historical receipts.
roundtrip=from_reference(to_reference(state),state)
assert roundtrip['transactions']==state['transactions']
assert [(o['deposit'],o['final']) for o in roundtrip['orders']]==[(o['deposit'],o['final']) for o in state['orders']]
# Verify all summary rows in the supplied workbook against the exact imported values.
for row in raw['月度汇总']:
    if row and row[0] in ('2026-09','2026-10'):
        summary=ledger.summary(state,row[0])
        assert [summary[k] for k in ('purchase','shipping','expense','income','discount','net')]==[money(v) if i!=5 else float(Decimal(str(v)).quantize(Decimal('.01'))) for i,v in enumerate(row[1:7])]

source_totals={}
for number,kind in [(o['id'],kind) for o in state['orders'] for kind in ('deposit','final')]:
    source_totals[number,kind]=sum(ledger.cents(r['amount']) for r in state['transactions'] if r.get('orderId')==number and r['type']=='income' and r.get('kind')==kind)
gaps=[]
for o in state['orders']:
    delta={kind:(ledger.cents(o[kind])-source_totals[o['id'],kind])/100 for kind in ('deposit','final')}
    if any(delta.values()): gaps.append({'orderNo':o['no'],'customer':o['customer'],'depositDifference':delta['deposit'],'finalDifference':delta['final']})
report={
    'source':str(SOURCE),'sourceSha256':SHA,'previousRevision':revision,
    'counts':{'orders':len(orders),'transactions':len(cash),'styles':len(state['styles'])},
    'orderDateRange':[min(o['date'] for o in orders),max(o['date'] for o in orders)],
    'cashDateRange':[min(r['date'] for r in cash),max(r['date'] for r in cash)],
    'summary':report,'renumberedOrders':renumbered,'reassignedCash':reassigned,
    'unmatchedOrderNumbers':unresolved,'historicalReceiptGaps':gaps,
    'historicalReceiptDifference':(sum(ledger.cents(o['received']) for o in state['orders'])-sum(ledger.cents(r['amount']) for r in state['transactions'] if r['type']=='income'))/100,
    'generatedHistoricalReceipts':0,'previousPhotosPreserved':True,
}
(FOLDER/'candidate-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
(FOLDER/'import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:report[k] for k in ('previousRevision','counts','summary','orderDateRange','cashDateRange','renumberedOrders','reassignedCash','unmatchedOrderNumbers','historicalReceiptDifference')},ensure_ascii=False))
