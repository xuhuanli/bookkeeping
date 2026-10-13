import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .ledger import cents, empty


class ConflictError(ValueError):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, price_cents INTEGER NOT NULL,
                    discount_cents INTEGER NOT NULL, cost_cents INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY, order_id TEXT REFERENCES orders(id),
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS styles (id TEXT PRIMARY KEY, price_cents INTEGER, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES ('revision', '0');
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read(self, connection):
        state = empty()
        for table in ('orders', 'transactions', 'styles'):
            state[table] = [json.loads(row[0]) for row in connection.execute(f'SELECT payload FROM {table} ORDER BY rowid')]
        revision = int(connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
        return state, revision

    def read(self):
        with self.connect() as connection:
            connection.execute('BEGIN')
            return self._read(connection)

    def _write(self, connection, state):
        connection.execute('DELETE FROM transactions')
        connection.execute('DELETE FROM orders')
        connection.execute('DELETE FROM styles')
        pack = lambda row: json.dumps(row, ensure_ascii=False, separators=(',', ':'))
        connection.executemany('INSERT INTO orders VALUES (?,?,?,?,?)', [(o['id'], cents(o['price']), cents(o['discount']), cents(o['cost']), pack(o)) for o in state['orders']])
        connection.executemany('INSERT INTO transactions VALUES (?,?,?,?)', [(t['id'], t.get('orderId') or None, cents(t['amount']), pack(t)) for t in state['transactions']])
        connection.executemany('INSERT INTO styles VALUES (?,?,?)', [(p['id'], cents(p['price']) if p.get('price') is not None else None, pack(p)) for p in state['styles']])

    def mutate(self, operation, revision=None, undo=False):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current, actual = self._read(connection)
            if revision is not None and revision != actual:
                raise ConflictError('账本已在另一台设备更新。请刷新页面后重试，刚才的内容没有覆盖新数据。')
            next_state = operation(current)
            if undo:
                connection.execute("INSERT OR REPLACE INTO metadata VALUES ('undo',?)", (json.dumps(current, ensure_ascii=False),))
            self._write(connection, next_state)
            connection.execute("UPDATE metadata SET value=? WHERE key='revision'", (str(actual + 1),))
            return next_state, actual + 1

    def undo(self, revision=None):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current, actual = self._read(connection)
            if revision is not None and actual != revision:
                raise ConflictError('账本已在另一台设备更新，请刷新后恢复。')
            saved = connection.execute("SELECT value FROM metadata WHERE key='undo'").fetchone()
            if not saved:
                raise ValueError('还没有可以恢复的操作。')
            state = json.loads(saved[0])
            self._write(connection, state)
            connection.execute("INSERT OR REPLACE INTO metadata VALUES ('undo',?)", (json.dumps(current, ensure_ascii=False),))
            connection.execute("UPDATE metadata SET value=? WHERE key='revision'", (str(actual + 1),))
            return state, actual + 1

    def has_undo(self):
        with self.connect() as connection:
            return bool(connection.execute("SELECT 1 FROM metadata WHERE key='undo'").fetchone())
