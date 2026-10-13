"""Convert the handmade-bag app's orders/cash/styles backup without inventing receipts."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from . import ledger
from .models import CATEGORIES, OrderInput, StyleInput, plain

FORMAT = 'handmade-bags'
STATUSES = {'已收定金-待制作': 'booked', '已收尾款-待发货': 'ready', '已完成': 'delivered'}


def normalize_backup(body):
    if body.get('app') and body['app'] != 'stitch-ledger':
        raise ValueError('请选择针线小账或手作包包记账的 JSON 备份文件。')
    source = deepcopy(body.get('data', body))
    if isinstance(source, dict) and 'cash' in source and 'version' not in source:
        return convert(source)
    return source


def convert(source):
    for key in ('orders', 'cash', 'styles'):
        ledger.check(isinstance(source.get(key), list) and len(source[key]) <= 50000, '旧版备份结构不完整或记录过多。')
    state = ledger.empty()
    expected = {}
    for row in source['orders']:
        ledger.check(isinstance(row, dict) and row.get('status') in STATUSES, '旧版订单状态不正确。')
        identifier = row['no']
        ledger.check(isinstance(identifier, str) and identifier and identifier not in expected, '旧版订单编号无效或重复。')
        phone = row.get('phone', '')
        address = row.get('address', '')
        ledger.check(isinstance(phone, str) and isinstance(address, str), '旧版收货信息不正确。')
        contact = '\n'.join(filter(None, [f'电话：{phone}' if phone and phone not in address else '', address]))
        model = OrderInput.model_validate({
            'id': identifier, 'date': row['date'], 'customer': row['customer'], 'style': row['style'],
            'price': row['price'], 'deposit': row['deposit'], 'final': row['final'],
            'discount': row.get('cut', 0), 'status': STATUSES[row['status']],
            'address': contact, 'tracking': row.get('tracking', ''), 'note': row.get('note', ''),
            'photos': row.get('ph', []), 'receiptDate': row['date'],
        })
        order = plain(model)
        order.pop('receiptDate')
        received = ledger.cents(order['deposit']) + ledger.cents(order['final'])
        order.update(received=received / 100, completedDate='', discountHistory=[])
        # The old format has current totals and status, but no completion/discount dates.
        # Keep those facts separate from dated history rather than assigning an arbitrary day.
        order['legacyImport'] = {
            'format': FORMAT, 'sourceId': row['id'], 'sourceExtraId': row.get('_id', ''),
            'phone': phone, 'address': address,
            'overpaymentCents': max(0, received + ledger.cents(order['discount']) - ledger.cents(order['price'])),
            'undatedDiscount': order['discount'],
            'completedDateUnknown': order['status'] == 'delivered',
        }
        state['orders'].append(order)
        expected[identifier] = (ledger.cents(order['deposit']), ledger.cents(order['final']))

    for row in source['cash']:
        ledger.check(isinstance(row, dict) and row.get('type') in CATEGORIES, '旧版流水分类不正确。')
        income, expense = ledger.cents(row['inc']), ledger.cents(row['exp'])
        ledger.check((income > 0 and expense == 0) or (expense > 0 and income == 0), '旧版流水需要且只能填写一种正金额。')
        transaction = {
            'id': row['id'], 'date': row['date'], 'type': 'income' if income else 'expense',
            'category': row['type'], 'title': row['desc'], 'amount': (income or expense) / 100,
            'orderId': row.get('orderNo', ''), 'note': row.get('note', ''),
        }
        if income and transaction['orderId']:
            transaction['kind'] = 'deposit' if row['type'] == '收入-定金' else 'final'
        state['transactions'].append(transaction)

    for row in source['styles']:
        ledger.check(isinstance(row, dict), '旧版款式格式不正确。')
        style = plain(StyleInput.model_validate(row))
        style['id'] = str(uuid5(NAMESPACE_URL, 'handmade-bags/style/' + style['name']))
        state['styles'].append(style)

    ledger.recalc(state)
    for order in state['orders']:
        actual = (ledger.cents(order['deposit']), ledger.cents(order['final']))
        ledger.check(actual == expected[order['id']], f"订单 {order['id']} 的收款与流水不一致，请先核对原备份；当前账本未改变。")
    return ledger.validate(state)
