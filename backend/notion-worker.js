// notion-worker.js
export default {
    async fetch(request, env, ctx) {
      const url = new URL(request.url);
      if (request.method === "OPTIONS") return cors(null); // 预检
  
      const db = url.searchParams.get("db");
      if (!db) return cors(new Response(JSON.stringify({error:"missing db"}), {status:400}));
  
      // 支持分页抓取整个数据库
      let hasMore = true, cursor = null, items = [];
      while (hasMore) {
        const body = { page_size: 100 };
        if (cursor) body.start_cursor = cursor;
  
        const r = await fetch(`https://api.notion.com/v1/databases/${db}/query`, {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${env.NOTION_TOKEN}`,
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
          },
          body: JSON.stringify(body)
        });
        if (!r.ok) return cors(new Response(await r.text(), {status:r.status}));
  
        const j = await r.json();
        // 映射字段：按你数据库的属性名（见下方 NOTION_FIELDS）
        for (const p of j.results) {
          const props = p.properties || {};
          const title = t => (t?.title||[]).map(x=>x.plain_text).join("");
          const rich  = r => (r?.rich_text||[]).map(x=>x.plain_text).join("\n").trim();
          const multi = m => (m?.multi_select||[]).map(x=>x.name);
  
          items.push({
            notionId: p.id,
            word: title(props.Word),     // 标题列
            cn:   rich(props.CN),        // 中文释义（rich_text）
            memo: rich(props.Memo),      // 自由笔记（rich_text）
            syn:  multi(props.Syn),      // 同义词（multi_select）
            col:  multi(props.Coll),     // 搭配（multi_select）
            ex:   rich(props.Ex),        // 例句（rich_text，多行）
            edited: p.last_edited_time
          });
        }
        hasMore = j.has_more;
        cursor = j.next_cursor;
      }
      return cors(json(items));
    }
  };
  
  function json(obj){ return new Response(JSON.stringify(obj), {headers:{"Content-Type":"application/json"}}); }
  function cors(res){
    const h = {
      "Access-Control-Allow-Origin": "*",             // 需要可改为你的域名
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    };
    if (!res) return new Response(null, {headers:h});
    Object.entries(h).forEach(([k,v])=>res.headers.set(k,v));
    return res;
  }
  