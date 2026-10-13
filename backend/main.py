from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from . import ledger
from .database import ConflictError, Database
from .export import excel
from .images import MAX_UPLOAD, check_photos, embed_photos, restore_photos, store_image
from .models import ClearInput, OrderInput, ProgressInput, StyleInput, TransactionInput, today

ROOT = Path(__file__).resolve().parent.parent


def create_app(data_dir: Path | None = None, images_dir: Path | None = None, frontend_dir: Path | None = None):
    data_dir = Path(data_dir or os.environ.get('BOOKKEEPING_DATA_DIR', ROOT / 'data'))
    images_dir = Path(images_dir or os.environ.get('BOOKKEEPING_IMAGES_DIR', ROOT / 'images'))
    frontend_dir = Path(frontend_dir or ROOT / 'frontend' / 'dist')
    images_dir.mkdir(parents=True, exist_ok=True)
    database = Database(data_dir / 'bookkeeping.sqlite3')
    app = FastAPI(title='针线小账 · 本地记账 API', version='1.0.0')
    app.state.database = database
    app.state.images_dir = images_dir

    @app.exception_handler(ConflictError)
    async def conflict_handler(request, error):
        return JSONResponse(status_code=409, content={'detail': str(error)})

    @app.exception_handler(ValueError)
    async def value_handler(request, error):
        message = '数据格式不正确，请检查日期、金额和备份内容。' if isinstance(error, ValidationError) else str(error)
        return JSONResponse(status_code=400, content={'detail': message})

    def result(pair):
        state, revision = pair
        return {'data': state, 'revision': revision, 'hasUndo': database.has_undo(), 'reports': {'total': ledger.summary(state), 'months': [ledger.summary(state,m) for m in ledger.months(state)]}}

    def mutate(operation, revision, undo=False):
        def checked(current):
            state = operation(current)
            check_photos(state, images_dir)
            return state
        return result(database.mutate(checked, revision, undo))

    @app.middleware('http')
    async def local_response_headers(request: Request, call_next):
        if request.url.path.startswith('/api/'):
            length = request.headers.get('content-length', '0')
            if length.isdigit() and int(length) > 45 * 1024 * 1024:
                return JSONResponse(status_code=413, content={'detail': '请求过大，备份不能超过 45 MB。'})
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'storage': 'sqlite', 'mode': 'local'}

    @app.get('/api/ledger')
    def get_ledger():
        return result(database.read())

    @app.get('/api/orders')
    def orders(q: str = '', status: str = '', unpaid: bool = False):
        state, _ = database.read()
        return [o for o in state['orders'] if (not q or q.lower() in ' '.join([o['id'],o['customer'],o['style']]).lower()) and (not status or o['status'] == status) and (not unpaid or ledger.balance(o)>0)]

    @app.post('/api/orders', status_code=201)
    def add_order(body: OrderInput, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.save_order(s, body), x_ledger_revision)

    @app.put('/api/orders/{identifier}')
    def edit_order(identifier: str, body: OrderInput, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.save_order(s, body, identifier), x_ledger_revision)

    @app.patch('/api/orders/{identifier}/status')
    def progress(identifier: str, body: ProgressInput, x_ledger_revision: int | None = Header(default=None)):
        def update(state):
            state = deepcopy(state)
            order = next((o for o in state['orders'] if o['id']==identifier), None)
            ledger.check(order, '订单不存在。')
            order['status'] = body.status
            order['completedDate'] = (order['completedDate'] or today()) if body.status == 'delivered' else ''
            return ledger.validate(state)
        return mutate(update, x_ledger_revision)

    @app.delete('/api/orders/{identifier}')
    def delete_order(identifier: str, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.remove(s, 'order', identifier), x_ledger_revision, undo=True)

    @app.get('/api/transactions')
    def transactions(month: str = '', type: str = '', category: str = ''):
        state, _ = database.read()
        return [t for t in state['transactions'] if (not month or t['date'].startswith(month)) and (not type or t['type']==type) and (not category or t['category']==category)]

    @app.post('/api/transactions', status_code=201)
    def add_transaction(body: TransactionInput, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.save_transaction(s, body), x_ledger_revision)

    @app.put('/api/transactions/{identifier}')
    def edit_transaction(identifier: str, body: TransactionInput, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.save_transaction(s, body, identifier), x_ledger_revision)

    @app.delete('/api/transactions/{identifier}')
    def delete_transaction(identifier: str, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.remove(s, 'transaction', identifier), x_ledger_revision, undo=True)

    @app.get('/api/styles')
    def styles():
        return database.read()[0]['styles']

    @app.post('/api/styles', status_code=201)
    def add_style(body: StyleInput, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.save_style(s, body), x_ledger_revision)

    @app.put('/api/styles/{identifier}')
    def edit_style(identifier: str, body: StyleInput, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.save_style(s, body, identifier), x_ledger_revision)

    @app.delete('/api/styles/{identifier}')
    def delete_style(identifier: str, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.remove(s, 'style', identifier), x_ledger_revision, undo=True)

    @app.post('/api/images', status_code=201)
    async def upload_image(file: UploadFile = File(...)):
        try:
            raw = await file.read(MAX_UPLOAD + 1)
            url = await run_in_threadpool(store_image, raw, images_dir)
            return {'url': url, 'filename': url.rsplit('/',1)[1]}
        finally:
            await file.close()

    @app.get('/api/reports')
    def reports():
        state, _ = database.read()
        return {'total': ledger.summary(state), 'months': [ledger.summary(state,m) for m in ledger.months(state)]}

    @app.get('/api/export.xlsx')
    def export_excel():
        content = excel(database.read()[0])
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote('针线小账-'+today()+'.xlsx')})

    @app.get('/api/backup')
    def backup():
        state = embed_photos(deepcopy(database.read()[0]), images_dir)
        body = {'app': 'stitch-ledger', 'version': 2, 'exportedAt': datetime.now().astimezone().isoformat(), 'data': state}
        return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type='application/json', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote('针线小账-完整备份-'+today()+'.json')})

    @app.post('/api/restore')
    def restore(body: dict, x_ledger_revision: int | None = Header(default=None)):
        if body.get('app') and body['app'] != 'stitch-ledger':
            raise ValueError('请选择针线小账导出的备份文件。')
        state = deepcopy(body.get('data', body))
        created = []
        try:
            ledger.validate(state)
            created = restore_photos(state, images_dir)
            return mutate(lambda s: ledger.validate(state), x_ledger_revision, undo=True)
        except (KeyError, TypeError, AttributeError):
            for path in created:
                path.unlink(missing_ok=True)
            raise ValueError('备份结构不完整，当前账本未改变。') from None
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    @app.post('/api/clear')
    def clear(body: ClearInput, x_ledger_revision: int | None = Header(default=None)):
        return mutate(lambda s: ledger.empty(), x_ledger_revision, undo=True)

    @app.post('/api/undo')
    def undo(x_ledger_revision: int | None = Header(default=None)):
        return result(database.undo(x_ledger_revision))

    app.mount('/images', StaticFiles(directory=images_dir), name='images')
    if frontend_dir.is_dir():
        app.mount('/', StaticFiles(directory=frontend_dir, html=True), name='frontend')
    else:
        @app.get('/')
        def missing_frontend():
            return JSONResponse(status_code=503, content={'detail': '请先在 frontend 中运行 npm install && npm run build，或使用 python run.py。'})
    return app


app = create_app()
