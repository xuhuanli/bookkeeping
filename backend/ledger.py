"""Ledger rules. Every mutation returns a new, validated snapshot."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from datetime import date
from uuid import uuid4

from .models import CATEGORIES, OrderInput, StyleInput, TransactionInput, plain, today


class LedgerError(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise LedgerError(message)


def cents(value):
    try:
        amount = Decimal(str(value))
        check(amount.is_finite() and amount * 100 == (amount * 100).to_integral_value(), '金额最多保留两位小数。')
        return int(amount * 100)
    except (InvalidOperation, TypeError):
        raise LedgerError('金额不正确。') from None


def total(rows, key='amount'):
    return sum(cents(r[key]) for r in rows) / 100


def balance(order):
    return (cents(order['price']) - cents(order['discount']) - cents(order['received'])) / 100


def empty():
    return {'version': 2, 'orders': [], 'transactions': [], 'styles': []}


def recalc(state):
    for order in state['orders']:
        rows = [t for t in state['transactions'] if t.get('orderId') == order['id'] and t['type'] == 'income']
        order['deposit'] = total([t for t in rows if t.get('kind') == 'deposit'])
        order['final'] = total([t for t in rows if t.get('kind') != 'deposit'])
        order['received'] = (cents(order['deposit']) + cents(order['final'])) / 100
    return state


def validate(state):
    check(isinstance(state, dict) and state.get('version') == 2, '不支持的备份版本。')
    for key in ('orders', 'transactions', 'styles'):
        check(isinstance(state.get(key), list) and len(state[key]) <= 50000, '备份结构不完整或记录过多。')
        ids = [r.get('id') for r in state[key] if isinstance(r, dict)]
        check(len(ids) == len(state[key]) and all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids), '备份中的编号无效或重复。')
    for style in state['styles']:
        StyleInput.model_validate({k: style.get(k) for k in ('name', 'price', 'cost') if k in style})
    orders = {o['id']: o for o in state['orders']}
    for order in state['orders']:
        fields = {k: order[k] for k in OrderInput.model_fields if k in order}
        OrderInput.model_validate(fields)
        check(balance(order) >= 0, '已收金额与优惠之和不能超过报价。')
        completed = order.get('completedDate', '')
        check(isinstance(completed, str), '订单完成日期无效。')
        if completed:
            date.fromisoformat(completed)
            check(completed >= order['date'], '完成日期不能早于下单日期。')
        check(order['status'] != 'delivered' or completed, '已完成订单缺少完成日期。')
        history = order.get('discountHistory', [])
        check(isinstance(history, list), '优惠历史无效。')
        for item in history:
            check(isinstance(item, dict) and isinstance(item.get('date'), str), '优惠历史无效。')
            date.fromisoformat(item['date'])
            check(item['date'] >= order['date'], '优惠登记日期不能早于下单日期。')
        check(sum(cents(h['amount']) for h in history) == cents(order['discount']), '优惠历史与金额不一致。')
    for row in state['transactions']:
        TransactionInput.model_validate({k: row[k] for k in TransactionInput.model_fields if k in row})
        check(row['category'] in CATEGORIES, '收支类型不正确。')
        check(row['type'] == ('income' if row['category'].startswith('收入-') or row['category'] == '其他收入' else 'expense'), '收支金额与类型不一致。')
        if row.get('orderId'):
            order = orders.get(row['orderId'])
            check(order is not None, '关联订单不存在。')
            if row['type'] == 'income':
                expected_kind = 'deposit' if row['category'] == '收入-定金' else 'final'
                check(row.get('kind') == expected_kind, '收款类型与流水分类不一致。')
                check(row['date'] >= order['date'], '收款日期不能早于下单日期。')
    for order in state['orders']:
        rows = [t for t in state['transactions'] if t.get('orderId') == order['id'] and t['type'] == 'income']
        check(cents(total(rows)) == cents(order['received']), '订单与关联收入流水不一致。')
        check(cents(total([t for t in rows if t['kind'] == 'deposit'])) == cents(order['deposit']), '定金与流水不一致。')
        check(cents(order['deposit']) + cents(order['final']) == cents(order['received']), '定金、尾款和已收金额不一致。')
    return state


def next_number(state, day):
    prefix = 'DD' + day.replace('-', '') + '-'
    ids = {o['id'] for o in state['orders']}
    number = 1
    while prefix + f'{number:02}' in ids:
        number += 1
    return prefix + f'{number:02}'


def save_order(state, model: OrderInput, old_id=None):
    state = deepcopy(state)
    old = next((o for o in state['orders'] if o['id'] == old_id), None)
    check(not old_id or old, '订单不存在。')
    order = plain(model)
    receipt_date = order.pop('receiptDate')
    order['id'] = order['id'] or (old_id if old_id else next_number(state, order['date']))
    check(not any(o['id'] == order['id'] and o['id'] != old_id for o in state['orders']), '订单编号已存在。')
    order['discountHistory'] = deepcopy(old['discountHistory']) if old else []
    delta = cents(order['discount']) - cents(old['discount'] if old else 0)
    if delta:
        check(receipt_date >= order['date'], '优惠日期不能早于下单日期。')
        order['discountHistory'].append({'date': receipt_date, 'amount': delta / 100})
    order['completedDate'] = (old.get('completedDate') or receipt_date) if old and order['status'] == 'delivered' else receipt_date if order['status'] == 'delivered' else ''
    if old:
        for row in state['transactions']:
            if row.get('orderId') == old_id:
                row['orderId'] = order['id']
                if row['title'] == old['customer'] + ' · ' + old['style']:
                    row['title'] = order['customer'] + ' · ' + order['style']
    for kind in ('deposit', 'final'):
        rows = [t for t in state['transactions'] if t.get('orderId') == order['id'] and t['type'] == 'income' and t['kind'] == kind]
        difference = cents(order[kind]) - cents(total(rows))
        if difference > 0:
            state['transactions'].append({'id': str(uuid4()), 'date': receipt_date, 'type': 'income', 'kind': kind, 'category': '收入-定金' if kind == 'deposit' else '收入-尾款', 'title': order['customer'] + ' · ' + order['style'], 'amount': difference / 100, 'orderId': order['id'], 'note': '订单收款金额调整' if old else ''})
        elif difference < 0:
            reduction = -difference
            for row in sorted(rows, key=lambda t: t['date'], reverse=True):
                take = min(cents(row['amount']), reduction)
                row['amount'] = (cents(row['amount']) - take) / 100
                reduction -= take
                if not reduction:
                    break
            state['transactions'] = [t for t in state['transactions'] if t['amount'] > 0]
    if old:
        state['orders'][state['orders'].index(old)] = order
    else:
        state['orders'].insert(0, order)
    return validate(recalc(state))


def save_transaction(state, model: TransactionInput, old_id=None):
    state = deepcopy(state)
    index = next((i for i, t in enumerate(state['transactions']) if t['id'] == old_id), None)
    check(not old_id or index is not None, '流水不存在。')
    row = plain(model)
    row['id'] = old_id or str(uuid4())
    if row.get('orderId') and row['type'] == 'income':
        row['kind'] = 'deposit' if row['category'] == '收入-定金' else 'final'
    if index is None:
        state['transactions'].insert(0, row)
    else:
        state['transactions'][index] = row
    return validate(recalc(state))


def save_style(state, model: StyleInput, old_id=None):
    state = deepcopy(state)
    old = next((p for p in state['styles'] if p['id'] == old_id), None)
    check(not old_id or old, '款式不存在。')
    check(not any(p['name'] == model.name and p['id'] != old_id for p in state['styles']), '这个款式名称已经存在。')
    row = {**(old or {}), **plain(model), 'id': old_id or str(uuid4())}
    if old:
        state['styles'][state['styles'].index(old)] = row
    else:
        state['styles'].append(row)
    return validate(state)


def remove(state, kind, identifier):
    state = deepcopy(state)
    key = {'order': 'orders', 'transaction': 'transactions', 'style': 'styles'}[kind]
    check(any(r['id'] == identifier for r in state[key]), '这条记录不存在。')
    state[key] = [r for r in state[key] if r['id'] != identifier]
    if kind == 'order':
        state['transactions'] = [t for t in state['transactions'] if t.get('orderId') != identifier or t['type'] == 'expense']
        for row in state['transactions']:
            if row.get('orderId') == identifier:
                row['orderId'] = ''
    return validate(recalc(state))


def summary(state, month=None):
    end = month + '-31' if month else '9999-12-31'
    rows = [t for t in state['transactions'] if not month or t['date'].startswith(month)]
    income = total([t for t in rows if t['type'] == 'income'])
    expense = total([t for t in rows if t['type'] == 'expense'])
    orders = [o for o in state['orders'] if not month or o['date'].startswith(month)]
    pending = 0
    for order in state['orders']:
        if order['date'] <= end:
            received = total([t for t in state['transactions'] if t.get('orderId') == order['id'] and t['type'] == 'income' and t['date'] <= end])
            cut = sum(cents(h['amount']) for h in order['discountHistory'] if h['date'] <= end)
            pending += max(0, cents(order['price']) - cents(received) - cut)
    return {'month': month or '累计', 'income': income, 'expense': expense, 'net': (cents(income) - cents(expense)) / 100, 'purchase': total([t for t in rows if t['type'] == 'expense' and t['category'].startswith('采购-')]), 'shipping': total([t for t in rows if t['category'] == '每周合并发货运费']), 'count': len(orders), 'completed': len([o for o in state['orders'] if o['status'] == 'delivered' and (not month or o['completedDate'].startswith(month))]), 'pending': pending / 100, 'discount': total(orders, 'discount')}


def months(state):
    return sorted({d[:7] for d in [*[o['date'] for o in state['orders']], *[t['date'] for t in state['transactions']], *[o['completedDate'] for o in state['orders'] if o['completedDate']], *[h['date'] for o in state['orders'] for h in o['discountHistory']]]}, reverse=True)
