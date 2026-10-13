import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from .ledger import balance, months, summary

STATUS = {'booked': '待制作', 'making': '制作中', 'ready': '待发货', 'shipped': '已发货', 'delivered': '已完成'}


def excel(state):
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = [
        ('订单台账', ['下单日期','订单编号','顾客','款式/规格','报价','定金','已收尾款','优惠','待收尾款','状态','收货信息','快递单号','预计交付','预估成本','备注','照片数量'], [[o['date'],o['id'],o['customer'],o['style'],o['price'],o['deposit'],o['final'],o['discount'],balance(o),STATUS[o['status']],o['address'],o['tracking'],o['due'],o['cost'],o['note'],len(o['photos'])] for o in state['orders']]),
        ('收支明细', ['日期','类型','对应订单','物品/事项','支出','收入','备注'], [[t['date'],t['category'],t.get('orderId',''),t['title'],t['amount'] if t['type']=='expense' else 0,t['amount'] if t['type']=='income' else 0,t.get('note','')] for t in state['transactions']]),
        ('月度汇总', ['月份','收入','支出','采购成本','发货运费','净收益','新增订单','完成订单','月末待收'], [[s['month'],s['income'],s['expense'],s['purchase'],s['shipping'],s['net'],s['count'],s['completed'],s['pending']] for s in [summary(state), *[summary(state,m) for m in months(state)]]]),
        ('常用款式', ['款式','单价','预估成本'], [[p['name'],p.get('price'),p.get('cost',0)] for p in state['styles']]),
    ]
    for name, headers, rows in sheets:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='49664F')
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                # User text remains text, even when it starts with an Excel formula.
                if isinstance(cell.value, str):
                    cell.data_type = 's'
                elif isinstance(cell.value, (float, int)):
                    cell.number_format = '#,##0.00'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        for column in sheet.columns:
            length = max(len(str(cell.value or '')) for cell in list(column)[:200])
            sheet.column_dimensions[column[0].column_letter].width = min(45, max(14, length + 2))
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
