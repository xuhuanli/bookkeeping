"""Reference-shaped books with automatic order receipt synchronization."""
from copy import deepcopy
from datetime import date
import re
from uuid import NAMESPACE_URL, uuid4, uuid5

from . import ledger
from .legacy_import import STATUSES
from .models import OrderInput, StyleInput, plain, today

LABELS = {value: key for key, value in STATUSES.items()}


def to_reference(state):
    sequence = deepcopy(state.get('sequence', {}))
    orders = []
    numbers = {}
    for order in state['orders']:
        number = order.get('no', order['id'])
        numbers[order['id']] = number
        legacy = order.get('legacyImport', {})
        orders.append({
            'id': order.get('referenceId') or legacy.get('sourceId') or order['id'],
            'no': number, 'date': order['date'], 'customer': order['customer'],
            'style': order['style'], 'phone': order.get('referencePhone', legacy.get('phone', '')),
            'address': order['address'], 'tracking': order['tracking'],
            'price': order['price'], 'deposit': order['deposit'], 'final': order['final'],
            'cut': order['discount'], 'status': LABELS.get(order['status'], '已收尾款-待发货' if order['status'] == 'shipped' else '已收定金-待制作'),
            'note': order['note'], 'ph': list(order['photos']),
        })
        match = re.fullmatch(r'DD(\d{8})-(\d+)', number)
        if match:
            key = 'o' + match[1]
            sequence[key] = max(sequence.get(key, 0), int(match[2]))
    cash = [{
        'id': row['id'], 'date': row['date'], 'type': row['category'],
        'orderNo': row.get('referenceOrderNo', numbers.get(row.get('orderId'), row.get('orderId', ''))),
        'desc': row['title'], 'exp': row['amount'] if row['type'] == 'expense' else 0,
        'inc': row['amount'] if row['type'] == 'income' else 0, 'note': row.get('note', ''),
    } for row in state['transactions']]
    return {'orders': orders, 'cash': cash, 'seq': sequence,
            'styles': [{'name': s['name'], 'price': s.get('price')} for s in state['styles']]}


def sync_receipts(state, previous, receipt_date=None):
    """Order amount edits win; cash-only amount edits flow back to the order.

    Existing receipt IDs and dates survive amount corrections. Only the first
    deposit/final receipt creates a row; later edits update that same receipt.
    Unchanged historical mismatches are preserved rather than silently rewritten.
    """
    old_orders = {o['id']: o for o in previous['orders']}

    def receipts(snapshot, identifier, kind):
        return [r for r in snapshot['transactions'] if r.get('orderId') == identifier
                and r['type'] == 'income' and r.get('kind') == kind]

    for order in state['orders']:
        old = old_orders.get(order['id'])
        for kind, label in (('deposit', '定金'), ('final', '尾款')):
            rows = receipts(state, order['id'], kind)
            before = receipts(previous, order['id'], kind)
            if old and (old['customer'], old['style']) != (order['customer'], order['style']):
                for row in rows:
                    row['title'] = (order['customer'] + ' · ' + order['style'])[:200]
            if old and old['note'] != order['note']:
                automatic_note = '订单' + label + '自动登记'
                previous_note = (automatic_note + (' ｜ ' + old['note'] if old['note'] else ''))[:2000]
                for row in rows:
                    if row.get('note') in (automatic_note, previous_note):
                        row['note'] = (automatic_note + (' ｜ ' + order['note'] if order['note'] else ''))[:2000]
            desired = ledger.cents(order[kind])
            if old is None or desired != ledger.cents(old[kind]):
                difference = desired - sum(ledger.cents(r['amount']) for r in rows)
                if difference > 0:
                    if rows:
                        latest = max(rows, key=lambda r: r['date'])
                        latest['amount'] = (ledger.cents(latest['amount']) + difference) / 100
                    else:
                        day = receipt_date or (order['date'] if old is None else today())
                        date.fromisoformat(day)
                        ledger.check(day >= order['date'], '收款日期不能早于下单日期。')
                        state['transactions'].append({
                            'id': str(uuid4()), 'date': day, 'type': 'income', 'kind': kind,
                            'category': '收入-' + label,
                            'title': (order['customer'] + ' · ' + order['style'])[:200],
                            'amount': difference / 100, 'orderId': order['id'],
                            'referenceOrderNo': order['no'],
                            'note': ('订单' + label + '自动登记' + (' ｜ ' + order['note'] if order['note'] else ''))[:2000],
                        })
                elif difference < 0:
                    reduction = -difference
                    for row in sorted(rows, key=lambda r: r['date'], reverse=True):
                        take = min(ledger.cents(row['amount']), reduction)
                        row['amount'] = (ledger.cents(row['amount']) - take) / 100
                        reduction -= take
                        if not reduction:
                            break
                    state['transactions'] = [r for r in state['transactions'] if ledger.cents(r['amount']) > 0]
            elif {r['id']: ledger.cents(r['amount']) for r in rows} != {r['id']: ledger.cents(r['amount']) for r in before}:
                order[kind] = sum(ledger.cents(r['amount']) for r in rows) / 100
        order['received'] = (ledger.cents(order['deposit']) + ledger.cents(order['final'])) / 100
    return ledger.validate(state)


def from_reference(source, previous, *, synchronize=True, receipt_date=None):
    source = deepcopy(source)
    # Accept portable backups exported by the previous local UI as well.
    if source.get('app') == 'stitch-ledger':
        source = source['data']
    if source.get('version') == 2 and isinstance(source.get('transactions'), list):
        ledger.validate(source)
        source['accountingMode'] = 'manual'
        return ledger.validate(source)
    for key in ('orders', 'cash', 'styles'):
        ledger.check(isinstance(source.get(key), list) and len(source[key]) <= 50000, '备份结构不完整或记录过多。')
    sequence = source.get('seq', {})
    ledger.check(isinstance(sequence, dict) and len(sequence) <= 50000, '订单编号记录无效。')
    ledger.check(all(isinstance(k, str) and type(v) is int and 0 <= v <= 999999999 for k, v in sequence.items()), '订单编号记录无效。')
    state = {**ledger.empty(), 'accountingMode': 'manual', 'sequence': sequence}
    old_orders = {o.get('referenceId') or o.get('legacyImport', {}).get('sourceId') or o['id']: o for o in previous['orders']}
    numbers = {}
    for row in source['orders']:
        ledger.check(isinstance(row, dict) and row.get('status') in STATUSES, '订单状态不正确。')
        identifier = row['id']
        ledger.check(isinstance(identifier, str) and re.fullmatch(r'[\w.\-]{1,100}', identifier), '订单编号无效。')
        ledger.check(isinstance(row['no'], str) and 0 < len(row['no']) <= 100, '请填写订单编号。')
        ledger.check(row['no'] not in numbers, '订单编号重复，请换一个编号。')
        old = old_orders.get(identifier, {})
        phone = row.get('phone', old.get('referencePhone', old.get('legacyImport', {}).get('phone', '')))
        ledger.check(isinstance(phone, str) and len(phone) <= 100, '联系电话格式不正确。')
        model = OrderInput.model_validate({
            'id': old.get('id', identifier), 'date': row['date'], 'customer': row['customer'],
            'style': row['style'], 'price': row['price'], 'deposit': row.get('deposit', 0),
            'final': row.get('final', 0), 'discount': row.get('cut', 0),
            'status': STATUSES[row['status']], 'address': row.get('address', ''),
            'tracking': row.get('tracking', ''), 'note': row.get('note', ''),
            'photos': row.get('ph', []), 'cost': old.get('cost', 0), 'due': old.get('due', ''),
            'channel': old.get('channel', ''), 'styleIds': old.get('styleIds', []),
            'product': old.get('product'), 'receiptDate': row['date'],
        })
        order = {**old, **plain(model), 'no': row['no'], 'referenceId': identifier, 'referencePhone': phone}
        order.pop('receiptDate', None)
        order['received'] = (ledger.cents(order['deposit']) + ledger.cents(order['final'])) / 100
        completed = old.get('completedDate', '')
        order['completedDate'] = completed if old.get('status') == order['status'] and completed >= order['date'] else ''
        order['discountHistory'] = []
        if order.get('legacyImport'):
            order['legacyImport']['undatedDiscount'] = order['discount']
        state['orders'].append(order)
        numbers.setdefault(row['no'], order['id'])
    old_cash = {r['id']: r for r in previous['transactions']}
    old_numbers = {o['id']: o.get('no', o['id']) for o in previous['orders']}
    new_numbers = {o['id']: o['no'] for o in state['orders']}
    for row in source['cash']:
        ledger.check(isinstance(row, dict), '收支记录无效。')
        income, expense = ledger.cents(row.get('inc', 0)), ledger.cents(row.get('exp', 0))
        ledger.check((income > 0 and expense == 0) or (expense > 0 and income == 0), '同一笔流水只能填写一种正金额。')
        number = row.get('orderNo', '')
        ledger.check(isinstance(number, str) and len(number) <= 100, '关联订单编号无效。')
        saved = {
            **old_cash.get(row['id'], {}), 'id': row['id'], 'date': row['date'],
            'type': 'income' if income else 'expense', 'category': row['type'],
            'title': row['desc'], 'amount': (income or expense) / 100,
            'orderId': numbers.get(number, ''), 'referenceOrderNo': number, 'note': row.get('note', ''),
        }
        # Renaming an order must not disconnect its existing receipts. Explicitly
        # changing the cash row's selected order still reassigns it normally.
        old_row = old_cash.get(row['id'], {})
        old_number = old_row.get('referenceOrderNo', old_numbers.get(old_row.get('orderId'), ''))
        if number and number == old_number and old_row.get('orderId') in new_numbers:
            saved['orderId'] = old_row['orderId']
            saved['referenceOrderNo'] = new_numbers[saved['orderId']]
        if income:
            saved['kind'] = 'deposit' if saved['category'] == '收入-定金' else 'final'
        state['transactions'].append(saved)
    old_styles = {s['name']: s for s in previous['styles']}
    for row in source['styles']:
        if isinstance(row, str):
            row = {'name': row, 'price': 0}
        model = StyleInput.model_validate(row)
        style = plain(model)
        old = old_styles.get(style['name'], {})
        state['styles'].append({**old, **style, 'cost': old.get('cost', 0),
                                'id': old.get('id') or str(uuid5(NAMESPACE_URL, 'handmade-bags/style/' + style['name']))})
    ledger.validate(state)
    return sync_receipts(state, previous, receipt_date) if synchronize else state
