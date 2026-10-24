"""One-time, user-authorized historical receipts, dated 2026-10-24."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend import ledger
from backend.database import Database
from backend.images import embed_photos

TARGETS = {
    'DD20260929-01': ('GRACIE、', 'final', 5300),
    'DD20260929-02': ('不困', 'final', 2190),
    'DD20260929-03': ('豆', 'final', 4000),
    'DD20261001-01': ('小兔降临', 'final', 2190),
    'DD20261001-03': ('X2', 'final', 5480),
    'DD20261001-04': ('Magic', 'final', 2280),
    'DD20261004-01': ('I', 'final', 2200),
    'DD20261004-02': ('煎荷包蛋', 'final', 4080),
    'DD20261004-04': ('7.', 'final', 2190),
    'DD20261005-01': ('小也', 'final', 3430),
    'DD20261005-02': ('dionysus', 'final', 2190),
    'DD20261008-01': ('nine', 'final', 7200),
    'DD20261016-01': ('L', 'deposit', 2500),
}
DAY = '2026-10-24'
path = ROOT / 'data/bookkeeping.sqlite3'
assert path.is_file()
database = Database(path)
state, revision = database.read()
by_number = {o.get('no', o['id']): o for o in state['orders']}
receipts = []
for number, (customer, kind, expected) in TARGETS.items():
    order = by_number[number]
    assert order['customer'] == customer, f'{number}: customer changed; recheck required'
    existing = sum(ledger.cents(t['amount']) for t in state['transactions']
                   if t.get('orderId') == order['id'] and t['type'] == 'income' and t.get('kind') == kind)
    gap = ledger.cents(order[kind]) - existing
    assert gap in (0, expected), f'{number}: amount changed; recheck required'
    if not gap:
        continue
    label = '定金' if kind == 'deposit' else '尾款'
    receipts.append({
        'id': str(uuid4()), 'date': DAY, 'type': 'income', 'kind': kind,
        'category': '收入-' + label, 'amount': gap / 100,
        'orderId': order['id'], 'referenceOrderNo': number,
        'title': (customer + ' · ' + order['style'])[:200],
        'note': '历史收款补录；按用户指定的2026-10-24入账，实际收款日期未知。',
    })
if not receipts:
    print(json.dumps({'added': 0, 'message': 'All 13 receipts already recorded; no changes.'}))
    raise SystemExit(0)
assert len(receipts) == 13 and sum(ledger.cents(r['amount']) for r in receipts) == 45230
candidate = deepcopy(state)
candidate['transactions'].extend(receipts)
ledger.validate(candidate)
income = lambda s: sum(ledger.cents(t['amount']) for t in s['transactions'] if t['type'] == 'income')
received = lambda s: sum(ledger.cents(o['deposit']) + ledger.cents(o['final']) for o in s['orders'])
assert income(candidate) == received(candidate)

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup_dir = ROOT / 'data/backups'
backup_dir.mkdir(exist_ok=True)
backup = backup_dir / ('before-historical-receipts-' + stamp + '.sqlite3')
with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as source:
    with sqlite3.connect(backup) as destination:
        source.backup(destination)
portable = {'app': 'stitch-ledger', 'version': 2, 'exportedAt': datetime.now().astimezone().isoformat(),
            'data': embed_photos(deepcopy(state), ROOT / 'images')}
backup.with_suffix('.json').write_text(json.dumps(portable, ensure_ascii=False, indent=2))

def apply(current):
    assert current == state, 'Ledger changed; recheck required'
    return candidate

saved, new_revision = database.mutate(apply, revision=revision, undo=True)
persisted, stored_revision = database.read()
assert persisted == saved and stored_revision == new_revision
assert saved['orders'] == state['orders'] and saved['styles'] == state['styles']
assert saved['transactions'][:-13] == state['transactions']
assert income(saved) == received(saved)
report = {
    'date': DAY, 'beforeRevision': revision, 'afterRevision': new_revision,
    'added': len(receipts), 'addedAmount': 452.30,
    'incomeBefore': income(state) / 100, 'incomeAfter': income(saved) / 100,
    'orderReceived': received(saved) / 100,
    'cashCountBefore': len(state['transactions']), 'cashCountAfter': len(saved['transactions']),
    'ordersUnchanged': True, 'oldCashUnchanged': True, 'stylesUnchanged': True,
    'backup': str(backup), 'portableBackup': str(backup.with_suffix('.json')), 'receipts': receipts,
}
Path(__file__).with_name('report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != 'receipts'}, ensure_ascii=False))
