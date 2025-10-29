"use strict";

/** ========= Notion sync configuration ========= */
const NOTION_ENDPOINT = "https://notion2json.kenway27a.workers.dev/";
const NOTION_DB_ID = "";
const NOTION_SYNC_TIMEOUT_MS = 12000;
const NOTION_SYNC_MAX_RETRIES = 2;
const NOTION_SYNC_RETRY_BASE_DELAY_MS = 600;
const NOTION_AUTO_RETRY_DELAY_MS = 60000;

/** ========= Storage & scheduling ========= */
const STORE_KEY = "wordcards.v1";
const INTERVALS = { 1: 1, 2: 2, 3: 4, 4: 7, 5: 15 }; // days
let storeCache = null;
let notionRetryTimer = null;
const clampBox = b => Math.max(1, Math.min(5, b));
const todayDateOnly = () => { const d = new Date(); d.setHours(0,0,0,0); return d; };
const addDays = (date, days) => { const d = new Date(date); d.setDate(d.getDate() + days); d.setHours(0,0,0,0); return d; };
const fmtDate = (d) => new Date(d).toISOString().slice(0,10);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s||"").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

/** ========= 背面只读字段（与你的 Notion 列对应） ========= */
const DEFAULT_WIDGETS = [
  { type: "list", key: "pron",   label: "Pronunciations" },
  { type: "senses-ol", key: "senses", label: "Senses" },   // 有序列表
  { type: "text", key: "ety",    label: "Etymologies" },
  { type: "tags", key: "same",   label: "Same Origin" },
  { type: "tags", key: "coll",   label: "Collocations" },
  { type: "tags", key: "conf",   label: "Confusions" },
  { type: "tags", key: "beans",  label: "Beans" }
];

/** ========= 本地数据（仅存排期与统计） ========= */
function loadAll(force=false){
  if (!force && Array.isArray(storeCache)) return storeCache;
  try{
    const raw = localStorage.getItem(STORE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    storeCache = Array.isArray(arr) ? arr : [];
  }catch{
    storeCache = [];
  }
  return storeCache;
}
function saveAll(list){
  storeCache = Array.isArray(list) ? list : [];
  localStorage.setItem(STORE_KEY, JSON.stringify(storeCache));
}

function getDueList(){
  const all = loadAll();
  const todayISO = fmtDate(todayDateOnly());
  return all
    .filter(x => (x.nextDueISO||"") <= todayISO)
    .sort((a,b) => (a.nextDueISO||"").localeCompare(b.nextDueISO));
}
function stats(){
  const all = loadAll();
  const todayISO = fmtDate(todayDateOnly());
  const due = all.filter(x => (x.nextDueISO||"") <= todayISO).length;
  const ok = all.reduce((s,x)=>s+(x.success||0),0);
  const bad = all.reduce((s,x)=>s+(x.fail||0),0);
  const recent = all
    .slice()
    .sort((a,b) => (b.createdAtISO||"").localeCompare(a.createdAtISO||""))
    .slice(0,200);
  return { total: all.length, due, ok, bad, recent };
}

/** ========= 例句生成（本地） ========= */
function guessPOS(w){
  const s = w.trim();
  if(/^to\s+/i.test(s)) return "verb";
  const x = s.toLowerCase();
  if(x.endsWith("ly")) return "adverb";
  if(/(ous|ive|ful|less|able|al|ic|ish|ern|ary)$/.test(x)) return "adj";
  if(/(tion|sion|ment|ness|ity|ship|tude|ance|ence|ism|ist)$/.test(x)) return "noun";
  if(/(ing|ed)$/.test(x)) return "verb";
  return "unknown";
}
function genExampleLocal(word){
  const raw = word.trim();
  const base = raw.replace(/^to\s+/i,"");
  const pos = guessPOS(raw);
  const you = ["I","We","They","You"][Math.floor(Math.random()*4)];
  const pick = a => a[Math.floor(Math.random()*a.length)];
  switch(pos){
    case "verb":
      return `${you} ${base} ${pick(["it","the plan","the task","the idea","the project"])} ${pick(["carefully","quickly","every day","when needed","whenever possible"])}.`;
    case "noun":
      return `${pick(["The","A","This","That"])} ${base} ${pick(["on the desk","in the report","for our trip","at work","in daily life"])} is very important.`;
    case "adj":
      return `It is a very ${base} ${pick(["idea","plan","approach","choice","solution"])}.`;
    case "adverb":
      return `${you} ${pick(["adapt","work","learn","respond","collaborate"])} ${base} under pressure.`;
    default:
      return `I came across the word “${base}” yesterday and tried to use it in a sentence.`;
  }
}

/** ========= Notion 自动同步 ========= */
function notionStatus(msg){ const el = $("notionStatus"); if(el) el.textContent = msg; }
function nlSplit(v){ if (Array.isArray(v)) return v; return String(v||"").split("\n").map(s=>s.trim()).filter(Boolean); }

function scheduleNotionRetry(delay = NOTION_AUTO_RETRY_DELAY_MS){
  if (notionRetryTimer) clearTimeout(notionRetryTimer);
  notionRetryTimer = setTimeout(() => {
    notionRetryTimer = null;
    autoSyncFromNotion();
  }, delay);
}

function clearNotionRetry(){
  if (notionRetryTimer){
    clearTimeout(notionRetryTimer);
    notionRetryTimer = null;
  }
}

async function fetchNotionRecords(url, onRetry){
  let attempt = 0;
  let lastError = null;
  const totalAttempts = NOTION_SYNC_MAX_RETRIES + 1;
  while (attempt < totalAttempts){
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), NOTION_SYNC_TIMEOUT_MS) : null;
    try{
      const res = await fetch(url.toString(), { method:"GET", signal: controller?.signal });
      if (timer) clearTimeout(timer);
      if(!res.ok){
        const text = await res.text();
        throw new Error(`Worker 返回错误：${res.status} ${text}`);
      }
      return await res.json();
    }catch(err){
      if (timer) clearTimeout(timer);
      if (err && err.name === "AbortError") {
        err = new Error("请求超时");
      }
      lastError = err;
      attempt++;
      if (attempt >= totalAttempts) throw lastError;
      if (typeof onRetry === "function"){
        onRetry({
          attempt,
          nextAttempt: attempt + 1,
          maxAttempts: totalAttempts,
          error: err
        });
      }
      const delay = NOTION_SYNC_RETRY_BASE_DELAY_MS * Math.pow(2, attempt - 1);
      await sleep(delay);
    }
  }
  throw lastError;
}

async function autoSyncFromNotion(){
  if(!NOTION_ENDPOINT){
    notionStatus("未配置 NOTION_ENDPOINT。");
    return;
  }
  if (typeof navigator !== "undefined" && navigator.onLine === false){
    notionStatus(`当前处于离线状态，将在 ${Math.round(NOTION_AUTO_RETRY_DELAY_MS/1000)} 秒后自动重试。`);
    scheduleNotionRetry();
    return;
  }
  try{
    notionStatus("正在从 Notion 拉取…");
    const base = NOTION_ENDPOINT.replace(/\/$/,"");
    const url = new URL(`${base}/sync`);
    if (NOTION_DB_ID) url.searchParams.set("db", NOTION_DB_ID);
    const arr = await fetchNotionRecords(url, ({ nextAttempt, maxAttempts, error }) => {
      notionStatus(`同步失败：${error.message}，准备第 ${Math.min(nextAttempt, maxAttempts)} 次重试…`);
    });
    if(!Array.isArray(arr)) throw new Error("Worker 返回的不是数组。");

    let all = loadAll(); let created=0, updated=0;
    for(const it of arr){
      if(!it || !it.word) continue;
      const canonicalWord = String(it.word).trim();
      if (!canonicalWord) continue;
      const normalizedWord = canonicalWord.toLowerCase();
      let idx = all.findIndex(r => r.notionId === it.notionId);
      if (idx < 0) {
        idx = all.findIndex(r => !r.notionId && String(r.word||"").trim().toLowerCase() === normalizedWord);
      }

      const mappedMeta = {
        pron: nlSplit(it.pron),
        senses: nlSplit(it.senses),
        ety: it.ety || "",
        same: nlSplit(it.same),
        coll: nlSplit(it.coll),
        conf: nlSplit(it.conf),
        beans: nlSplit(it.beans)
      };

      if (idx >= 0){
        const cur = all[idx];
        all[idx] = {
          ...cur,
          word: canonicalWord || cur.word,
          meta: { ...(cur.meta||{}), ...mappedMeta },
          notionId: it.notionId,
          notionEdited: it.edited
        };
        updated++;
      }else{
        const now = new Date();
        all.unshift({
          id: (crypto.randomUUID && crypto.randomUUID()) || (String(Date.now()) + Math.random()),
          word: canonicalWord,
          note: "",
          box: 1,
          nextDueISO: fmtDate(todayDateOnly()),
          createdAtISO: now.toISOString(),
          success: 0, fail: 0,
          meta: mappedMeta,
          notionId: it.notionId,
          notionEdited: it.edited
        });
        created++;
      }
    }
    saveAll(all);
    refreshStats();
    const ts = new Date().toLocaleString();
    notionStatus(`同步完成：新增 ${created}，更新 ${updated}（${ts}）`);
    clearNotionRetry();
  }catch(err){
    console.error(err);
    notionStatus(`同步失败：${err.message}（将在 ${Math.round(NOTION_AUTO_RETRY_DELAY_MS/1000)} 秒后自动重试）`);
    scheduleNotionRetry();
  }
}

/** ========= 右侧词库（只读，点击跳转 Notion 原条目） ========= */
function refreshStats(){
  const s = stats();
  $("totalV").textContent = s.total;
  $("dueV").textContent = s.due;
  $("okV").textContent = s.ok;
  $("badV").textContent = s.bad;
  $("duePill").textContent = `今日到期：${s.due}`;

  const list = $("recentList");
  list.innerHTML = "";
  s.recent.forEach(r=>{
    const div = document.createElement("div");
    div.className = "item";
    const notionUrl = r.notionId ? `https://www.notion.so/${String(r.notionId).replace(/-/g,"")}` : null;
    div.innerHTML = `
      <div>
        <div class="w">${esc(r.word)}</div>
        <div class="n">${r.meta?.senses?.length ? esc(r.meta.senses[0]) : "<i>（无释义）</i>"}</div>
      </div>
      <div class="meta">
        <span>盒${r.box||1}</span>
        <span class="tag">${esc(r.nextDueISO||"-")}</span>
      </div>
    `;
    if (notionUrl){
      div.style.cursor = "pointer";
      div.title = "在 Notion 中打开";
      div.onclick = ()=> window.open(notionUrl, "_blank");
    }
    list.appendChild(div);
  });
}

/** ========= 报纸版沉浸模式（正面上浮 + 背面下拉充满） ========= */
let session = { list: [], idx: 0, current: null, detailsOpen:false };

function startImmersive(){
  const due = getDueList();
  let list = due.length ? due : loadAll().slice(0,20);
  if (list.length === 0){
    alert("还没有可复习的词。请确认 Notion 已同步成功。");
    return;
  }
  session = { list, idx:0, current:list[0], detailsOpen:false };
  $("immersive").hidden = false;
  renderImmersiveCard();
  updateImProgress();
}

function renderImmersiveCard(){
  const item = session.current;
  if(!item) return;
  if (!item.meta) item.meta = { pron:[], senses:[], ety:"", same:[], coll:[], conf:[], beans:[] };

  const eg = genExampleLocal(item.word);
  const wrap = $("imWrap");

  const today = new Date();
  const vol = (item.box||1);
  const due = esc(item.nextDueISO || "-");
  const todayStamp = esc(today.toLocaleDateString());
  const dispatchNo = esc(String(item.id || "").slice(-4).toUpperCase() || "XXXX");
  const serialNo = esc(String(item.id || "").slice(-6) || "000000");

  wrap.innerHTML = `
    <div class="card" id="imCard">
      <article class="paper telegram-sheet card-front">
        <header class="telegram-masthead">
          <div class="telegram-office">UNITED CABLE SERVICE</div>
          <div class="telegram-meta">
            <span>${todayStamp}</span>
            <span>DISPATCH ${dispatchNo}</span>
          </div>
        </header>
        <div class="double-rule double-rule-top"></div>
        <h1 class="headline telegram-head">${esc(item.word).toUpperCase()}</h1>
        <div class="double-rule double-rule-bottom"></div>
        <p class="telegram-lede">${esc(eg)}</p>
        <footer class="telegram-footer">
          <span class="footer-tag">BOX ${vol}</span>
          <span class="footer-tag">DUE ${due}</span>
          <span class="footer-tag">FILE ${serialNo}</span>
        </footer>
        <div class="postal-stamp" aria-hidden="true">
          <span class="stamp-top">POSTE</span>
          <span class="stamp-mid">${due}</span>
          <span class="stamp-btm">${today.getFullYear()}</span>
        </div>
        <aside class="margin-note note-left" aria-hidden="true">REVIEW ${due}</aside>
        <aside class="margin-note note-right" aria-hidden="true">BOX ${vol}</aside>
      </article>

      <article class="card-details paper broadsheet" id="cardDetails">
        <header class="broadsheet-masthead">
          <div class="broadsheet-title">LEXICAL BULLETIN · SECTION ${vol}</div>
          <div class="broadsheet-meta">Filed ${todayStamp}</div>
        </header>
        <div class="broadsheet-body" id="detailsBody">
          ${renderBackWidgetsAsArticles(item)}
        </div>
        <footer class="broadsheet-footer">
          <span>Compiled for dispatch ${dispatchNo}</span>
          <span>${serialNo}</span>
        </footer>
        <div class="marginalia marginalia-left" aria-hidden="true">CLASSIFIED</div>
      <div class="marginalia marginalia-right" aria-hidden="true">ARCHIVE</div>
    </article>
  </div>
  `;

  const cardEl = $("imCard");
  if (cardEl){
    const details = $("cardDetails");
    if (details){
      if (session.detailsOpen){
        details.classList.add("is-open");
        details.style.height = details.scrollHeight + "px";
        requestAnimationFrame(()=>{ details.style.height = "auto"; });
      }else{
        details.classList.remove("is-open");
        details.style.height = "0px";
      }
    }
    cardEl.onclick = (e)=>{
      // 避免和按钮冲突
      if (e.target.closest(".card-details")) return toggleDetails();
      if (e.target.closest(".im-controls")) return;
      toggleDetails();
    };
  }
}

function renderBackWidgetsAsArticles(rec){
  const m = rec.meta || {};
  let sectionIndex = 0;
  const sections = [];

  DEFAULT_WIDGETS.forEach(w => {
    const val = m[w.key];
    const label = esc(w.label);
    let content = "";
    let hasContent = false;

    if (w.type === "text"){
      const txt = (val && String(val).trim()) ? esc(val).replace(/\n/g,"<br>") : "";
      if (txt){
        hasContent = true;
        content = `<p class="broadsheet-text">${txt}</p>`;
      }
    }else if (w.type === "tags"){
      const arr = Array.isArray(val)? val : nlSplit(val);
      if (arr.length){
        hasContent = true;
        content = `<div class="tag-ribbon">${arr.map(t=>`<span class="franked-tag">${esc(t)}</span>`).join("")}</div>`;
      }
      if (!hasContent && w.key === "conf"){
        // show empty caution area for conflicts to highlight absence
        content = `<div class="tag-ribbon muted">无记录</div>`;
        hasContent = true;
      }
    }else if (w.type === "list"){
      const arr = Array.isArray(val)? val : nlSplit(val);
      if (arr.length){
        hasContent = true;
        content = `<ul class="ticker-list">${arr.map(t=>`<li>${esc(t)}</li>`).join("")}</ul>`;
      }
    }else if (w.type === "senses-ol"){
      const arr = Array.isArray(val)? val : nlSplit(val);
      if (arr.length){
        hasContent = true;
        const [lead, ...rest] = arr;
        const quote = `<blockquote class="pull-quote"><span class="quote-mark">❝</span>${esc(lead)}<span class="quote-mark">❞</span></blockquote>`;
        const list = rest.length
          ? `<ol class="bulletin-ol">${rest.map((s,i)=>`<li><span class="ol-index">${String(i+1).padStart(2,"0")}</span>${esc(s)}</li>`).join("")}</ol>`
          : "";
        content = `${quote}${list}`;
      }
    }

    if (!hasContent) return;
    sectionIndex++;
    const sectionNo = String(sectionIndex).padStart(2,"0");
    const cautionClass = w.key === "conf" ? " caution" : "";
    sections.push(`
      <section class="bulletin-section${cautionClass}" data-key="${esc(w.key)}">
        <header class="section-head">
          <span class="section-number">${sectionNo}</span>
          <span class="section-label">${label}</span>
          <span class="section-rule" aria-hidden="true"></span>
        </header>
        <div class="section-body">${content}</div>
      </section>
    `);
  });

  return sections.join("");
}

function toggleDetails(force){
  const next = typeof force === "boolean" ? force : !session.detailsOpen;
  const card = $("imCard");
  if (!card) return;
  const details = card.querySelector(".card-details");
  if (!details) return;

  if (next === session.detailsOpen){
    return;
  }

  if (next){
    details.style.transition = "none";
    details.style.height = "auto";
    const target = details.scrollHeight;
    details.style.height = "0px";
    // 强制回流，确保起点为 0
    details.offsetHeight;
    details.style.transition = "";
    details.classList.add("is-open");
    details.style.height = target + "px";
    session.detailsOpen = true;

    const onEnd = (e)=>{
      if(e.propertyName !== "height") return;
      details.removeEventListener("transitionend", onEnd);
      if (session.detailsOpen){
        details.style.height = "auto";
      }
    };
    details.addEventListener("transitionend", onEnd);
  }else{
    const current = details.scrollHeight;
    details.style.height = current + "px";
    details.offsetHeight;
    details.style.height = "0px";
    session.detailsOpen = false;
    details.classList.remove("is-open");

    const onEnd = (e)=>{
      if(e.propertyName !== "height") return;
      details.removeEventListener("transitionend", onEnd);
      if (!session.detailsOpen){
        details.style.height = "0px";
      }
    };
    details.addEventListener("transitionend", onEnd);
  }
}

/** ========= 原有进度/排期逻辑 ========= */
function updateImProgress(){
  const p = Math.round((session.idx) / session.list.length * 100);
  $("imBar").style.width = Math.min(100, p) + "%";
}

function nextImItem(){
  session.idx++;
  if(session.idx >= session.list.length){
    $("imBar").style.width = "100%";
    setTimeout(()=> exitImmersive(), 300);
    return;
  }
  session.current = session.list[session.idx];
  session.detailsOpen = false;
  renderImmersiveCard();
  updateImProgress();
}
function scheduleAfterGrade(rec, isGood){
  const nowBox = rec.box || 1;
  if(isGood){
    const newBox = clampBox(nowBox + 1);
    const days = INTERVALS[newBox] || 1;
    const next = fmtDate(addDays(todayDateOnly(), days));
    return { box: newBox, nextDueISO: next, success: (rec.success||0)+1 };
  }else{
    const next = fmtDate(addDays(todayDateOnly(), 1));
    return { box: 1, nextDueISO: next, fail: (rec.fail||0)+1 };
  }
}
function gradeIm(isGood){
  const rec = session.current;
  const patch = scheduleAfterGrade(rec, isGood);
  const all = loadAll();
  const idx = all.findIndex(x=>x.id===rec.id);
  if(idx>=0){ all[idx] = {...all[idx], ...patch}; saveAll(all); }
  nextImItem();
}
function exitImmersive(){
  $("immersive").hidden = true;
  session.detailsOpen = false;
  refreshStats();
}

/** ========= 事件绑定 ========= */
window.addEventListener("DOMContentLoaded", () => {
  const mastDate = $("mastDate");
  if (mastDate){
    const formatter = new Intl.DateTimeFormat("zh-Hans", { year: "numeric", month: "short", day: "numeric" });
    mastDate.textContent = formatter.format(new Date());
  }
  // 自动从 Notion 拉取
  autoSyncFromNotion();

  // 复习
  $("immStartBtn").onclick = startImmersive;

  // 导入/导出（备份本地排期）
  $("exportBtn").onclick = ()=>{
    const data = JSON.stringify(loadAll(), null, 2);
    const blob = new Blob([data], {type:"application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "wordcards.json"; a.click();
    URL.revokeObjectURL(url);
  };
  $("importFile").onchange = (e)=>{
    const file = e.target.files[0];
    if(!file) return;
    const reader = new FileReader();
    reader.onload = ()=>{
      try{
        const arr = JSON.parse(reader.result);
        if(Array.isArray(arr)){
          saveAll(arr);
          refreshStats();
          notionStatus("已从 JSON 导入本地排期数据。");
        }else{
          alert("导入失败：JSON 格式不正确。");
        }
      }catch(err){
        alert("导入失败："+err.message);
      }
    };
    reader.readAsText(file, "utf-8");
  };

  // 沉浸快捷键
  $("imExit").onclick = exitImmersive;
  const handleToggle = ()=> toggleDetails();
  $("imFlip").onclick = handleToggle;
  
  $("imGood").onclick = ()=> gradeIm(true);
  $("imBad").onclick = ()=> gradeIm(false);
  window.addEventListener("keydown",(e)=>{
    const im = $("immersive");
    const activeTag = (document.activeElement && document.activeElement.tagName) || "";
    if (["INPUT","TEXTAREA"].includes(activeTag)) return;
    if (im && !im.hidden){
      if (e.code==="Space"){ e.preventDefault(); handleToggle(); }
      if (e.key==="j" || e.key==="J"){ e.preventDefault(); $("imBad").click(); }
      if (e.key==="k" || e.key==="K"){ e.preventDefault(); $("imGood").click(); }
      if (e.key==="Escape"){ e.preventDefault(); $("imExit").click(); }
    }
  });

  // 初始渲染
  refreshStats();
});
