"use strict";

/** ========= 配置：你的 Notion Worker 根地址（后端已配置 DB） ========= */
const NOTION_ENDPOINT = "https://notion2json.kenway27a.workers.dev/";

/** ========= 基础工具 ========= */
const STORE_KEY = "wordcards.v1";
const INTERVALS = { 1:1, 2:2, 3:4, 4:7, 5:15 }; // 天
const clampBox = b => Math.max(1, Math.min(5, b));
const todayDateOnly = () => { const d = new Date(); d.setHours(0,0,0,0); return d; };
const addDays = (date, days) => { const d = new Date(date); d.setDate(d.getDate() + days); d.setHours(0,0,0,0); return d; };
const fmtDate = (d) => new Date(d).toISOString().slice(0,10);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s||"").replace(/</g,"&lt;").replace(/>/g,"&gt;");

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
function loadAll(){
  try{
    const raw = localStorage.getItem(STORE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  }catch{ return []; }
}
function saveAll(list){ localStorage.setItem(STORE_KEY, JSON.stringify(list)); }

function getDueList(){
  const all = loadAll();
  const todayISO = fmtDate(todayDateOnly());
  return all
    .filter(x => (x.nextDueISO||"") <= todayISO)
    .sort((a,b) => (a.nextDueISO||"").localeCompare(b.nextDueISO));
}
function stats(){
  const all = loadAll();
  const due = getDueList().length;
  const ok = all.reduce((s,x)=>s+(x.success||0),0);
  const bad = all.reduce((s,x)=>s+(x.fail||0),0);
  return { total: all.length, due, ok, bad, recent: all.slice(0,200) };
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

async function autoSyncFromNotion(){
  if(!NOTION_ENDPOINT){
    notionStatus("未配置 NOTION_ENDPOINT。");
    return;
  }
  try{
    notionStatus("正在从 Notion 拉取…");
    const url = `${NOTION_ENDPOINT.replace(/\/$/,"")}/sync`;
    const res = await fetch(url, { method:"GET" });
    if(!res.ok){
      const t = await res.text();
      throw new Error(`Worker 返回错误：${res.status} ${t}`);
    }
    const arr = await res.json();
    if(!Array.isArray(arr)) throw new Error("Worker 返回的不是数组。");

    let all = loadAll(); let created=0, updated=0;
    for(const it of arr){
      if(!it || !it.word) continue;
      let idx = all.findIndex(r => r.notionId === it.notionId);
      if (idx < 0) idx = all.findIndex(r => !r.notionId && r.word === it.word);

    const mappedMeta = {
        pron:  nlSplit(it.pron),
        senses:nlSplit(it.senses),
        ety:   it.ety || "",
        same:  nlSplit(it.same),
        coll:  nlSplit(it.coll),
        conf:  nlSplit(it.conf),
        beans: nlSplit(it.beans)
      };

      if (idx >= 0){
        const cur = all[idx];
        all[idx] = {
          ...cur,
          word: it.word || cur.word,
          meta: { ...(cur.meta||{}), ...mappedMeta },
          notionId: it.notionId,
          notionEdited: it.edited
        };
        updated++;
      }else{
        const now = new Date();
        all.unshift({
          id: (crypto.randomUUID && crypto.randomUUID()) || (String(Date.now()) + Math.random()),
          word: it.word,
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
  }catch(err){
    console.error(err);
    notionStatus("同步失败：" + err.message);
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
let session = { list: [], idx: 0, current: null, showingBack:false };

function startImmersive(){
  const due = getDueList();
  let list = due.length ? due : loadAll().slice(0,20);
  if (list.length === 0){
    alert("还没有可复习的词。请确认 Notion 已同步成功。");
    return;
  }
  session = { list, idx:0, current:list[0], showingBack:false };
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

  wrap.innerHTML = `
    <div class="card ${session.showingBack ? "state-back sheet-open" : "state-front"}" id="imCard">

      <!-- 正面：报头 + 大标题 + 例句 + 版次章（保持原样，打开后上浮收缩） -->
      <div class="panel front-panel">
        <article class="paper">
          <div class="masthead">
            <div class="mast-left">Wordcards Gazette</div>
            <div class="mast-right">
              <span>${today.toLocaleDateString()}</span>
              <span>Vol. ${vol}</span>
            </div>
          </div>
          <h1 class="headline sc ink">${esc(item.word)}</h1>
          <div class="subhead">${esc(eg)}</div>
          <div class="seals">
            <span class="seal">BOX ${vol}</span>
            <span class="seal">DUE ${due}</span>
          </div>
          <div class="footer-rule meta-line" style="margin-top:12px;">
            <span>Press: Local • Print No.${String(item.id).slice(-6)}</span>
          </div>
        </article>
      </div>

      <!-- 背面：下拉占满纵向，主体滚动 -->
      <div class="panel back-panel">
        <article class="paper">
          <div class="masthead" style="margin-bottom:6px;">
            <div class="mast-left">Lexicography & Natural History</div>
            <div class="mast-right"><span>Filed: ${today.toLocaleDateString()}</span></div>
          </div>
          <div class="paper-body" id="paperBody">
            ${renderBackWidgetsAsArticles(item)}
          </div>
        </article>
      </div>

    </div>
  `;

  // 容器切换对齐方式（让卡片上浮到顶部）
  const cw = document.querySelector(".im-cardwrap");
  if (cw){
    cw.classList.toggle("sheet-open", session.showingBack);
  }

  $("imCard").onclick = ()=> $("imFlip").click();
}

function renderBackWidgetsAsArticles(rec){
  const m = rec.meta || {};
  const blocks = DEFAULT_WIDGETS.map(w => {
    const val = m[w.key];
    const label = esc(w.label);

    if (w.type === "text"){
      const txt = (val && String(val).trim()) ? esc(val) : "—";
      return `
        <section class="article">
          <div class="label">${label}</div>
          <div class="text">${txt.replace(/\n/g,"<br>")}</div>
        </section>
      `;
    }

    if (w.type === "tags"){
      const arr = Array.isArray(val)? val : nlSplit(val);
      const content = arr.length
        ? arr.map(t=>`<span class="pill">${esc(t)}</span>`).join("")
        : "—";
      const extra = (w.key === "conf") ? " warning" : "";
      return `
        <section class="article${extra}">
          <div class="label">${label}</div>
          <div class="tags">${content}</div>
        </section>
      `;
    }

    if (w.type === "list"){
      const arr = Array.isArray(val)? val : nlSplit(val);
      const content = arr.length
        ? arr.map(t=>`<span class="capsule">${esc(t)}</span>`).join("")
        : "—";
      return `
        <section class="article">
          <div class="label">${label}</div>
          <div class="text">${content}</div>
        </section>
      `;
    }

    if (w.type === "senses-ol"){
      const arr = Array.isArray(val)? val : nlSplit(val);
      const content = arr.length
        ? `<ol class="news-ol">${arr.map(s=>`<li>${esc(s)}</li>`).join("")}</ol>`
        : "—";
      return `
        <section class="article">
          <div class="label">${label}</div>
          <div class="text">${content}</div>
        </section>
      `;
    }

    return "";
  }).join("");

  return blocks;
}

/** ========= 进度/排期 ========= */
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
  session.showingBack = false;
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
  // 退出时清理 sheet-open
  const cw = document.querySelector(".im-cardwrap");
  if (cw){ cw.classList.remove("sheet-open"); }
  refreshStats();
}

/** ========= 事件绑定 ========= */
window.addEventListener("DOMContentLoaded", () => {
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
  $("imFlip").onclick = ()=>{
    const card = $("imCard");
    if(!card) return;
  
    const container = document.querySelector(".im-cardwrap");
    const isBackNow = !!card.classList.contains("state-back");
  
    // —— 打开（进入下拉背面）——
    if(!isBackNow){
      session.showingBack = true;
      card.classList.add("state-back","sheet-open");
      card.classList.remove("state-front","closing");
      if (container) container.classList.add("sheet-open");
      const body = card.querySelector(".back-panel .paper-body");
      if (body){ body.scrollTop = 0; }
      return;
    }
  
    // —— 关闭（先折叠背面，再切换类，避免重影）——
    session.showingBack = false;
    const body = card.querySelector(".back-panel .paper-body");
    if(!body){
      // 兜底：没有找到正文容器就直接关
      card.classList.remove("state-back","sheet-open","closing");
      card.classList.add("state-front");
      if (container) container.classList.remove("sheet-open");
      return;
    }
  
    // 1) 进入 closing 状态，准备做高度动画
    card.classList.add("closing");
    // 先把 max-height 设为当前实际高度（像素），保证从“实际高度 → 0”的动画流畅
    body.style.maxHeight = body.scrollHeight + "px";
    // 触发一次回流让上面数值生效
    void body.offsetHeight;
    // 再把 max-height 设为 0，启动收合动画（CSS 中会配合 opacity 轻淡出）
    body.style.maxHeight = "0px";
  
    // 2) 收合完再切换类，彻底回到正面
    const onEnd = (e)=>{
      if(e.propertyName !== "max-height") return;
      body.removeEventListener("transitionend", onEnd);
  
      // 清理内联样式与状态
      body.style.maxHeight = "";
      card.classList.remove("closing","sheet-open","state-back");
      card.classList.add("state-front");
      if (container) container.classList.remove("sheet-open");
    };
    body.addEventListener("transitionend", onEnd);
  };
  
  $("imGood").onclick = ()=> gradeIm(true);
  $("imBad").onclick = ()=> gradeIm(false);
  window.addEventListener("keydown",(e)=>{
    const im = $("immersive");
    const activeTag = (document.activeElement && document.activeElement.tagName) || "";
    if (["INPUT","TEXTAREA"].includes(activeTag)) return;
    if (im && !im.hidden){
      if (e.code==="Space"){ e.preventDefault(); $("imFlip").click(); }
      if (e.key==="j" || e.key==="J"){ e.preventDefault(); $("imBad").click(); }
      if (e.key==="k" || e.key==="K"){ e.preventDefault(); $("imGood").click(); }
      if (e.key==="Escape"){ e.preventDefault(); $("imExit").click(); }
    }
  });

  // 初始渲染
  refreshStats();
});