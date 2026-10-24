export function startReferenceApp() {

/* UI and interactions matched to the user-supplied reference app.
   Records are saved by the local FastAPI service. */
const ORDER_STATUS = ['已收定金-待制作','已收尾款-待发货','已完成'];
const CASH_TYPES = ['采购-布料','采购-耗材辅料','采购-工具','每周合并发货运费','收入-定金','收入-尾款'];
const STATUS_CLS = {
  '已收定金-待制作':'b-dep','已收尾款-待发货':'b-ship','已完成':'b-done'
};

/* ---------- 数据层 ---------- */
let DB = { orders:[], cash:[], seq:{}, styles:[] };

function today(){
  const d=new Date(), p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`;
}
let revision = 0;
let confirmed = JSON.stringify(DB);
let persisting = false;
async function request(path, options = {}) {
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('无法连接电脑上的服务，请检查电脑和网络。'); }
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请检查日期、金额和必填内容。');
  return result;
}
function accept(result) {
  DB = result.data;
  revision = result.revision;
  confirmed = JSON.stringify(DB);
}
function lockControls() {
  const controls = [...document.querySelectorAll('button, input, select, textarea')];
  const enabled = controls.filter(el => !el.disabled);
  enabled.forEach(el => { el.disabled = true; });
  return () => enabled.forEach(el => { if (el.isConnected) el.disabled = false; });
}
async function load() {
  accept(await request('/api/book'));
}
async function save(payload = DB, options = {}) {
  if (persisting) { toast('正在保存，请稍等'); return false; }
  persisting = true;
  const unlock = lockControls();
  try {
    accept(await request('/api/book', {
      method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Ledger-Revision': String(revision),
        ...(options.receiptDate ? {'X-Receipt-Date': options.receiptDate} : {}),
        ...(options.restore ? {'X-Book-Restore': 'true'} : {})},
      body: JSON.stringify(payload),
    }));
    return true;
  } catch (error) {
    DB = JSON.parse(confirmed);
    renderAll();
    toast(error.message, 4500);
    return false;
  } finally { persisting = false; unlock(); }
}
function uid(){ return Date.now().toString(36)+Math.random().toString(36).slice(2,7); }

/* 生成订单编号 DDYYYYMMDD-NN */
function genOrderNo(dateStr){
  const key = (dateStr||today()).replace(/-/g,'');
  const letters = key.slice(-4);
  const n = (DB.seq['o'+key]||0)+1; DB.seq['o'+key]=n;
  return `DD${key}-${String(n).padStart(2,'0')}`;
}
/* 生成流水编号 SK 仅内部用，不展示 */

/* ---------- 款式库：自定义常用款式（含单价），下单时一键选取 ---------- */
/* 兼容旧数据：早期只存字符串，现在存 {name, price} */
function styleNorm(x){
  if(x && typeof x === 'object'){
    const n = String(x.name==null?'':x.name).trim();
    if(!n) return null;
    return { name:n, price: round2(x.price) };
  }
  const n = String(x==null?'':x).trim();
  return n ? { name:n, price:0 } : null;
}
/* 规范化后的款式列表：去重、保序、丢弃空项 */
function styleList(){
  const seen = {}, out = [];
  (Array.isArray(DB.styles)?DB.styles:[]).forEach(x=>{
    const s = styleNorm(x);
    if(!s || seen[s.name]) return;
    seen[s.name] = 1; out.push(s);
  });
  return out;
}
/* 名称列表 */
const styleNames = () => styleList().map(s=>s.name);
/* 查单价；找不到返回 0
   支持松匹配：订单里常写成「帆布托特包·中号·米白」，款式库只登记了「帆布托特包」，
   此时按「前缀 / 首个分隔符前的主名」回退匹配，避免款式价格匹配失败。 */
function stylePrice(name){
  const k = String(name==null?'':name).trim();
  if(!k) return 0;
  const list = styleList();
  const hit = list.filter(s=>s.name===k)[0];
  if(hit) return num(hit.price);
  /* 回退 1：订单名以款式库名开头（「帆布托特包·中号」←→「帆布托特包」） */
  const pre = list.filter(s=>s.name && k.indexOf(s.name)===0)
                  .sort((a,b)=>b.name.length-a.name.length)[0];
  if(pre) return num(pre.price);
  /* 回退 2：取订单名的主名（第一个 ·、-、空格 之前）再比一次 */
  const base = k.split(/[·・\-—\s(（]/)[0].trim();
  if(base && base!==k){
    const b = list.filter(s=>s.name===base)[0];
    if(b) return num(b.price);
  }
  return 0;
}
/* 新增款式（已存在则忽略）；price 可省略 */
function addStyle(name, price){
  const k = String(name==null?'':name).trim();
  if(!k) return false;
  if(styleNames().indexOf(k) > -1) return false;
  DB.styles = styleList().concat([{ name:k, price: round2(price) }]);
  return true;
}
/* 只改价格（列表里直接改） */
function setStylePrice(name, price){
  const k = String(name==null?'':name).trim();
  DB.styles = styleList().map(s => s.name===k ? { name:s.name, price: round2(price) } : s);
}
function removeStyle(name){
  const k = String(name||'').trim();
  DB.styles = styleList().filter(s => s.name !== k);
}
/* 订单在用的款式（用于提示哪些不能随便删） */
function usedStyleCount(name){
  const k = String(name||'').trim();
  return DB.orders.filter(o => String(o.style||'').trim() === k).length;
}
/* ---------- 款式数量：解析与格式化 ---------- */
/* 把「帆布托特包 ×2」拆成 {name:'帆布托特包', qty:2}；没写数量就是 1 */
function parseStylePart(s){
  const raw = String(s==null?'':s).trim();
  if(!raw) return null;
  const m = raw.match(/^(.*?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*$/);
  if(m){
    const nm = m[1].trim();
    const q = num(m[2]);
    if(!nm) return null;
    return { name: nm, qty: q > 0 ? q : 1 };
  }
  return { name: raw, qty: 1 };
}
/* 数量格式化：1 个不写，≥2 写「×N」；非整数保留小数 */
function fmtQty(q){
  const n = num(q);
  if(n <= 1) return '';
  return ' ×' + (Math.abs(n - Math.round(n)) < 1e-9 ? String(Math.round(n)) : String(round2(n)));
}
/* 把 [{name,qty}] 拼成款式框文本 */
function stylesToText(items){
  return (Array.isArray(items)?items:[]).filter(x=>x && x.name)
    .map(x => x.name + fmtQty(x.qty)).join(' + ');
}
/* 把款式框文本拆回 [{name,qty}] */
function textToStyles(s){
  return String(s==null?'':s).split(/\s*\+\s*/).map(parseStylePart).filter(Boolean);
}
/* 点选款式算报价：单价 × 数量 再求和；兼容纯字符串数组 */
function stylesTotal(names){
  return round2((Array.isArray(names)?names:[]).reduce((a,n)=>{
    if(n && typeof n === 'object') return a + stylePrice(n.name) * (n.qty === undefined || n.qty === null || n.qty === '' ? 1 : num(n.qty));
    return a + stylePrice(n);
  }, 0));
}

/* ---------- 计算层（与 Excel 公式口径一致） ---------- */
const num = v => { const n=Number(v); return isFinite(n)?n:0; };
const EPS = 0.005;   /* 分位容差，避免浮点误差误判「还差点没结清」 */
/* 以「分」为单位取整，规避 0.1+0.2 这类浮点误差 */
function round2(v){ return Math.round(num(v)*100)/100; }
/* 待收尾款 = 报价 − 抹零/优惠 − 已收定金 − 已收尾款 */
const owe = o => round2(num(o.price) - num(o.cut) - num(o.deposit) - num(o.final));
const monthOf = d => {
  const m = String(d == null ? '' : d).slice(0, 7);
  return /^\d{4}-\d{2}$/.test(m) ? m : '';
};

function compute(){
  let cost=0, freight=0, expense=0, income=0;
  DB.cash.forEach(c=>{
    const e=num(c.exp), i=num(c.inc);
    expense+=e; income+=i;
    if(c.type==='每周合并发货运费') freight+=e;
    else if(c.type && c.type.indexOf('采购-')===0) cost+=e;
  });
  const receivable = DB.orders.reduce((s,o)=> s+Math.max(0,owe(o)), 0);
  /* 抹零/优惠合计：只统计真正让出去的零头（抹零 ≤ 报价 − 定金 − 尾款） */
  const rounded = DB.orders.reduce((s,o)=>{
    const real = Math.max(0, num(o.price) - num(o.deposit) - num(o.final));
    return s + Math.min(num(o.cut), real);
  }, 0);

  // 按月聚合
  const map = {};
  const touch = m => (map[m] = map[m] || {mon:m,cost:0,freight:0,exp:0,inc:0,newOrders:0,done:0,owe:0,rounded:0});
  DB.cash.forEach(c=>{ const m=monthOf(c.date); if(!m) return; const t=touch(m);
    const e=num(c.exp), i=num(c.inc);
    t.exp+=e; t.inc+=i;
    if(c.type==='每周合并发货运费') t.freight+=e;
    else if(c.type && c.type.indexOf('采购-')===0) t.cost+=e;
  });
  DB.orders.forEach(o=>{ const m=monthOf(o.date); if(!m) return; const t=touch(m);
    t.newOrders++;
    if(o.status==='已完成') t.done++;
    t.owe+=Math.max(0,owe(o));
    const real = Math.max(0, num(o.price) - num(o.deposit) - num(o.final));
    t.rounded+=Math.min(num(o.cut), real);
  });
  const months = Object.values(map).sort((a,b)=> a.mon<b.mon?1:-1);

  /* ---------- 全程总账：从第一笔账到现在，实时累计 ---------- */
  /* 起算日期 = 订单与收支里最早的那一天（只看合法 YYYY-MM-DD） */
  const dateOk = d => /^\d{4}-\d{2}-\d{2}$/.test(String(d||''));
  const allDates = DB.cash.map(c=>c.date).concat(DB.orders.map(o=>o.date)).filter(dateOk).sort();
  const from = allDates.length ? allDates[0] : '';
  const to   = allDates.length ? allDates[allDates.length-1] : '';
  /* 跨了几个月：按自然月数算（同月记 1 个月），月均用它做分母 */
  const liveMonths = months.length;

  let settledOrders = 0, doneOrders = 0, totalOrders = DB.orders.length;
  DB.orders.forEach(o=>{
    if(Math.max(0,owe(o)) <= EPS) settledOrders++;
    if(o.status === '已完成') doneOrders++;
  });
  const totalPrice = DB.orders.reduce((s,o)=> s+num(o.price), 0);
  const totalDeposit = DB.orders.reduce((s,o)=> s+num(o.deposit), 0);
  const totalFinal = DB.orders.reduce((s,o)=> s+num(o.final), 0);

  const totals = {
    from, to, liveMonths,
    firstCashDate: DB.cash.map(c=>c.date).filter(dateOk).sort()[0] || '',
    firstOrderDate: DB.orders.map(o=>o.date).filter(dateOk).sort()[0] || '',
    totalOrders, doneOrders, settledOrders,
    unsettledOrders: totalOrders - settledOrders,
    totalPrice, totalDeposit, totalFinal,
    netProfit: round2(income - expense),
    grossIncome: income, grossExpense: expense,
    cashCount: DB.cash.length,
    avgProfit: liveMonths ? round2((income - expense) / liveMonths) : 0,
    avgIncome: liveMonths ? round2(income / liveMonths) : 0,
    avgExpense: liveMonths ? round2(expense / liveMonths) : 0,
    /* 目标进度用得到：平均每单赚多少 */
    perOrder: totalOrders ? round2((income - expense) / totalOrders) : 0,
  };

  return {cost,freight,expense,income,receivable,rounded,
          profit:income-expense, months, totals,
          from, to, liveMonths};
}

/* 抹零快捷档位：每个档位给出「抹零后实收的零头应该是多少」 */
const CUT_PRESETS = [
  {label:'抹到整元',    fn:r=>Math.floor(round2(r))},
  {label:'抹到整5元',   fn:r=>Math.floor(round2(r)/5)*5},
  {label:'抹到整10元',  fn:r=>Math.floor(round2(r)/10)*10},
];
/* 抹零后实际收到的零头应为 keep，返回应登记的「抹零/优惠」金额 */
function cutAmount(r, keep){
  return Math.max(0, round2(Math.max(0,r) - Math.max(0,keep)));
}
/* 定金快捷档位 */
const DEPOSIT_PRESETS = [
  { label:'定金 25', amount:25 },
  { label:'定金 10', amount:10 },
  { label:'无定金',  amount:0  },
];

/* ---------- 工具 ---------- */
const esc = s => String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const money = n => num(n).toFixed(2);
function toast(msg,ms){
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('on');
  clearTimeout(toast._t);
  toast._t=setTimeout(()=>t.classList.remove('on'), ms||1700);
}
function $(id){ return document.getElementById(id); }

/* ---------- 搜索：订单筛选 ---------- */
let orderQuery = '';
let selectedOrderFilter = 'all';
const orderFilters = [
  {id:'all', label:'全部', match:()=>true},
  {id:'making', label:'待制作', match:o=>o.status==='已收定金-待制作'},
  {id:'shipping', label:'待发货', match:o=>o.status==='已收尾款-待发货'},
  {id:'completed', label:'已完成', match:o=>o.status==='已完成'},
  {id:'unpaid', label:'待收尾款', match:o=>owe(o)>EPS},
];

function renderOrderFilters(searched){
  $('orderFilters').innerHTML = orderFilters.map(filter=>{
    const count = searched.filter(filter.match).length;
    const selected = selectedOrderFilter===filter.id;
    return `<button type="button" class="order-filter${selected?' is-active':''}"
      data-order-filter="${filter.id}" aria-pressed="${selected}" aria-label="${filter.label}，${count} 条订单">
      <span>${filter.label}</span><span class="order-filter-count" aria-hidden="true">${count}</span>
    </button>`;
  }).join('');
}

function selectOrderFilter(event){
  const button = event.target.closest('[data-order-filter]');
  if(!button || !$('orderFilters').contains(button)) return;
  const id = button.dataset.orderFilter;
  if(id===selectedOrderFilter || !orderFilters.some(filter=>filter.id===id)) return;
  selectedOrderFilter = id;
  renderOrders();
  $('orderFilters').querySelector(`[data-order-filter="${id}"]`).focus({preventScroll:true});
}
/* 关键词归一化：去空格、全角转半角、统一小写，让「小林 」「　小林」都能搜到 */
function norm(s){
  return String(s==null?'':s)
    .replace(/[\uFF01-\uFF5E]/g, ch=>String.fromCharCode(ch.charCodeAt(0)-0xFEE0))
    .replace(/[\s\u3000]+/g,'')
    .toLowerCase();
}
/* 一条订单参与搜索的所有文本 */
function orderHaystack(o){
  return [o.customer, o.no, o.style, o.phone, o.address, o.tracking, o.note, o.status].map(norm).join('|');
}
function filterOrders(list){
  const q = norm(orderQuery);
  if(!q) return list;
  /* 多个关键词用空格分隔，需全部命中（AND） */
  const words = String(orderQuery).replace(/[\u3000]/g,' ')
    .split(/\s+/).map(norm).filter(Boolean);
  if(!words.length) return list;
  return list.filter(o=>{
    const hay = orderHaystack(o);
    return words.every(w=> hay.indexOf(w)>-1);
  });
}
/* 命中的关键词加亮，方便一眼看出为什么被搜到 */
function hl(text){
  const raw = String(text==null?'':text);
  const words = String(orderQuery).replace(/\u3000/g,' ').split(/\s+/).filter(Boolean);
  if(!words.length) return esc(raw);
  let out = esc(raw);
  words.forEach(w=>{
    const nw = norm(w); if(!nw) return;
    /* 对已转义的文本做忽略大小写的字面替换 */
    const rx = new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'), 'gi');
    out = out.replace(rx, m=>`<mark>${m}</mark>`);
  });
  return out;
}

/* ---------- 渲染：订单台账 ---------- */
function renderOrders(){
  const c = compute();
  const active = DB.orders;
  $('orderKpis').innerHTML = `
    <div class="kpi"><div class="lab">订单总数</div><div class="val">${active.length}</div></div>
    <div class="kpi"><div class="lab">待收尾款合计</div><div class="val exp hl">¥${money(c.receivable)}</div></div>
    <div class="kpi"><div class="lab">已收金额合计</div><div class="val inc">¥${money(DB.orders.reduce((s,o)=>s+num(o.deposit)+num(o.final),0))}</div></div>
    <div class="kpi"><div class="lab">抹零/优惠合计</div><div class="val" style="color:#C08A2E">¥${money(c.rounded)}</div></div>`;
  const searched = filterOrders(DB.orders);
  const filter = orderFilters.find(filter=>filter.id===selectedOrderFilter);
  const matched = searched.filter(filter.match);
  renderOrderFilters(searched);
  $('orderCount').textContent = selectedOrderFilter==='all' && !norm(orderQuery)
    ? `共 ${DB.orders.length} 条` : `筛选 ${matched.length} / 共 ${DB.orders.length} 条`;

  const box = $('orderList');
  if(!DB.orders.length){
    box.innerHTML = `<div class="empty"><span class="big">📦</span>还没有订单<br>点下方「+ 记一笔」开始记录吧</div>`;
    $('orderSearchHint').innerHTML = '';
    return;
  }

  /* 搜索结果提示条 */
  const hint = $('orderSearchHint');
  if(norm(orderQuery)){
    hint.innerHTML = matched.length
      ? `找到 <b>${matched.length}</b> 条匹配订单`
      : `${selectedOrderFilter==='all'?'':`在「${filter.label}」中`}没有找到含「<b>${esc(orderQuery)}</b>」的订单`;
  } else {
    hint.innerHTML = '';
  }

  if(!matched.length){
    box.innerHTML = norm(orderQuery)
      ? `<div class="empty"><span class="big">🔍</span>当前条件下没有匹配的订单<br><span style="font-size:11.5px">调整关键词或切换筛选条件试试</span></div>`
      : `<div class="empty"><span class="big">📦</span>暂无${filter.label}订单</div>`;
    return;
  }

  const sorted = matched.slice().sort((a,b)=> (a.date<b.date?1:-1));
  box.innerHTML = sorted.map(o=>{
    const w = Math.max(0, owe(o));
    const settled = w <= EPS;              /* 抹零后已结清 */
    const cut = num(o.cut);
    const showCut = cut > 0;
    return `<div class="row" data-kind="order" data-id="${esc(o.id)}">
      <div class="main">
        <div class="l1">
          <span class="title">${hl(o.customer||'未填客户')} · ${hl(o.style||'未填款式')}</span>
          <span class="amt">¥${money(o.price)}</span>
        </div>
        <div class="l2">${hl(o.date)} ｜ ${hl(o.no||'')}</div>
        <div class="l3">
          <span class="badge ${STATUS_CLS[o.status]||''}">${esc(o.status)}</span>
          ${showCut?`<span class="owe" style="color:#9C6500">抹零 −¥${money(cut)}</span>`:''}
          ${w>EPS?`<span class="owe">待收 ¥${money(w)}</span>`:''}
        </div>
        ${o.address?`<div class="l3" style="color:#9AA8A0">📍 ${esc(o.address)}</div>`:''}
        ${o.tracking?`<div class="l3" style="color:#9AA8A0">📮 ${hl(o.tracking)}</div>`:''}
      </div>
    </div>`;
  }).join('');
}

/* ---------- 渲染：收支明细 ---------- */
const cashKpiGroups = [
  {id:'expense', label:'总支出', value:'expense', color:'exp', empty:'暂无支出记录', match:x=>num(x.exp)>0},
  {id:'income', label:'总收入', value:'income', color:'inc', empty:'暂无收入记录', match:x=>num(x.inc)>0},
  {id:'purchase', label:'采购成本（布料+耗材+工具）', value:'cost', color:'exp', empty:'暂无采购记录', match:x=>num(x.exp)>0 && String(x.type).startsWith('采购-')},
  {id:'freight', label:'发货运费', value:'freight', color:'exp', empty:'暂无运费记录', match:x=>num(x.exp)>0 && x.type==='每周合并发货运费'},
];
const expandedCashKpis = new Set();

function cashRowsHtml(rows, emptyText='暂无流水记录'){
  if(!rows.length) return `<div class="empty">${esc(emptyText)}</div>`;
  return rows.slice().sort((a,b)=>b.date.localeCompare(a.date)).map(x=>{
    const isInc = num(x.inc)>0;
    return `<div class="row" data-kind="cash" data-id="${esc(x.id)}">
      <div class="main">
        <div class="l1">
          <span class="title">${esc(x.type)}</span>
          <span class="amt ${isInc?'inc':'exp'}">${isInc?'+':'−'}¥${money(isInc?x.inc:x.exp)}</span>
        </div>
        <div class="l2">${esc(x.date)}${x.orderNo?' ｜ '+esc(x.orderNo):''}</div>
        <div class="l3">${esc(x.desc||'')}${x.note?' ｜ '+esc(x.note):''}</div>
      </div>
    </div>`;
  }).join('');
}

function toggleCashKpi(event){
  const button = event.target.closest('[data-cash-toggle]');
  if(!button || !$('cashKpis').contains(button)) return;
  const group = cashKpiGroups.find(g=>g.id===button.dataset.cashToggle);
  if(!group) return;
  const expanded = !expandedCashKpis.has(group.id);
  if(expanded) expandedCashKpis.add(group.id); else expandedCashKpis.delete(group.id);
  const panel = $(button.getAttribute('aria-controls'));
  if(expanded) panel.querySelector('.cash-kpi-list').innerHTML = cashRowsHtml(DB.cash.filter(group.match), group.empty);
  button.setAttribute('aria-expanded', String(expanded));
  panel.setAttribute('aria-hidden', String(!expanded));
  panel.inert = !expanded;
  button.closest('.cash-kpi').classList.toggle('is-open', expanded);
}

function renderCash(){
  const c = compute();
  $('cashKpis').innerHTML = cashKpiGroups.map(group=>{
    const rows = DB.cash.filter(group.match);
    const expanded = expandedCashKpis.has(group.id);
    return `<div class="kpi cash-kpi${expanded?' is-open':''}">
      <button type="button" class="cash-kpi-toggle" id="cash-toggle-${group.id}"
        data-cash-toggle="${group.id}" aria-expanded="${expanded}" aria-controls="cash-details-${group.id}">
        <span class="cash-kpi-summary"><span class="lab">${group.label}</span><span class="val ${group.color}">¥${money(c[group.value])}</span></span>
        <span class="cash-kpi-action"><span>${rows.length} 条</span><svg class="cash-kpi-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></span>
      </button>
      <div class="cash-kpi-details" id="cash-details-${group.id}" role="region"
        aria-labelledby="cash-toggle-${group.id}" aria-hidden="${!expanded}"${expanded?'':' inert'}>
        <div class="cash-kpi-clip"><div class="cash-kpi-list">${expanded?cashRowsHtml(rows, group.empty):''}</div></div>
      </div>
    </div>`;
  }).join('');
  $('cashCount').textContent = `共 ${DB.cash.length} 条`;

  const box = $('cashList');
  if(!DB.cash.length){
    box.innerHTML = `<div class="empty"><span class="big">💰</span>还没有流水记录<br>点下方「+ 记一笔」开始记账</div>`;
    return;
  }
  box.innerHTML = cashRowsHtml(DB.cash);
}

/* ---------- 渲染：月度汇总 ---------- */
/* 全程总账：从第一笔账到此刻的累计，每记一笔都会重算 */
function renderGl(){
  const box = $('glBox');
  if(!box){ return; }
  const c = compute(), t = c.totals;
  if(!t.totalOrders && !t.cashCount){
    box.innerHTML = `<div class="gl">
      <div class="gl-hd"><span class="t">📈 全程总账</span><span class="r">还没有数据</span></div>
      <div class="gl-empty">从你登记第一笔账开始，这里会自动累计<br>一共有多少收入、花了多少、净赚了多少</div>
    </div>`;
    return;
  }
  const pos = t.netProfit >= 0;
  const tot = Math.max(t.grossExpense + t.grossIncome, 0.01);
  /* 月均的分母：有数据的自然月数；只有 1 个月时不写「月均」以免误导 */
  const multi = t.liveMonths > 1;
  const settleRate = t.totalOrders ? (t.settledOrders / t.totalOrders * 100) : 0;
  box.innerHTML = `<div class="gl">
    <div class="gl-hd">
      <span class="t">📈 全程总账</span>
      <span class="r">${t.from ? esc(t.from) + ' 起 · 共 ' + t.liveMonths + ' 个月' : esc(cdate(t.to) || '')}</span>
    </div>

    <div class="gl-hero">
      <div class="cap">从第一笔账到现在，一共净赚</div>
      <div class="amt ${pos?'pos':'neg'}">${pos?'':'−'}¥${money(Math.abs(t.netProfit))}</div>
      <div class="sub">累计收入 <b>¥${money(t.grossIncome)}</b> ｜ 累计支出 ¥${money(t.grossExpense)}</div>
    </div>

    <div class="gl-bar">
      <div class="e" style="width:${(t.grossExpense/tot*100).toFixed(1)}%"></div>
      <div class="i" style="width:${(t.grossIncome/tot*100).toFixed(1)}%"></div>
    </div>

    <div class="gl-grid">
      <div class="gl-it"><div class="l">累计收入</div><div class="v pos">¥${money(t.grossIncome)}</div></div>
      <div class="gl-it"><div class="l">累计支出</div><div class="v neg">¥${money(t.grossExpense)}</div></div>
      <div class="gl-it"><div class="l">采购成本</div><div class="v">¥${money(c.cost)}</div></div>
      <div class="gl-it"><div class="l">发货运费</div><div class="v">¥${money(c.freight)}</div></div>
      <div class="gl-it"><div class="l">累计抹零/优惠</div><div class="v">¥${money(c.rounded)}</div></div>
      <div class="gl-it"><div class="l">还没收的尾款</div><div class="v ${c.receivable>0?'neg':''}">¥${money(c.receivable)}</div></div>
    </div>

    <div class="gl-line"><span class="k">一共做了多少单</span><span class="v">${t.totalOrders} 单</span></div>
    <div class="gl-line"><span class="k">已结清 / 已完成</span><span class="v">${t.settledOrders} 单 ｜ ${t.doneOrders} 单</span></div>
    ${t.totalOrders ? `<div class="gl-line"><span class="k">结清率</span><span class="v">${settleRate.toFixed(0)}%</span></div>` : ''}
    ${t.totalOrders ? `<div class="gl-line"><span class="k">平均每单净赚</span><span class="v">¥${money(t.perOrder)}</span></div>` : ''}
    ${multi ? `<div class="gl-line"><span class="k">月均净赚（${t.liveMonths} 个月）</span><span class="v ${t.avgProfit>=0?'':'neg'}">¥${money(t.avgProfit)}</span></div>` : ''}

    <div class="gl-ft">这两个数字跟着你记的每一笔实时变化 · 最后记账 ${t.to ? esc(t.to) : '—'}</div>
  </div>`;
}
/* 把 YYYY-MM-DD 写成「2026年10月9日」，空值原样返回 */
function cdate(d){
  const s = String(d||'');
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? (m[1] + '年' + Number(m[2]) + '月' + Number(m[3]) + '日') : s;
}

function renderSummary(){
  renderGl();
  const c = compute();
  const all = DB.cash.length + DB.orders.length;
  $('sumKpis').innerHTML = `
    <div class="kpi wide">
      <div class="lab">累计净利润（总收入 − 总支出）</div>
      <div class="val ${c.profit>=0?'inc':'exp'} hl">¥${money(c.profit)}</div>
    </div>
    <div class="kpi"><div class="lab">累计收入</div><div class="val inc">¥${money(c.income)}</div></div>
    <div class="kpi"><div class="lab">累计支出</div><div class="val exp">¥${money(c.expense)}</div></div>`;

  const box = $('sumList');
  if(!c.months.length){
    box.innerHTML = `<div class="empty"><span class="big">📊</span>还没有数据<br>先在「订单台账」或「收支明细」记上一笔<br>这里会自动统计</div>`;
    return;
  }
  box.innerHTML = c.months.map(m=>{
    const exp = m.cost + m.freight;
    const net = m.inc - exp;
    const tot = Math.max(exp + m.inc, 0.01);
    return `<div class="mrow">
      <div class="mh">
        <span class="mon">${esc(m.mon)}</span>
        <span class="net ${net>=0?'pos':'neg'}">${net>=0?'+':'−'}¥${money(Math.abs(net))}</span>
      </div>
      <div class="msplit">
        <span>采购 <b>¥${money(m.cost)}</b></span>
        <span>运费 <b>¥${money(m.freight)}</b></span>
        <span>收入 <b>¥${money(m.inc)}</b></span>
      </div>
      <div class="barwrap">
        <div class="bar-exp" style="width:${(exp/tot*100).toFixed(1)}%"></div>
        <div class="bar-inc" style="width:${(m.inc/tot*100).toFixed(1)}%"></div>
      </div>
      <div class="morder">订单：新增 ${m.newOrders} 单 ｜ 已完成 ${m.done} 单 ｜ 月末待收尾款 ¥${money(m.owe)}</div>
    </div>`;
  }).join('');
  if(!all) box.innerHTML = '';
}

function renderAll(){ renderOrders(); renderCash(); renderSummary(); }

/* ---------- 弹层管理 ---------- */
const sheet=$('sheet'), sheetIn=$('sheetIn');
function openSheet(html){ sheetIn.innerHTML=html; sheet.classList.add('on');
  sheetIn.scrollTop=0; }
function closeSheet(){ sheet.classList.remove('on'); sheetIn.innerHTML=''; }
sheet.addEventListener('click', e=>{ if(e.target===sheet) closeSheet(); });

/* ---------- 表单：订单 ---------- */
function orderForm(o){
  const isNew = !o;
  o = o || {date:today(),no:'',customer:'',phone:'',address:'',tracking:'',style:'',price:'',
            deposit:'',final:'',cut:'',status:ORDER_STATUS[0],note:''};
  openSheet(`
    <h2>${isNew?'新建订单':'编辑订单'}</h2>
    <div class="field"><label>下单日期 <span class="req">*</span></label>
      <input type="date" id="f_date" value="${esc(o.date)}"></div>
    <div class="field"><label>订单编号</label>
      <input type="text" id="f_no" value="${esc(o.no)}" placeholder="留空自动生成，如 DD20261008-01">
      <div class="hint">下单日期填好后留空，保存时会自动编号</div></div>
    <div class="field"><label>客户名称/昵称 <span class="req">*</span></label>
      <input type="text" id="f_customer" value="${esc(o.customer)}" placeholder="例如 小林、阿柚">
      <div class="hint">建议填客人下定金时用的那个名字，之后搜这个名字就能找到订单</div></div>
    <div class="field"><label>收货信息（姓名 / 电话 / 地址）</label>
      <textarea id="f_address" placeholder="例如：小林 13800138000 广东省深圳市南山区XX路XX号XX栋X单元">${esc(o.address)}</textarea>
      <div class="hint">写在一行里就行，不用分开填；发货时直接复制</div></div>
    <div class="field"><label>快递单号</label>
      <input type="text" id="f_tracking" value="${esc(o.tracking)}" placeholder="例如 77312345678901、SF1234567890">
      <div class="hint">发货后把单号填这里，客人来问时一搜就能找到</div></div>
    <div class="field"><label>包包款式/规格 <span class="req">*</span></label>
      <input type="text" id="f_style" value="${esc(o.style)}" placeholder="例如 帆布托特包·中号·米白">
      <div class="hint">可以直接打字，也可以点下面的常用款式快速填入（可多选，报价自动相加）</div>
      <div class="quickrow" id="styleQuick"></div>
      <div class="hint" id="styleSum" style="margin-top:4px"></div></div>
    <div class="field"><label>订单报价（元） <span class="req">*</span></label>
      <input type="number" id="f_price" inputmode="decimal" step="0.01" min="0"
        value="${o.price===''?'':esc(o.price)}" placeholder="0.00"></div>
    <div class="field"><label>已收定金（元）</label>
      <input type="number" id="f_deposit" inputmode="decimal" step="0.01" min="0"
        value="${o.deposit===''?'':esc(o.deposit)}" placeholder="没收到就填 0 或留空">
      <div class="hint">只填实际已经收到的金额；也可以点下面的常见档位</div>
      <div class="quickrow" id="depQuick"></div></div>
    <div class="field"><label>已收尾款（元）</label>
      <input type="number" id="f_final" inputmode="decimal" step="0.01" min="0"
        value="${o.final===''?'':esc(o.final)}" placeholder="没收到就填 0 或留空">
      <div class="hint">只填实际到账金额；修改金额会直接更新对应原流水，不会新增差额记录。</div></div>
    <div class="field" id="receiptDateField" hidden><label>本次收款日期</label>
      <input type="date" id="f_receiptDate" value="${esc(isNew ? o.date : today())}">
      <div class="hint">保存后自动登记定金、尾款，无需再记收入；月度汇总按收款日期统计。</div></div>
    <div class="field"><label>抹零 / 优惠（元）</label>
      <input type="number" id="f_cut" inputmode="decimal" step="0.01" min="0"
        value="${o.cut===''?'':esc(o.cut)}" placeholder="抹掉的零头填这里，没有就留空">
      <div class="hint">客人付尾款时你客气抹掉的那部分，填这里订单才能结清、利润才准确</div>
      <div class="quickrow" id="cutQuick"></div></div>
    <div class="calcbox multi">
      <div class="line"><span class="k">应收尾款（报价 − 定金）</span><span class="v" id="f_due">¥0.00</span></div>
      <div class="line"><span class="k">抹零 / 优惠</span><span class="v" id="f_cutshow">−¥0.00</span></div>
      <div class="line big"><span class="k">待收尾款</span><span class="v" id="f_owe">¥0.00</span></div>
    </div>
    <div class="field"><label>订单状态</label>
      <select id="f_status">${ORDER_STATUS.map(s=>`<option${s===o.status?' selected':''}>${s}</option>`).join('')}</select></div>
    <div class="field"><label>备注</label>
      <textarea id="f_note" placeholder="加急、定制要求、退款情况等">${esc(o.note)}</textarea></div>
    <div class="sheet-btns">
      ${isNew?'':'<button class="btn btn-danger" id="delBtn">删除</button>'}
      <button class="btn btn-sec" id="cancelBtn">取消</button>
      <button class="btn btn-pri" id="saveBtn">保存</button>
    </div>
    `);

  $('f_date').addEventListener('change', () => {
    if(isNew) $('f_receiptDate').value = $('f_date').value;
  });
  o._id = o.id;
  const P=$('f_price'), D=$('f_deposit'), F=$('f_final'), C=$('f_cut');
  const R = ()=> Math.max(0, num(P.value) - num(D.value) - num(F.value));  /* 还没抹零的零头 */

  const calc = ()=>{
    const needsReceiptDate = [['deposit',D,'收入-定金'],['final',F,'收入-尾款']].some(([kind,input,type])=>
      num(input.value)>0 && num(input.value)!==num(o[kind]) &&
      !DB.cash.some(row=>row.orderNo===o.no && row.type===type && num(row.inc)>0));
    $('receiptDateField').hidden = !needsReceiptDate;
    const r = R(), cut = num(C.value);
    $('f_due').textContent = '¥'+money(num(P.value)-num(D.value));
    $('f_cutshow').textContent = '−¥'+money(cut);
    const w = num(P.value) - cut - num(D.value) - num(F.value);
    const el = $('f_owe');
    el.textContent = '¥'+money(w);
    el.className = 'v' + (Math.abs(w)<=EPS ? ' ok' : '');
    if(Math.abs(w)<=EPS && num(P.value)>0 && (num(D.value)+num(F.value))>0){
      el.textContent = '¥0.00 · 已结清 ✓';
    }
    renderCutQuick(r, cut);
    renderDepQuick();
  };

  /* 定金快捷档位：25 / 10 / 无定金 */
  function renderDepQuick(){
    const box = $('depQuick'); if(!box) return;
    const cur = $('f_deposit').value;
    box.innerHTML = DEPOSIT_PRESETS.map(p=>{
      const on = cur !== '' && Math.abs(num(cur)-p.amount) < EPS;
      return `<button type="button" data-dep="${p.amount}"${on?' style="background:#E4F0FA;border-color:#B7D3EA"':''}>${p.label}</button>`;
    }).join('');
    box.querySelectorAll('button').forEach(b=>{
      b.onclick = ()=>{
        const amt = num(b.dataset.dep);
        $('f_deposit').value = amt === 0 ? '0' : money(amt);
        calc();
      };
    });
  }

  /* 一键填入常用抹零额度 */
  function renderCutQuick(r, cut){
    const box = $('cutQuick'); if(!box) return;
    if(r <= EPS){
      box.innerHTML = `<span style="font-size:11px;color:var(--muted)">当前没有零头需要抹</span>`;
      return;
    }
    box.innerHTML = CUT_PRESETS.map((p,i)=>{
      const amt = cutAmount(r, p.fn(r));
      if(amt<=0) return '';
      const on = Math.abs(amt-cut)<EPS;
      return `<button type="button" data-amt="${amt}"${on?' style="background:#E4F0FA;border-color:#B7D3EA"':''}>${p.label} −¥${money(amt)}</button>`;
    }).join('') + (cut>0?`<button type="button" data-amt="0">清除</button>`:'');
    box.querySelectorAll('button').forEach(b=>{
      b.onclick = ()=>{ C.value = b.dataset.amt==='0' ? '' : b.dataset.amt; calc(); };
    });
  }

  /* 常用款式：多选 + 每款数量；款式框写「名 ×N」，报价 = 单价 × 数量 求和 */
  let picked = [];   /* [{name, qty}] */
  /* 同步款式框文本 + 报价（报价 = 单价 × 数量 之和，直接覆盖） */
  function syncFromPicked(){
    $('f_style').value = stylesToText(picked);
    const total = stylesTotal(picked);
    if(picked.length && total > 0) $('f_price').value = money(total);
  }
  /* 以下三个用行内 onclick 调用：必须挂到 window 上（行内属性只在全局作用域求值） */
  window.quickPick = function(el){
    const v = el && el.dataset ? el.dataset.style : null;
    if(v === undefined || v === null || v === '') return;
    const i = picked.map(x=>x.name).indexOf(v);
    if(i > -1) picked.splice(i,1); else picked.push({ name:v, qty:1 });
    syncFromPicked(); refreshStyleUI(); calc();
  };
  window.quickQty = function(el, d){
    const v = el && el.dataset ? (d > 0 ? el.dataset.plus : el.dataset.minus) : null;
    if(v === undefined || v === null || v === '') return;
    const it = picked.filter(x=>x.name===v)[0];
    if(!it) return;
    if(d > 0) it.qty = Math.min(999, (num(it.qty)||1) + 1);
    else {
      const q = (num(it.qty)||1) - 1;
      if(q <= 0) picked = picked.filter(x=>x.name!==v); else it.qty = q;
    }
    syncFromPicked(); refreshStyleUI(); calc();
  };
  window.quickClear = function(){ picked = []; $('f_style').value = ''; refreshStyleUI(); calc(); };
  /* 供自动化测试/控制台取用 */
  window.__quick = { pick: window.quickPick, qty: window.quickQty, clear: window.quickClear };
  function renderStyleQuick(){
    const box = $('styleQuick'); if(!box) return;
    const list = styleList();
    const names = list.map(s=>s.name);
    picked = picked.filter(x => names.indexOf(x.name) > -1);   /* 库里已删的自动去掉 */
    if(!list.length){
      box.innerHTML = `<span style="font-size:11px;color:var(--muted)">还没有常用款式，点右上角「⋯ → 管理常用款式」添加</span>`;
      return;
    }
    const at = {}; picked.forEach(x=>{ at[x.name] = x; });
    box.innerHTML = list.map(s=>{
      const on = !!at[s.name];
      const pr = num(s.price) > 0 ? ' ¥'+money(s.price) : '';
      if(!on) return `<button type="button" data-style="${esc(s.name)}" onclick="quickPick(this)">${esc(s.name)}${pr}</button>`;
      /* 已选：显示名称 + 数量步进器 */
      const q = num(at[s.name].qty) || 1;
      return `<span class="stpick">
        <button type="button" class="pj" data-style="${esc(s.name)}" onclick="quickPick(this)">${esc(s.name)}${pr}</button>
        <button type="button" class="qminus" data-minus="${esc(s.name)}" onclick="quickQty(this,-1)">−</button>
        <span class="qnum">${q}</span>
        <button type="button" class="qplus" data-plus="${esc(s.name)}" onclick="quickQty(this,1)">+</button>
      </span>`;
    }).join('') + (picked.length ? `<button type="button" data-clear="1" onclick="quickClear()">清除选择</button>` : '');
  }
  /* 选中摘要：已选 2 款 3 个：帆布托特包 ¥68 ×2 + 挂饰 ¥15 = ¥151.00 */
  function renderStyleSum(){
    const el = $('styleSum'); if(!el) return;
    if(!picked.length){ el.innerHTML = ''; return; }
    const parts = picked.map(x => {
      const pr = stylePrice(x.name);
      const q = num(x.qty) || 1;
      return pr > 0 ? x.name + ' ¥' + money(pr) + (q>1 ? ' ×' + q : '') : x.name + (q>1 ? ' ×' + q : '');
    });
    const totalQty = picked.reduce((a,x)=> a + (num(x.qty)||1), 0);
    el.innerHTML = '已选 ' + picked.length + ' 款 ' + totalQty + ' 个：' + parts.map(esc).join(' + ') +
      ' = <b>¥' + money(stylesTotal(picked)) + '</b>';
  }
  function refreshStyleUI(){ renderStyleQuick(); renderStyleSum(); }
  /* 编辑旧订单时回填：款式名用「 + 」分隔、可带 ×N 的，自动还原选中与数量 */
  function initStylePickers(){
    picked = [];
    const cur = String($('f_style').value||'').trim();
    const byName = {}; styleList().forEach(s=>{ byName[s.name] = 1; });
    if(cur){
      textToStyles(cur).forEach(it=>{
        if(byName[it.name] && picked.map(x=>x.name).indexOf(it.name) === -1) picked.push({ name:it.name, qty:it.qty });
      });
    }
    /* 已有订单里写了数量、但报价是「单价×数量」的，回填时同步一次报价 */
    if(picked.length) syncFromPicked();
    refreshStyleUI();
  }
  $('f_style').addEventListener('input', ()=>{
    /* 手改款式框时也还原选中态；不重建按钮，避免打断光标与事件绑定 */
    const byName = {}; styleList().forEach(s=>{ byName[s.name] = 1; });
    const next = textToStyles($('f_style').value).filter(it => byName[it.name]);
    /* 数量以文本框里写的为准；只有数量没变时才复用原对象，避免步进器抖动 */
    picked = next.map(it=>{
      const old = picked.filter(x=>x.name===it.name)[0];
      return (old && num(old.qty) === num(it.qty)) ? old : { name:it.name, qty:it.qty };
    });
    renderStyleQuick(); renderStyleSum();
  });
  initStylePickers();

  [P,D,F,C].forEach(el=> el.addEventListener('input', calc));
  calc();

  $('cancelBtn').onclick = closeSheet;
  $('saveBtn').onclick = async ()=>{
    const date=$('f_date').value.trim();
    const customer=$('f_customer').value.trim();
    const style=$('f_style').value.trim();
    if(!date){ toast('请填下单日期'); return; }
    if(!customer){ toast('请填客户名称'); return; }
    if(!style){ toast('请填包包款式'); return; }
    if($('f_price').value===''||num($('f_price').value)<0){ toast('请填订单报价'); return; }
    if (!$('receiptDateField').hidden && !$('f_receiptDate').value) { toast('请填本次收款日期'); return; }

    let no=$('f_no').value.trim();
    const rec = {
      id: o._id || uid(),
      date, no,
      customer, style,
      phone: o.phone || '',
      address: $('f_address').value.trim(),
      tracking: $('f_tracking').value.trim(),
      price: num($('f_price').value),
      deposit: num($('f_deposit').value),
      final: num($('f_final').value),
      cut: num($('f_cut').value),
      status: $('f_status').value,
      note: $('f_note').value.trim(),
      ph: Array.isArray(o.ph) ? o.ph.slice() : []
    };
    if(!no) rec.no = genOrderNo(date);

    if(o._id){
      const i = DB.orders.findIndex(x=>x.id===o._id);
      if(i>-1) DB.orders[i]=rec; else DB.orders.push(rec);
    } else {
      DB.orders.push(rec);
    }
    if (!await save(DB, {receiptDate: $('receiptDateField').hidden ? undefined : $('f_receiptDate').value})) return;
    closeSheet(); renderAll(); toast('已保存，收支和汇总已同步 ✓');
  };
  if($('delBtn')){
    $('delBtn').onclick = async ()=>{
      if(!confirm('确定删除这条订单吗？删除后无法恢复。')) return;
      DB.orders = DB.orders.filter(x=>x.id!==o._id);
      if (!await save()) return; closeSheet(); renderAll(); toast('已删除');
    };
  }

}

/* ---------- 表单：收支 ---------- */
function cashForm(x){
  const isNew = !x;
  x = x || {date:today(),type:'采购-布料',orderNo:'',desc:'',exp:'',inc:'',note:''};
  const orderOpts = DB.orders.map(o=>`<option value="${esc(o.no)}"${o.no===x.orderNo?' selected':''}>${esc(o.no)} · ${esc(o.customer)}</option>`).join('');
  openSheet(`
    <h2>${isNew?'记一笔收支':'编辑收支'}</h2>
    <div class="field"><label>日期 <span class="req">*</span></label>
      <input type="date" id="c_date" value="${esc(x.date)}"></div>
    <div class="field"><label>收支类型 <span class="req">*</span></label>
      <select id="c_type">${CASH_TYPES.map(t=>`<option${t===x.type?' selected':''}>${t}</option>`).join('')}</select></div>
    <div class="field"><label>对应订单编号（收入类建议选）</label>
      <select id="c_orderNo"><option value="">— 不关联订单 —</option>${orderOpts}</select>
      <div class="hint">订单定金、尾款会自动登记，请勿重复记账；修改关联收入也会同步订单已收金额。</div></div>
    <div class="field"><label>物品/事项说明 <span class="req">*</span></label>
      <input type="text" id="c_desc" value="${esc(x.desc)}"
        placeholder="如 厚帆布2米 / 【第38周合并多单发货运费，共3个包裹】">
      <div class="hint">运费请写明第几周、一共多少个包裹</div></div>
    <div class="field"><label>支出金额（元）</label>
      <input type="number" id="c_exp" inputmode="decimal" step="0.01" min="0"
        value="${x.exp===''?'':esc(x.exp)}" placeholder="支出填这里，正数">
      <div class="hint">采购、运费填这里；收入类留空</div></div>
    <div class="field"><label>收入金额（元）</label>
      <input type="number" id="c_inc" inputmode="decimal" step="0.01" min="0"
        value="${x.inc===''?'':esc(x.inc)}" placeholder="收入填这里，正数">
      <div class="hint">定金、尾款填这里；<b>填实际到账的金额</b>（客户抹零后实付多少就填多少），支出类留空</div></div>
    <div class="field"><label>备注</label>
      <textarea id="c_note" placeholder="其他补充信息">${esc(x.note)}</textarea></div>
    <div class="sheet-btns">
      ${isNew?'':'<button class="btn btn-danger" id="delBtn">删除</button>'}
      <button class="btn btn-sec" id="cancelBtn">取消</button>
      <button class="btn btn-pri" id="saveBtn">保存</button>
    </div>`);

  const curId = x.id;
  // 类型切换时自动把另一边清空，避免同时填两边
  const typeSel=$('c_type'), expI=$('c_exp'), incI=$('c_inc');
  function syncType(){
    const isInc = typeSel.value.indexOf('收入')===0;
    expI.disabled = isInc; incI.disabled = !isInc;
    expI.style.opacity = isInc?'.45':'1';
    incI.style.opacity = isInc?'1':'.45';
  }
  typeSel.addEventListener('change', ()=>{ syncType(); });
  syncType();

  $('cancelBtn').onclick = closeSheet;
  $('saveBtn').onclick = async ()=>{
    const date=$('c_date').value.trim();
    const desc=$('c_desc').value.trim();
    const type=$('c_type').value;
    const isInc = type.indexOf('收入')===0;
    if(!date){ toast('请填日期'); return; }
    if(!desc){ toast('请填物品/事项说明'); return; }
    const e = isInc?0:num(expI.value), i = isInc?num(incI.value):0;
    if(e===0 && i===0){ toast('请填金额'); return; }
    const rec = {
      id: curId || uid(),
      date, type,
      orderNo: $('c_orderNo').value,
      desc,
      exp: e, inc: i,
      note: $('c_note').value.trim()
    };
    if(curId){
      const k = DB.cash.findIndex(y=>y.id===curId);
      if(k>-1) DB.cash[k]=rec; else DB.cash.push(rec);
    } else DB.cash.push(rec);
    if (!await save()) return; closeSheet(); renderAll(); toast('已保存 ✓');
  };
  if($('delBtn')){
    $('delBtn').onclick = async ()=>{
      if(!confirm('确定删除这条记录吗？删除后无法恢复。')) return;
      DB.cash = DB.cash.filter(y=>y.id!==curId);
      if (!await save()) return; closeSheet(); renderAll(); toast('已删除');
    };
  }
}

/* ---------- 新增入口（按当前页签） ---------- */
let curTab='orders';
function onAdd(){
  if(curTab==='orders') orderForm(null); else cashForm(null);
}
function syncAddBtn(){
  $('addBtn').textContent = curTab==='orders' ? '+ 记一笔订单' : '+ 记一笔收支';
}

/* ---------- 更多菜单 ---------- */
function menuForm(){
  openSheet(`
    <h2>更多</h2>
    <div class="sheet-btns" style="flex-direction:column;gap:9px">
      <button class="btn btn-pri" id="mExport">📥 导出 Excel（.xlsx）</button>
      <button class="btn btn-sec" id="mStyles">🏷 管理常用款式</button>
      <button class="btn btn-sec" id="mBackup">💾 备份数据（.json）</button>
      <button class="btn btn-sec" id="mRestore">📤 恢复备份</button>
      <button class="btn btn-danger" id="mClear">🗑 清空所有数据</button>
      <button class="btn btn-sec" id="mClose">关闭</button>
    </div>
    <div class="notes" style="margin-top:14px">
      <p class="nt">💡 关于数据安全</p>
      <p>1. 数据保存在<b>运行服务的这台电脑</b>里，通过局域网访问，不上传外网。</p>
      <p>2. 手机和电脑访问同一个服务，使用同一份账本；清除手机浏览器缓存不会清空电脑上的数据。</p>
      <p>3. 建议每隔一段时间点「导出 Excel」或「备份数据」存一份到微信收藏/电脑，最稳妥。</p>
      <p class="nt" style="margin-top:10px">📲 添加到手机桌面（推荐）</p>
      <p>安卓浏览器：右上角 ⋮ 菜单 →「添加到主屏幕」。</p>
      <p>iPhone：用 Safari 打开 → 分享按钮 →「添加到主屏幕」。</p>
      <p>添加后像 App 一样点开即用，不用再找链接。</p>
    </div>`);
  $('mClose').onclick = closeSheet;
  $('mExport').onclick = ()=>{ closeSheet(); exportExcel(); };
  $('mStyles').onclick = ()=>{ closeSheet(); styleForm(); };
  $('mBackup').onclick = ()=>{ closeSheet(); backup(); };
  $('mRestore').onclick = ()=>{ closeSheet(); restore(); };
  $('mClear').onclick = async ()=>{
    if(!confirm('确定清空所有订单和流水吗？\n此操作不可恢复，建议先导出备份。')) return;
    if(!confirm('再次确认：真的要清空全部数据吗？')) return;
    DB={orders:[],cash:[],seq:{},styles:[]}; if (!await save()) return; closeSheet(); renderAll(); toast('已清空');
  };
}

/* ---------- 常用款式管理 ---------- */
function styleForm(){
  const render = ()=>{
    const list = styleList();
    const rows = list.length
      ? list.map(s=>{
          const used = usedStyleCount(s.name);
          return `<div class="stylerow">
            <span class="nm">${esc(s.name)}</span>
            <input type="number" class="pr" inputmode="decimal" step="0.01" min="0"
              data-price="${esc(s.name)}" value="${s.price>0?esc(s.price):''}" placeholder="单价">
            <span class="use">${used?`${used} 单在用`:'未使用'}</span>
            <button type="button" data-del="${esc(s.name)}">删除</button>
          </div>`;
        }).join('')
      : `<div style="font-size:12.5px;color:var(--muted);padding:8px 2px">还没有常用款式，在下面输入框添加吧</div>`;
    return `
      <h2>常用款式</h2>
      <div class="hint" style="margin:-4px 0 10px">在这里维护你常做的款式和单价；下单时在「包包款式」下面点一下就能填入，报价会自动相加。</div>
      <div class="stylelist">${rows}</div>
      <div class="field" style="margin-top:12px"><label>新增款式</label>
        <input type="text" id="st_new" placeholder="例如 帆布托特包·中号·米白">
        <div class="hint">填你习惯的叫法就行，可含尺寸和颜色</div></div>
      <div class="field"><label>单价（元，可留空）</label>
        <input type="number" id="st_price" inputmode="decimal" step="0.01" min="0" placeholder="0.00">
        <div class="hint">填了以后，下单点选这个款式，报价就会自动加上这个金额</div></div>
      <div class="sheet-btns">
        <button class="btn btn-sec" id="st_close">关闭</button>
        <button class="btn btn-pri" id="st_add">添加</button>
      </div>`;
  };

  const bind = ()=>{
    const add = async ()=>{
      const el = $('st_new'); if(!el) return;
      const v = el.value.trim();
      if(!v){ toast('请先填写款式名称'); return; }
      const pr = $('st_price') ? $('st_price').value.trim() : '';
      if(!addStyle(v, pr===''?0:num(pr))){ toast('这个款式已经在列表里了'); return; }
      if (!await save()) return; toast('已添加 ✓');
      openSheet(render()); bind();
    };
    const el = $('st_new');
    if(el) el.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); add(); } });
    const pe = $('st_price');
    if(pe) pe.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); add(); } });
    /* 行内改单价：失焦或回车即保存 */
    sheetIn.querySelectorAll('[data-price]').forEach(inp=>{
      const commit = async ()=>{
        const name = inp.dataset.price;
        const v = inp.value.trim();
        if(Math.abs(stylePrice(name) - num(v)) < EPS) return;
        setStylePrice(name, v===''?0:num(v));
        if (!await save()) return; toast('单价已更新 ✓');
      };
      inp.addEventListener('blur', commit);
      inp.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); commit(); inp.blur(); } });
    });
    const ab = $('st_add'); if(ab) ab.onclick = add;
    const cb = $('st_close'); if(cb) cb.onclick = ()=>{ closeSheet(); renderAll(); };
    sheetIn.querySelectorAll('[data-del]').forEach(b=>{
      b.onclick = async ()=>{
        const name = b.dataset.del;
        const used = usedStyleCount(name);
        const msg = used
          ? `「${name}」已被 ${used} 个订单使用。\n删除后不影响已有订单（它们仍保留这个款式），只是以后不再出现在快捷选择里。\n确定删除吗？`
          : `确定删除款式「${name}」吗？`;
        if(!confirm(msg)) return;
        removeStyle(name); if (!await save()) return; toast('已删除');
        openSheet(render()); bind();
      };
    });
  };

  openSheet(render()); bind();
}

/* ---------- 备份 / 恢复 ---------- */
async function backup(){
  try {
    const data = await request('/api/book/backup');
    download(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}), `手作包包记账_备份_${today()}.json`);
    toast('备份文件已下载 ✓');
  } catch(error) { toast(error.message, 4000); }
}
function restore(){
  const inp=document.createElement('input');
  inp.type='file'; inp.accept='.json,application/json';
  inp.onchange=async ()=>{
    const file=inp.files&&inp.files[0]; if(!file) return;
    try {
      const raw=JSON.parse(await file.text()), data=raw.data||raw;
      const cash=Array.isArray(data.cash)?data.cash:data.transactions;
      if(!Array.isArray(data.orders)||!Array.isArray(cash)) throw new Error('文件格式不正确');
      if(!confirm(`将导入 ${data.orders.length} 条订单、${cash.length} 条流水。\n当前数据会被覆盖，确定继续？`)) return;
      if(!await save(raw, {restore: true})) return;
      renderAll(); toast('恢复成功 ✓');
    } catch(error) { toast(error instanceof SyntaxError?'文件格式不正确':error.message, 4000); }
  };
  inp.click();
}

/* ---------- 导出 Excel（复用 Excel 结构 + 配色） ---------- */
const XL={mint:'B7DFC8',pink:'F7DCE4',green:'C6E8D5',blue:'D5E5F2',
  cream:'FDF3E3',rowA:'FBFDFB',rowB:'FFFFFF',bd:'D9E8DF',
  tx:'4A4A4A',inc:'2E6B52',exp:'B4655A',hl:'FFF6D6',
  dIn:'F0FAF4',dSt:'FDF2F6'};

function xesc(s){
  return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
/* 生成一张 sheet 的 XML */
function sheetXml(rows, colWidths, dv){
  const cols = colWidths.map((w,i)=>
    `<col min="${i+1}" max="${i+1}" width="${w}" customWidth="1"/>`).join('');
  const body = rows.map(r=>{
    const cells = r.cells.map((c,ci)=>{
      if(c==null||c.v===''||c.v==null) {
        const st = c&&c.s!=null?` s="${c.s}"`:'';
        return `<c r="${colLetter(ci)}${r.n}"${st}/>`;
      }
      const st = c.s!=null?` s="${c.s}"`:'';
      if(c.t==='n') return `<c r="${colLetter(ci)}${r.n}"${st}><v>${c.v}</v></c>`;
      return `<c r="${colLetter(ci)}${r.n}"${st} t="inlineStr"><is><t xml:space="preserve">${xesc(c.v)}</t></is></c>`;
    }).join('');
    const ht = r.h?` ht="${r.h}" customHeight="1"`:'';
    return `<row r="${r.n}"${ht}>${cells}</row>`;
  }).join('');
  const dvXml = dv && dv.length ? `<dataValidations count="${dv.length}">${
    dv.map(d=>`<dataValidation type="list" allowBlank="1" showInputMessage="1" showErrorMessage="1" sqref="${d.sqref}"><formula1>${xesc(d.list)}</formula1></dataValidation>`).join('')
  }</dataValidations>` : '';
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="${rows.length&&rows[0].freeze?rows[0].freeze:1}" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="18"/>
<cols>${cols}</cols>
<sheetData>${body}</sheetData>
${dvXml}
</worksheet>`;
}
function colLetter(i){
  let s=''; i++;
  while(i>0){ const m=(i-1)%26; s=String.fromCharCode(65+m)+s; i=Math.floor((i-1)/26); }
  return s;
}

function exportExcel(){
  const c = compute();
  const S = {
    title:1, hdrP:2, hdrG:3, hdrB:4,
    lbl:5, tx:6, txB:7, inc:8, exp:9, incB:10, expB:11, hl:12, hlB:13,
    dropIn:14, dropSt:15, cream:16, wrapTx:17
  };
  const styles = `
  <fonts count="9">
    <font><sz val="10"/><color rgb="FF${XL.tx}"/><name val="微软雅黑"/></font>
    <font><b/><sz val="15"/><color rgb="FF${XL.tx}"/><name val="微软雅黑"/></font>
    <font><b/><sz val="11"/><color rgb="FF${XL.tx}"/><name val="微软雅黑"/></font>
    <font><sz val="10"/><color rgb="FF${XL.inc}"/><name val="微软雅黑"/></font>
    <font><sz val="10"/><color rgb="FF${XL.exp}"/><name val="微软雅黑"/></font>
    <font><b/><sz val="10"/><color rgb="FF${XL.tx}"/><name val="微软雅黑"/></font>
    <font><b/><sz val="10"/><color rgb="FF${XL.inc}"/><name val="微软雅黑"/></font>
    <font><b/><sz val="10"/><color rgb="FF${XL.exp}"/><name val="微软雅黑"/></font>
    <font><sz val="9"/><color rgb="FF8A9A92"/><name val="微软雅黑"/></font>
  </fonts>
  <fills count="11">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.rowA}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.rowB}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.pink}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.green}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.blue}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.cream}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.hl}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.dIn}"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF${XL.dSt}"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FF${XL.bd}"/></left><right style="thin"><color rgb="FF${XL.bd}"/></right><top style="thin"><color rgb="FF${XL.bd}"/></top><bottom style="thin"><color rgb="FF${XL.bd}"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="${S.wrapTx+1}">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="7" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="5" fillId="7" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="5" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="2" fontId="3" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="2" fontId="4" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="2" fontId="6" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="2" fontId="7" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="2" fontId="7" fillId="8" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="0" fontId="7" fillId="8" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="9" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="10" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="7" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>`;

  const wb = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">${styles}</styleSheet>`;

  /* --- Sheet1 订单台账 --- */
  const oRows=[]; let n=1;
  oRows.push({n:n++, h:32, cells:[{v:'📦 订单台账 · 记录每一个订单的收款进度（待收尾款自动计算）',s:S.title}]});
  const oHdr=['下单日期','订单编号','客户名称/昵称','收货信息（姓名/电话/地址）','快递单号','包包款式/规格','订单报价（元）','已收定金（元）','已收尾款（元）','抹零/优惠（元）','待收尾款（元）','订单状态','备注'];
  oRows.push({n:n++, h:30, cells:oHdr.map(h=>({v:h,s:S.hdrP}))});
  let oSum={p:0,d:0,f:0,c:0,w:0};
  const oFirst = n;   // 第一条数据行
  DB.orders.slice().sort((a,b)=>a.date<b.date?-1:1).forEach(o=>{
    const w=Math.max(0,owe(o));
    oSum.p+=num(o.price); oSum.d+=num(o.deposit); oSum.f+=num(o.final);
    oSum.c+=num(o.cut); oSum.w+=w;
    oRows.push({n:n++, cells:[
      {v:o.date,s:S.tx},{v:o.no,s:S.tx},{v:o.customer,s:S.tx},{v:o.address,s:S.wrapTx},
      {v:o.tracking,s:S.tx},{v:o.style,s:S.tx},
      {v:num(o.price),t:'n',s:S.exp},{v:num(o.deposit),t:'n',s:S.inc},{v:num(o.final),t:'n',s:S.inc},
      {v:num(o.cut),t:'n',s:S.exp},{v:w,t:'n',s:S.hlB},{v:o.status,s:S.dropSt},{v:o.note,s:S.tx}
    ]});
  });
  const oLast = Math.max(n-1, oFirst);   // 最后一条数据行（无数据时退化为首行）
  oRows.push({n:n++, cells:[
    {v:'合计',s:S.lbl},{v:'',s:S.lbl},{v:'',s:S.lbl},{v:'',s:S.lbl},{v:'',s:S.lbl},{v:'',s:S.lbl},
    {v:oSum.p,t:'n',s:S.hlB},{v:oSum.d,t:'n',s:S.hlB},{v:oSum.f,t:'n',s:S.hlB},
    {v:oSum.c,t:'n',s:S.hlB},{v:oSum.w,t:'n',s:S.hlB},
    {v:'',s:S.lbl},{v:'报价 / 已收 / 抹零 / 待收 合计',s:S.lbl}
  ]});
  oRows.push({n:n++, h:22, cells:[{v:'📝 使用说明 · 订单台账（本表由记账本导出）',s:S.cream}]});
  ['1. 客户下单就在这里建一行，登记客户、款式、报价；收到定金/尾款就更新「已收定金」「已收尾款」列，状态同步切换。',
   '2. 「待收尾款」= 报价 − 抹零/优惠 − 定金 − 尾款，已由网页版自动算好。',
   '3. 客户尾款抹零头（如应收 41.7、实收 41）时，把差额 0.7 填进「抹零/优惠」列，订单即可结清，利润统计也准确。',
   '4. 订单状态只有三档：已收定金-待制作 / 已收尾款-待发货 / 已完成。',
   '5. 同一笔定金/尾款需同时在【收支明细】登记一行（填实际到账金额），两张表才能对上。',
   '6. 「快递单号」发货后补填；客人拿着单号来问，直接在网页版搜索框输入单号就能定位到这一单。',
   '7. 如当月出现退款/退货，请在备注注明，并从对应收入中体现，避免利润虚高。'
  ].forEach(t=>oRows.push({n:n++, h:19, cells:[{v:t,s:S.cream}]}));

  /* --- Sheet2 收支明细 --- */
  const cRows=[]; let m=1;
  cRows.push({n:m++, h:32, cells:[{v:'💰 收支明细 · 日常记账，所有真实现金流都在这里',s:S.title}]});
  const cHdr=['日期','收支类型','对应订单编号（可选）','物品/事项说明','支出金额','收入金额','备注'];
  cRows.push({n:m++, h:30, cells:cHdr.map(h=>({v:h,s:S.hdrG}))});
  let cE=0,cI=0;
  const cFirst = m;
  DB.cash.slice().sort((a,b)=>a.date<b.date?-1:1).forEach(x=>{
    cE+=num(x.exp); cI+=num(x.inc);
    cRows.push({n:m++, cells:[
      {v:x.date,s:S.tx},{v:x.type,s:S.dropIn},{v:x.orderNo,s:S.tx},{v:x.desc,s:S.tx},
      x.exp?{v:num(x.exp),t:'n',s:S.exp}:{v:'',s:S.tx},
      x.inc?{v:num(x.inc),t:'n',s:S.inc}:{v:'',s:S.tx},
      {v:x.note,s:S.tx}
    ]});
  });
  const cLast = Math.max(m-1, cFirst);
  cRows.push({n:m++, cells:[
    {v:'合计',s:S.lbl},{v:'',s:S.lbl},{v:'',s:S.lbl},{v:'',s:S.lbl},
    {v:cE,t:'n',s:S.hlB},{v:cI,t:'n',s:S.hlB},{v:'支出 / 收入 合计',s:S.lbl}
  ]});
  cRows.push({n:m++, h:22, cells:[{v:'📝 使用说明 · 收支明细（本表由记账本导出）',s:S.cream}]});
  ['1. 每一笔业务占 1 行；买一次布一行；每周全部包裹的总运费只记 1 行，说明写清第几周、一共多少个包裹；收到定金一行、尾款一行。',
   '2. 金额全部填正数，不要填负数；支出填「支出金额」，收入填「收入金额」。',
   '3. 买布、买辅料、买工具都属于支出，工具一次性采购计入当月成本，贵的工具请在备注写明。',
   '4. 如当月出现退款/退货，请在备注注明，并从对应收入中冲减，避免利润虚高。'
  ].forEach(t=>cRows.push({n:m++, h:19, cells:[{v:t,s:S.cream}]}));

  /* --- Sheet3 月度汇总（静态结果） --- */
  const sRows=[]; let k=1;
  sRows.push({n:k++, h:32, cells:[{v:'📈 全程总账 · 从第一笔账到导出时的累计（实时统计）',s:S.title}]});
  const t = c.totals;
  if(t.totalOrders || t.cashCount){
    const tHdr=['项目','数值','说明'];
    sRows.push({n:k++, h:30, cells:tHdr.map(h=>({v:h,s:S.hdrB}))});
    /* 起算到现在的关键数字，一行一项，便于直接看 */
    sRows.push({n:k++, cells:[{v:'起算日期',s:S.lbl},{v:t.from||'—',s:S.txB},
      {v:'从登记的第一笔账开始算',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'记账月数',s:S.lbl},{v:t.liveMonths,t:'n',s:S.txB},
      {v:'有记账数据的自然月数',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'累计收入（元）',s:S.lbl},{v:t.grossIncome,t:'n',s:S.incB},
      {v:'收支明细里所有收入的合计',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'累计支出（元）',s:S.lbl},{v:t.grossExpense,t:'n',s:S.expB},
      {v:'采购 + 运费 + 其他所有支出的合计',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'累计净利润（元）',s:S.lbl},{v:t.netProfit,t:'n',s:S.hlB},
      {v:'累计收入 − 累计支出',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'其中：采购成本（元）',s:S.lbl},{v:c.cost,t:'n',s:S.exp},
      {v:'布料 + 耗材辅料 + 工具',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'其中：发货运费（元）',s:S.lbl},{v:c.freight,t:'n',s:S.exp},
      {v:'每周合并发货运费',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'累计抹零/优惠（元）',s:S.lbl},{v:c.rounded,t:'n',s:S.expB},
      {v:'让给客户的零头合计，仅作参考',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'还没收的尾款（元）',s:S.lbl},{v:c.receivable,t:'n',s:S.hlB},
      {v:'全部订单待收尾款合计',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'一共做了多少单',s:S.lbl},{v:t.totalOrders,t:'n',s:S.txB},
      {v:'订单台账里的订单总数',s:S.tx}]});
    sRows.push({n:k++, cells:[{v:'已结清 / 已完成（单）',s:S.lbl},
      {v:t.settledOrders + ' / ' + t.doneOrders,s:S.txB},
      {v:'已结清＝待收尾款为 0',s:S.tx}]});
    if(t.totalOrders){
      sRows.push({n:k++, cells:[{v:'结清率',s:S.lbl},
        {v:(t.settledOrders/t.totalOrders*100).toFixed(1)+'%',s:S.txB},
        {v:'已结清订单 ÷ 总订单',s:S.tx}]});
      sRows.push({n:k++, cells:[{v:'平均每单净赚（元）',s:S.lbl},{v:t.perOrder,t:'n',s:S.txB},
        {v:'累计净利润 ÷ 总订单',s:S.tx}]});
    }
    if(t.liveMonths > 1){
      sRows.push({n:k++, cells:[{v:'月均净赚（元）',s:S.lbl},{v:t.avgProfit,t:'n',s:S.hlB},
        {v:'累计净利润 ÷ ' + t.liveMonths + ' 个月',s:S.tx}]});
      sRows.push({n:k++, cells:[{v:'月均收入（元）',s:S.lbl},{v:t.avgIncome,t:'n',s:S.incB},
        {v:'累计收入 ÷ ' + t.liveMonths + ' 个月',s:S.tx}]});
    }
    sRows.push({n:k++, h:6, cells:[{v:'',s:S.tx}]});
  }

  sRows.push({n:k++, h:32, cells:[{v:'📊 月度汇总 · 每月赚了多少钱（自动统计）',s:S.title}]});
  const sHdr=['月份','总采购成本（元）','总发货运费（元）','总支出合计（元）','总收入合计（元）','抹零/优惠合计（元）','本月净利润（元）','订单情况（新增 / 已完成 / 月末待收尾款）','备注'];
  sRows.push({n:k++, h:30, cells:sHdr.map(h=>({v:h,s:S.hdrB}))});
  c.months.slice().sort((a,b)=>a.mon<b.mon?-1:1).forEach(mm=>{
    const exp=mm.cost+mm.freight, net=mm.inc-exp;
    sRows.push({n:k++, cells:[
      {v:mm.mon,s:S.txB},{v:mm.cost,t:'n',s:S.exp},{v:mm.freight,t:'n',s:S.exp},
      {v:exp,t:'n',s:S.expB},{v:mm.inc,t:'n',s:S.incB},
      {v:mm.rounded,t:'n',s:S.expB},
      {v:net,t:'n',s:net>=0?S.hlB:S.hlB},
      {v:`${mm.newOrders} 单新增 ｜ 已完成 ${mm.done} 单 ｜ 月末待收尾款 ${mm.owe.toFixed(2)} 元`,s:S.tx},
      {v:'',s:S.tx}
    ]});
  });
  sRows.push({n:k++, cells:[
    {v:'合计',s:S.lbl},
    {v:c.cost,t:'n',s:S.hlB},{v:c.freight,t:'n',s:S.hlB},{v:c.expense,t:'n',s:S.hlB},
    {v:c.income,t:'n',s:S.hlB},{v:c.rounded,t:'n',s:S.hlB},{v:c.profit,t:'n',s:S.hlB},
    {v:'累计',s:S.lbl},{v:'',s:S.lbl}
  ]});
  sRows.push({n:k++, h:22, cells:[{v:'📝 使用说明 · 月度汇总（为导出时点的静态结果）',s:S.cream}]});
  ['1. 本表数字为导出瞬间的统计结果，修改需回到网页版操作后再重新导出。',
   '2. 最上面的「📈 全程总账」是从你登记的第一笔账算到导出时的累计数，网页版里每记一笔都会自动更新。',
   '3. 总采购成本 = 布料 + 耗材辅料 + 工具；总发货运费 = 每周合并发货运费；总收入 = 定金 + 尾款（实际到账）。',
   '4. 抹零/优惠合计 = 所有订单让给客户的零头之和，是实际收入与报价之间的差额，仅作参考，已从应收中扣除。',
   '5. 净利润 = 总收入 −（总采购成本 + 总发货运费）；月均 = 累计值 ÷ 有数据的自然月数。',
   '6. 平均每单净赚 = 累计净利润 ÷ 订单总数，用来判断这个副业单量上是否划算。',
   '7. 如当月出现退款/退货，请在备注注明，避免利润虚高。'
  ].forEach(t=>sRows.push({n:k++, h:19, cells:[{v:t,s:S.cream}]}));

  /* --- Sheet4 订单结算核对（一单一算，用于核对抹零与到账） --- */
  const rRows=[]; let q=1;
  rRows.push({n:q++, h:32, cells:[{v:'🧾 订单结算核对 · 一单一算，看清「应收 / 实收 / 抹零」',s:S.title}]});
  const rHdr=['订单编号','客户','报价（元）','减：定金（元）','减：尾款（元）','减：抹零/优惠（元）','待收尾款（元）','实收合计（元）','是否结清'];
  rRows.push({n:q++, h:30, cells:rHdr.map(h=>({v:h,s:S.hdrB}))});
  let rSum={p:0,d:0,f:0,c:0,w:0};
  const rFirst = q;
  DB.orders.slice().sort((a,b)=>a.date<b.date?-1:1).forEach(o=>{
    const w = owe(o), wShow = Math.max(0,w);
    rSum.p+=num(o.price); rSum.d+=num(o.deposit); rSum.f+=num(o.final);
    rSum.c+=num(o.cut); rSum.w+=wShow;
    const settled = wShow<=EPS;
    rRows.push({n:q++, cells:[
      {v:o.no,s:S.tx},{v:o.customer,s:S.tx},
      {v:num(o.price),t:'n',s:S.exp},{v:num(o.deposit),t:'n',s:S.inc},
      {v:num(o.final),t:'n',s:S.inc},{v:num(o.cut),t:'n',s:S.exp},
      {v:wShow,t:'n',s:S.hlB},
      {v:num(o.deposit)+num(o.final),t:'n',s:S.incB},
      {v:settled?'已结清':'待收 '+wShow.toFixed(2),s:settled?S.hlB:S.hdrG}
    ]});
  });
  const rLast = Math.max(q-1, rFirst);
  rRows.push({n:q++, cells:[
    {v:'合计',s:S.lbl},{v:'',s:S.lbl},
    {v:rSum.p,t:'n',s:S.hlB},{v:rSum.d,t:'n',s:S.hlB},{v:rSum.f,t:'n',s:S.hlB},
    {v:rSum.c,t:'n',s:S.hlB},{v:rSum.w,t:'n',s:S.hlB},
    {v:rSum.d+rSum.f,t:'n',s:S.hlB},{v:'',s:S.lbl}
  ]});
  rRows.push({n:q++, h:22, cells:[{v:'📝 使用说明 · 订单结算核对',s:S.cream}]});
  ['1. 本表用于核对每一单「报价 → 抹零 → 实收 → 待收」是否闭环。',
   '2. 待收尾款 = 报价 − 定金 − 尾款 − 抹零/优惠，结果为 0（或 0.01 以内）即视为已结清。',
   '3. 若某单「是否结清」显示「待收」，说明还有尾款没收到，或客户抹零的金额还没有登记到「抹零/优惠」。',
   '4. 实收合计 = 定金 + 尾款，应与【收支明细】中该订单对应的收入行金额一致。'
  ].forEach(t=>rRows.push({n:q++, h:19, cells:[{v:t,s:S.cream}]}));

  const files = [
    {name:'[Content_Types].xml', data:`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet4.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`},
    {name:'_rels/.rels', data:`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`},
    {name:'xl/workbook.xml', data:`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>
<sheet name="订单台账" sheetId="1" r:id="rId1"/>
<sheet name="收支明细" sheetId="2" r:id="rId2"/>
<sheet name="月度汇总" sheetId="3" r:id="rId3"/>
<sheet name="订单结算核对" sheetId="4" r:id="rId5"/>
</sheets>
</workbook>`},
    {name:'xl/_rels/workbook.xml.rels', data:`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet4.xml"/>
</Relationships>`},
    {name:'xl/styles.xml', data:wb},
    {name:'xl/worksheets/sheet1.xml', data:sheetXml(oRows,[13,17,16,34,20,26,13,13,13,13,13,20,34],[
      {sqref:`L3:L${oLast}`, list:ORDER_STATUS.join(',')}
    ])},
    {name:'xl/worksheets/sheet2.xml', data:sheetXml(cRows,[13,20,22,38,13,13,30],[
      {sqref:`B3:B${cLast}`, list:CASH_TYPES.join(',')}
    ])},
    {name:'xl/worksheets/sheet3.xml', data:sheetXml(sRows,[22,18,17,17,17,17,17,44,20])},
    {name:'xl/worksheets/sheet4.xml', data:sheetXml(rRows,[17,14,13,13,13,15,13,14,16])}
  ];

  try{
    const blob = buildZip(files);
    download(blob, `手作包包记账表_${today()}.xlsx`);
    toast('Excel 已导出 ✓ 可在微信里转发或存档');
  }catch(e){
    console.error(e); toast('导出失败：'+e.message);
  }
}

/* ---------- 最小 ZIP 打包（store 模式，不压缩） ---------- */
function crc32(bytes){
  let t=crc32.t;
  if(!t){ t=crc32.t=new Uint32Array(256);
    for(let i=0;i<256;i++){ let c=i;
      for(let k=0;k<8;k++) c=c&1?0xEDB88320^(c>>>1):c>>>1;
      t[i]=c>>>0; } }
  let crc=0xFFFFFFFF;
  for(let i=0;i<bytes.length;i++) crc=t[(crc^bytes[i])&0xFF]^(crc>>>8);
  return (crc^0xFFFFFFFF)>>>0;
}
function buildZip(files){
  const enc=new TextEncoder();
  const parts=[], central=[];
  let offset=0;
  const dosTime=(()=>{ const d=new Date();
    return ((d.getHours()<<11)|(d.getMinutes()<<5)|(d.getSeconds()/2))&0xFFFF; })();
  const dosDate=(()=>{ const d=new Date();
    return (((d.getFullYear()-1980)<<9)|((d.getMonth()+1)<<5)|d.getDate())&0xFFFF; })();

  files.forEach(f=>{
    const nameB=enc.encode(f.name);
    const dataB=enc.encode(f.data);
    const crc=crc32(dataB);
    const lh=new Uint8Array(30+nameB.length);
    const dv=new DataView(lh.buffer);
    dv.setUint32(0,0x04034b50,true);
    dv.setUint16(4,20,true); dv.setUint16(6,0x0800,true); dv.setUint16(8,0,true);
    dv.setUint16(10,dosTime,true); dv.setUint16(12,dosDate,true);
    dv.setUint32(14,crc,true);
    dv.setUint32(18,dataB.length,true); dv.setUint32(22,dataB.length,true);
    dv.setUint16(26,nameB.length,true); dv.setUint16(28,0,true);
    lh.set(nameB,30);
    parts.push(lh,dataB);

    const ch=new Uint8Array(46+nameB.length);
    const cv=new DataView(ch.buffer);
    cv.setUint32(0,0x02014b50,true);
    cv.setUint16(4,20,true); cv.setUint16(6,20,true);
    cv.setUint16(8,0x0800,true); cv.setUint16(10,0,true);
    cv.setUint16(12,dosTime,true); cv.setUint16(14,dosDate,true);
    cv.setUint32(16,crc,true);
    cv.setUint32(20,dataB.length,true); cv.setUint32(24,dataB.length,true);
    cv.setUint16(28,nameB.length,true);
    cv.setUint32(42,offset,true);
    ch.set(nameB,46);
    central.push(ch);
    offset += lh.length + dataB.length;
  });

  const cdSize=central.reduce((s,c)=>s+c.length,0);
  const eocd=new Uint8Array(22);
  const ev=new DataView(eocd.buffer);
  ev.setUint32(0,0x06054b50,true);
  ev.setUint16(8,files.length,true); ev.setUint16(10,files.length,true);
  ev.setUint32(12,cdSize,true); ev.setUint32(16,offset,true);

  return new Blob([...parts,...central,eocd],
    {type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
}

function download(blob, filename){
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url; a.download=filename;
  document.body.appendChild(a); a.click();
  setTimeout(()=>{ document.body.removeChild(a); URL.revokeObjectURL(url); },900);
}

/* ---------- 事件绑定 ---------- */
document.querySelectorAll('.tab').forEach(t=>{
  t.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
    t.classList.add('on');
    curTab=t.dataset.tab;
    $('panel-'+curTab).classList.add('on');
    syncAddBtn();
  };
});
$('addBtn').onclick = onAdd;
$('exportBtn').onclick = exportExcel;
$('menuBtn').onclick = menuForm;
$('cashKpis').addEventListener('click', toggleCashKpi);
$('orderFilters').addEventListener('click', selectOrderFilter);

/* ---------- 订单搜索 ---------- */
(function initSearch(){
  const inp = $('orderSearch'), clr = $('orderSearchClr');
  if(!inp) return;
  const sync = ()=>{
    orderQuery = inp.value;
    clr.classList.toggle('on', !!inp.value);
    renderOrders();
  };
  inp.addEventListener('input', sync);
  inp.addEventListener('search', sync);   /* 手机键盘「搜索」键 */
  clr.onclick = ()=>{ inp.value=''; orderQuery=''; clr.classList.remove('on'); renderOrders(); inp.focus(); };
})();

// 列表点击 → 编辑
function onListClick(e){
  const row=e.target.closest('.row');
  if(!row) return;
  const id=row.dataset.id, kind=row.dataset.kind;
  if(kind==='order'){ const o=DB.orders.find(x=>x.id===id); if(o) orderForm(o); }
  else if(kind==='cash'){ const x=DB.cash.find(y=>y.id===id); if(x) cashForm(x); }
}
document.addEventListener('click', onListClick);

/* ---------- 启动 ---------- */
async function boot() {
  const unlock = lockControls();
  try {
    await load();
    renderAll(); syncAddBtn();
    if(!DB.orders.length && !DB.cash.length){
      $('orderList').innerHTML = `<div class="empty"><span class="big">📦</span>还没有订单<br>点下方「+ 记一笔订单」开始记录<br><span style="font-size:11.5px">数据会自动保存在本机</span></div>`;
    }
    unlock();
  } catch(error) { toast(error.message, 6000); }
}
boot();

/* ---------- PWA：Service Worker + 添加到桌面 ---------- */
if('serviceWorker' in navigator){
  navigator.serviceWorker.register('./sw.js').catch(()=>{});
}
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', e=>{
  e.preventDefault();
  deferredPrompt = e;
  showInstallTip();
});
function showInstallTip(){
  // 只提示一次，且已安装过的不提示
  if(localStorage.getItem('bagledger_install_tip')) return;
  if(window.matchMedia('(display-mode: standalone)').matches) return;
  localStorage.setItem('bagledger_install_tip','1');
  const bar = document.createElement('div');
  bar.style.cssText = 'position:fixed;left:12px;right:12px;bottom:calc(74px + var(--safe-b));z-index:70;'+
    'background:#fff;border:1px solid var(--bd);border-radius:13px;padding:12px 14px;'+
    'box-shadow:0 6px 22px rgba(120,160,140,.22);font-size:13px;line-height:1.55';
  bar.innerHTML = '<b>📲 添加到手机桌面</b><br>'+
    '<span style="color:var(--muted)">像 App 一样点开即用，不怕找不到链接。</span><br>'+
    '<span style="color:var(--muted);font-size:12px">安卓：右上角菜单 →「添加到主屏幕」　iOS Safari：分享 →「添加到主屏幕」</span>'+
    '<span id="ipClose" style="position:absolute;right:10px;top:8px;color:var(--muted);font-size:17px;cursor:pointer">×</span>';
  document.body.appendChild(bar);
  bar.querySelector('#ipClose').onclick = ()=> bar.remove();
  setTimeout(()=>{ if(bar.parentNode) bar.remove(); }, 15000);
}


return () => {
  document.removeEventListener('click', onListClick);
  $('cashKpis').removeEventListener('click', toggleCashKpi);
  $('orderFilters').removeEventListener('click', selectOrderFilter);
  clearTimeout(toast._t);
};
}
