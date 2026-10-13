from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[Decimal, Field(ge=0, le=9999999, decimal_places=2)]
Status = Literal['booked', 'making', 'ready', 'shipped', 'delivered']
CATEGORIES = ['采购-布料', '采购-耗材辅料', '采购-工具', '每周合并发货运费', '其他支出', '收入-定金', '收入-尾款', '其他收入']


def today() -> str:
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class OrderInput(InputModel):
    id: str = Field(default='', max_length=100, pattern=r'^[\w.\-]*$')
    date: date
    customer: str = Field(min_length=1, max_length=80)
    style: str = Field(min_length=1, max_length=1000)
    price: Money
    deposit: Money = Decimal(0)
    final: Money = Decimal(0)
    discount: Money = Decimal(0)
    cost: Money = Decimal(0)
    status: Status = 'booked'
    due: date | None = None
    channel: str = Field(default='', max_length=80)
    address: str = Field(default='', max_length=1000)
    tracking: str = Field(default='', max_length=100)
    note: str = Field(default='', max_length=2000)
    photos: list[str] = Field(default_factory=list, max_length=6)
    styleIds: list[str] = Field(default_factory=list, max_length=50)
    product: int | None = None
    receiptDate: date = Field(default_factory=lambda: date.fromisoformat(today()))

    @field_validator('due', mode='before')
    @classmethod
    def empty_due(cls, value):
        return value or None


class TransactionInput(InputModel):
    date: date
    type: Literal['income', 'expense']
    category: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    amount: Annotated[Decimal, Field(gt=0, le=9999999, decimal_places=2)]
    orderId: str = Field(default='', max_length=100)
    note: str = Field(default='', max_length=2000)


class StyleInput(InputModel):
    name: str = Field(min_length=1, max_length=120)
    price: Money | None = None
    cost: Money = Decimal(0)


class ProgressInput(InputModel):
    status: Status


class ClearInput(InputModel):
    confirmation: Literal['清空']


def plain(model: BaseModel) -> dict:
    """Keep the public money fields numeric and ISO date fields textual."""
    result = model.model_dump()
    for key, value in result.items():
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, date):
            result[key] = value.isoformat()
        elif value is None and key == 'due':
            result[key] = ''
    return result
