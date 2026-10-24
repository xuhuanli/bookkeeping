import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const source = await readFile(new URL('../src/reference-app.js', import.meta.url), 'utf8');

// Exercise the production renderer and XLSX writer, substituting only browser
// elements, the HTTP response and the download destination.
function application(data) {
  const elements = new Map();
  const control = {disabled: false, isConnected: true};
  const downloads = [];
  let snapshot = {data, revision: 1};
  let offline = false;
  const context = {
    Blob, TextEncoder, Uint8Array, Uint32Array, DataView,
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, {
          innerHTML: '', textContent: '', addEventListener() {},
          classList: {add() {}, remove() {}},
        });
        return elements.get(id);
      },
      querySelectorAll: () => [control],
    },
    setTimeout() {}, clearTimeout() {},
    fetch: async path => {
      assert.equal(path, '/api/book');
      if (offline) throw new Error('offline');
      return {ok: true, json: async () => structuredClone(snapshot)};
    },
    capture: blob => downloads.push(blob),
  };
  vm.createContext(context);
  const prefix = source.slice(0, source.indexOf('function download(blob, filename){'))
    .replace('export function startReferenceApp()', 'function startReferenceApp()');
  vm.runInContext(prefix + `
    function download(blob) { capture(blob); }
    return {load, exportExcel, renderSummary};
  }`, context);
  return {
    app: context.startReferenceApp(), elements, downloads, control,
    update(data) { snapshot = {data, revision: snapshot.revision + 1}; },
    disconnect() { offline = true; },
  };
}

function fixture() {
  const row = (id, type, exp, inc) => ({id, type, date: '2026-10-24', orderNo: '', desc: id, exp, inc, note: ''});
  return {orders: [], styles: [], seq: {}, cash: [
    row('定金', '收入-定金', 0, 20),
    row('布料', '采购-布料', 10, 0),
    row('其他', '其他支出', 5, 0),
  ]};
}

async function zipEntries(blob) {
  const bytes = Buffer.from(await blob.arrayBuffer());
  const entries = new Map();
  for (let offset = 0; bytes.readUInt32LE(offset) === 0x04034b50;) {
    assert.equal(bytes.readUInt16LE(offset + 8), 0);
    const size = bytes.readUInt32LE(offset + 18);
    const nameLength = bytes.readUInt16LE(offset + 26);
    const start = offset + 30 + nameLength + bytes.readUInt16LE(offset + 28);
    entries.set(bytes.toString('utf8', offset + 30, offset + 30 + nameLength), bytes.toString('utf8', start, start + size));
    offset = start + size;
  }
  return entries;
}

test('export fetches the newest snapshot after another device records cash', async () => {
  const data = fixture();
  const ui = application(data);
  await ui.app.load();
  data.cash.push({id: 'new', date: '2026-10-24', type: '采购-工具', orderNo: '', desc: '另一设备刚新增 & 工具', exp: 7, inc: 0, note: ''});
  ui.update(data);
  await ui.app.exportExcel();
  assert.equal(ui.downloads.length, 1);
  const entries = await zipEntries(ui.downloads[0]);
  assert.match(entries.get('xl/worksheets/sheet2.xml'), /另一设备刚新增 &amp; 工具/);
  assert.match(ui.elements.get('cashCount').textContent, /4/);
  assert.equal(ui.control.disabled, false);
});

test('all expense categories reduce monthly profit in the page and exported sheet', async () => {
  const ui = application(fixture());
  await ui.app.exportExcel();
  assert.match(ui.elements.get('sumList').innerHTML, /\+¥5\.00/);
  const entries = await zipEntries(ui.downloads[0]);
  const xml = entries.get('xl/worksheets/sheet3.xml');
  const monthRow = [...xml.matchAll(/<row\b[^>]*>[\s\S]*?<\/row>/g)]
    .map(match => match[0]).find(row => /<t[^>]*>2026-10<\/t>/.test(row));
  assert.match(monthRow, /<c r="D\d+"[^>]*><v>15<\/v>/);
  assert.match(monthRow, /<c r="G\d+"[^>]*><v>5<\/v>/);
});

test('failed refresh cancels the export and restores the controls', async () => {
  const ui = application(fixture());
  await ui.app.load();
  ui.disconnect();
  await ui.app.exportExcel();
  assert.equal(ui.downloads.length, 0);
  assert.match(ui.elements.get('toast').textContent, /导出失败/);
  assert.equal(ui.control.disabled, false);
});
