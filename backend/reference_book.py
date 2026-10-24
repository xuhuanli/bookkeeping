"""The reference app's independent order and cash books, backed by local SQLite."""
from copy import deepcopy
import re
from uuid import NAMESPACE_URL, uuid5

from . import ledger
from .legacy_import import STATUSES
from .models import OrderInput, StyleInput, plain

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


def from_reference(source, previous):
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
    return ledger.validate(state)
