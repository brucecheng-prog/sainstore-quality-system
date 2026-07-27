# -*- coding: utf-8 -*-
"""
photo_api.py
============
在线 QC 检验报告 —— 照片上传后端（独立轻量 HTTP 服务，零第三方依赖）。

设计要点（与《在线报告完整蓝图 V1》一致）：
- NAS 为唯一真源：上传时同步写 NAS + 本地缓存（NAS 不可达时本地兜底）。
- 索引落 report_photos 表（online_report_db），组件只持有 photo_id，不存 base64。
- 删除 = 软删除（标记 deleted + 审计 + 删实体文件），满足「图片删除留痕」。
- 鉴权：共享令牌 PHOTO_API_TOKEN（内网 LAN 工具，够用；生产建议配隧道 HTTPS）。

路由：
  POST   /api/photo/upload        multipart: file + report_key/category/defect_index/seq/caption/created_by/token
  GET    /api/photo/<id>          流式返回图片（本地优先，回退 NAS）
  DELETE /api/photo/<id>          ?token=&by=   软删除
  GET    /api/photo/list?report_key=  列出该 key 下未删照片

启动：
  python photo_api.py            # 监听 PHOTO_API_PORT（默认 8800）
"""
import os
import sys
import io
import json
import hashlib
import mimetypes
import sqlite3
import re
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import online_report_db as odb
from nas_client import upload_file, download_file, check_connection

PORT = int(os.environ.get("PHOTO_API_PORT", "8800"))
TOKEN = os.environ.get("PHOTO_API_TOKEN", "")          # 空 = 开发模式不校验
API_BASE = os.environ.get("PHOTO_API_BASE", f"http://localhost:{PORT}")
CACHE_DIR = os.path.join(_HERE, "data", "photo_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
NAS_PHOTO_ROOT = "/QA/验货照片"


def _request_base(req_handler):
    proto = req_handler.headers.get("X-Forwarded-Proto", "") or "http"
    host = (req_handler.headers.get("X-Forwarded-Host", "")
            or req_handler.headers.get("Host", "")
            or f"localhost:{PORT}")
    return f"{proto}://{host}"

# 移动端拍照上传页类别（与组件 GAL 一致；路线 A：捕时打标签，拍照自动归入对应图框）
CAPTURE_CATS = [
    {"id": "placement", "name": "分产品摆放", "en": "Placement"},
    {"id": "docs",      "name": "产品资料",   "en": "Product Docs"},
    {"id": "dimension", "name": "尺寸测量",   "en": "Dimension"},
    {"id": "weight",    "name": "称重",       "en": "Weighing"},
    {"id": "label",     "name": "标签&条码",  "en": "Label & Barcode"},
    {"id": "function",  "name": "功能测试",   "en": "Function"},
    {"id": "safety",    "name": "安规检测",   "en": "Safety"},
    {"id": "drop",      "name": "跌落测试",   "en": "Drop Test"},
    {"id": "other",     "name": "其他检测",   "en": "Other"},
    {"id": "defect",    "name": "缺陷记录",   "en": "Defect"},
]

# NAS 的二级目录对现场人员直接可读，禁止用组件内部英文 id 作为目录名。
CAPTURE_CATEGORY_FOLDERS = {
    "placement": "分产品摆放", "docs": "产品资料", "dimension": "尺寸测量",
    "weight": "称重", "label": "标签与条码", "function": "功能测试",
    "safety": "安规检测", "drop": "跌落测试", "other": "其他检测", "defect": "缺陷记录",
}


def _resolve_report(key, rid, no):
    """按 r<id> / id / report_no 解析报告，返回 meta dict 或 None。"""
    try:
        conn = odb.get_connection()
        row = None
        if rid:
            row = conn.execute(
                "SELECT id, report_no, title, product_name, supplier, status "
                "FROM online_reports WHERE id=?", (rid,)).fetchone()
        elif no:
            row = conn.execute(
                "SELECT id, report_no, title, product_name, supplier, status "
                "FROM online_reports WHERE report_no=?", (no,)).fetchone()
        elif key and key.startswith("r") and key[1:].isdigit():
            row = conn.execute(
                "SELECT id, report_no, title, product_name, supplier, status "
                "FROM online_reports WHERE id=?", (int(key[1:]),)).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row["id"], "report_no": row["report_no"] or "",
            "title": row["title"] or "", "product": row["product_name"] or "",
            "supplier": row["supplier"] or "", "status": row["status"] or "",
        }
    except Exception:
        return None


def _escape_html(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _meta_text(meta):
    parts = []
    if meta["report_no"]:
        parts.append(meta["report_no"])
    if meta["product"]:
        parts.append("产品：" + meta["product"])
    if meta["supplier"]:
        parts.append("供应商：" + meta["supplier"])
    if meta["status"]:
        parts.append("状态：" + meta["status"])
    return " · ".join(parts) if parts else ("报告 #" + str(meta["id"]))


def _build_temp_meta(key):
    suffix = str(key or "").replace("tmp_", "", 1)[:12] or "未保存"
    return {
        "id": None,
        "report_no": "未保存草稿",
        "title": "",
        "product": "",
        "supplier": "",
        "status": "草稿",
        "temp_key": str(key or ""),
        "temp_label": suffix,
    }


def _build_legacy_meta(key, label=""):
    label = str(label or "").strip() or "未命名旧品"
    return {
        "id": None,
        "report_no": "旧品独立拍照",
        "title": label,
        "product": label,
        "supplier": "",
        "status": "不关联在线报告",
        "temp_key": str(key or ""),
        "temp_label": label,
    }


def _is_temp_key(key):
    value = str(key or "").strip()
    return value.startswith("tmp_") and len(value) > 4


_CAPTURE_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<title>验货现场拍照上传</title>
<style>
  :root{--p:#2563eb;--p2:#1d4ed8;--bg:#f1f5f9;--card:#fff;--line:#e2e8f0;--mut:#64748b;}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:#0f172a;}
  header{background:linear-gradient(135deg,var(--p),var(--p2));color:#fff;padding:18px 16px 14px;}
  header .t{font-size:18px;font-weight:700;}
  header .sub{font-size:12.5px;opacity:.92;margin-top:4px;word-break:break-all;}
  main{padding:14px 14px 40px;max-width:680px;margin:0 auto;}
  .field{margin:10px 0;}
  .field label{font-size:13px;color:var(--mut);display:block;margin-bottom:6px;}
  .field input{width:100%;padding:12px 14px;border:1px solid var(--line);border-radius:10px;font-size:15px;background:#fff;}
  .ct{font-size:13px;font-weight:700;color:#334155;margin:18px 0 8px;}
  .cats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;}
  .cat{background:var(--card);border:2px solid var(--line);border-radius:12px;padding:14px 10px;text-align:center;font-size:14px;font-weight:600;color:#334155;cursor:pointer;transition:.15s;}
  .cat .en{display:block;font-size:10.5px;font-weight:400;color:var(--mut);margin-top:3px;font-family:ui-monospace,monospace;}
  .cat.on{border-color:var(--p);background:#eff6ff;color:var(--p2);box-shadow:0 2px 8px rgba(37,99,235,.18);}
  .shoot{display:flex;align-items:center;justify-content:center;gap:10px;margin-top:16px;background:var(--p);color:#fff;font-size:17px;font-weight:700;padding:18px;border-radius:14px;cursor:pointer;box-shadow:0 4px 14px rgba(37,99,235,.35);}
  .shoot:active{transform:scale(.98);}
  .shoot input{display:none;}
  .hint{font-size:12.5px;color:var(--mut);text-align:center;margin-top:10px;min-height:18px;}
  .hint.ok{color:#16a34a;} .hint.err{color:#dc2626;}
  .lt{font-size:13px;font-weight:700;color:#334155;margin:22px 0 8px;}
  .list{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}
  .list .empty{color:var(--mut);font-size:13px;padding:20px;text-align:center;grid-column:1/-1;}
  .pc{position:relative;border-radius:10px;overflow:hidden;background:#000;aspect-ratio:1/1;border:1px solid var(--line);}
  .pc img{width:100%;height:100%;object-fit:cover;display:block;}
  .pc .b{position:absolute;left:0;right:0;bottom:0;background:rgba(15,23,42,.72);color:#fff;font-size:10px;padding:3px 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .pc .x{position:absolute;top:4px;right:4px;background:rgba(220,38,38,.9);color:#fff;border:none;border-radius:50%;width:22px;height:22px;font-size:14px;line-height:1;cursor:pointer;}
</style>
</head>
<body>
<header><div class="t">📷 验货现场拍照上传</div><div class="sub" id="meta">__META__</div><button id="copyLink" type="button" style="margin-top:8px;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.5);color:#fff;border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer;">📋 复制本页链接发给手机</button></header>
<div id="offbar" style="display:none;align-items:center;gap:8px;background:#fef3c7;color:#92400e;font-size:13px;padding:8px 14px;">
  <span id="offIcon">📴</span><span id="offLabel">离线模式</span><span id="qcount" style="font-weight:700"></span>
  <div style="margin-left:auto;display:flex;gap:6px;">
    <button id="retryBtn" type="button" style="background:#2563eb;color:#fff;border:none;border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer;">↻ 重试</button>
    <button id="clearBtn" type="button" style="background:#dc2626;color:#fff;border:none;border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer;">✕ 清空</button>
  </div>
</div>
<main>
  <div id="modeBar" style="display:none;align-items:center;gap:8px;font-size:13px;padding:8px 14px;margin-bottom:10px;border-radius:8px;"></div>
  <div class="field"><label>验货员姓名（留痕）</label><input id="byName" placeholder="如：张三" value="__BY__"></div>
  <div class="ct">① 选择照片类别（决定自动落入报告哪个图框）</div>
  <div class="cats" id="cats"></div>
  <div class="ct">② 拍照 / 选图，自动归入上方类别</div>
  <label class="shoot"><input id="file" type="file" accept="image/*" capture="environment"><span>📸 拍照并上传</span></label>
  <div class="hint" id="hint">请选择类别后拍照</div>
  <div class="lt">已上传（本报告）</div>
  <div class="list" id="list"><div class="empty">加载中…</div></div>
</main>
<script>
const CATS=__CATS__;
const API=location.origin;
const KEY="__KEY__";
const MODE="__MODE__"||"new";
const TOKEN=__TOKEN__;
const PRESET=__PRESET__;
let active=PRESET||(CATS[0]&&CATS[0].id)||"other";
const $=s=>document.querySelector(s);
function withToken(u){return TOKEN?(u+(u.indexOf("?")>=0?"&":"?")+"token="+encodeURIComponent(TOKEN)):u;}
function setActive(id){active=id;document.querySelectorAll(".cat").forEach(c=>c.classList.toggle("on",c.dataset.id===id));}
function renderCats(){const w=$("#cats");w.innerHTML="";CATS.forEach(c=>{const b=document.createElement("div");b.className="cat"+(c.id===active?" on":"");b.dataset.id=c.id;b.innerHTML=c.name+'<span class="en">'+c.en+"</span>";b.onclick=()=>setActive(c.id);w.appendChild(b);});}
function hint(m,cls){const h=$("#hint");h.textContent=m;h.className="hint"+(cls?(" "+cls):"");}
// 模式横幅：new=新品（进报告）；old=旧品（仅NAS归档，缺陷除外）
(function renderModeBar(){const bar=$("#modeBar");if(!bar)return;const isOld=String(MODE).toLowerCase()==="old";bar.style.display="flex";if(isOld){bar.style.background="#fef3c7";bar.style.color="#92400e";bar.innerHTML="📦 <b>旧品模式</b>：照片实时归档 NAS，非缺陷照片不进报告（缺陷照片除外）";}else{bar.style.background="#dcfce7";bar.style.color="#166534";bar.innerHTML="✨ <b>新品模式</b>：照片进报告图框 + 实时归档 NAS";}}());
function compress(file,cb){const max=1600;const img=new Image();const url=URL.createObjectURL(file);img.onload=()=>{let w=img.width,h=img.height;if(w>max||h>max){const r=Math.min(max/w,max/h);w=Math.round(w*r);h=Math.round(h*r);}const c=document.createElement("canvas");c.width=w;c.height=h;c.getContext("2d").drawImage(img,0,0,w,h);c.toBlob(b=>{cb(b);URL.revokeObjectURL(url);},"image/jpeg",0.82);};img.onerror=()=>{cb(file);URL.revokeObjectURL(url);};img.src=url;}

// ===== 离线队列（IndexedDB）：无网时暂存，联网后静默自动补传 =====
const DB_NAME="capture_queue", STORE="photos";
let offlineCount=0, _flushStatus=""; // _flushStatus: ""|syncing|error
function openDB(){return new Promise((res,rej)=>{const r=indexedDB.open(DB_NAME,1);r.onupgradeneeded=e=>{const db=e.target.result;if(!db.objectStoreNames.contains(STORE))db.createObjectStore(STORE,{keyPath:"id",autoIncrement:true});};r.onsuccess=e=>res(e.target.result);r.onerror=e=>rej(e.target.error);});}
function dbAll(){return new Promise(async(res)=>{try{const db=await openDB();const tx=db.transaction(STORE,"readonly");const rq=tx.objectStore(STORE).getAll();rq.onsuccess=()=>res(rq.result||[]);rq.onerror=()=>res([]);}catch(e){res([]);}});}
async function dbDel(id){try{const db=await openDB();await new Promise((res,rej)=>{const tx=db.transaction(STORE,"readwrite");tx.objectStore(STORE).delete(id);tx.oncomplete=res;tx.onerror=()=>rej(tx.error);});}catch(e){}}
async function dbClearAll(){try{const db=await openDB();await new Promise((res,rej)=>{const tx=db.transaction(STORE,"readwrite");tx.objectStore(STORE).clear();tx.oncomplete=res;tx.onerror=()=>rej(tx.error);});}catch(e){}}
// ── 删除指定 IDB 记录 ──
async function dbDelByIds(ids){if(!ids.length)return;try{const db=await openDB();await new Promise((res,rej)=>{const tx=db.transaction(STORE,"readwrite");const os=tx.objectStore(STORE);ids.forEach(id=>os.delete(id));tx.oncomplete=res;tx.onerror=()=>rej(tx.error);});}catch(e){}}
// 横幅状态：区分 离线 / 同步中 / 有错误待处理 / 有残留可清空
function updateOffbar(){const bar=$("#offbar");if(!bar)return;offlineCount=Math.max(0,offlineCount);
  if(offlineCount>0){
    bar.style.display="flex";
    const icon=$("#offIcon"), label=$("#offLabel");
    if(!navigator.onLine){icon.textContent="📴";label.textContent="离线模式";}
    else if(_flushStatus==="syncing"){icon.textContent="⏳";label.textContent="正在上传";}
    else if(_flushStatus==="error"){icon.textContent="⚠️";label.textContent="上传失败";}
    else{icon.textContent="📦";label.textContent="本地暂存";}
    $("#qcount").textContent="· "+offlineCount+" 张";
  }else{bar.style.display="none";_flushStatus="";}}
// 上传到服务器：返回 {ok:true} 或 throw Error(原因)
function doUpload(blob,fname,name,cat){const fd=new FormData();fd.append("file",blob,fname||"photo.jpg");fd.append("report_key",KEY);fd.append("category",cat);fd.append("created_by",name);fd.append("mode",MODE);if(cat==="defect")fd.append("defect_index","");
  return fetch(withToken(API+"/api/photo/upload"),{method:"POST",body:fd,signal:AbortSignal.timeout(30000)}).then(r=>{
    if(!r.ok)throw new Error("HTTP "+r.status);
    return r.json();
  }).then(j=>{if(j.ok){hint("✓ 已上传（"+cat+"）","ok");$("#file").value="";loadList();return true;}
    throw new Error(j.msg||"服务端返回失败");});}
// 入队（仅在真正无法上传时调用）
async function enqueue(blob,fname,name,cat,errReason){
  try{const db=await openDB();await new Promise((res,rej)=>{const tx=db.transaction(STORE,"readwrite");tx.objectStore(STORE).add({blob:blob,name:fname,report_key:KEY,category:cat,created_by:name,defect:(cat==="defect"),ts:Date.now(),err:errReason||""});tx.oncomplete=res;tx.onerror=()=>rej(tx.error);});}catch(e){}
  offlineCount++;updateOffbar();}
// 拍照主入口：先尝试实时上传，失败才入队并提示原因
function upload(file){const name=$("#byName").value.trim()||"匿名";
  hint("上传中…","");compress(file,blob=>{doUpload(blob,file.name||"photo.jpg",name,active)
    .catch(err=>{const reason=(err&&err.message)||"网络异常";hint("✗ "+reason+"，已暂存本地","err");enqueue(blob,file.name||"photo.jpg",name,active,reason);});
  });}
// ── 核心修复：防重锁 + 逐条删 + 跳过孤儿 + 状态反馈 + 手动清空 ──
let _flushing=false;
async function flushQueue(){if(_flushing)return;_flushing=true;_flushStatus="syncing";updateOffbar();try{
  let items=await dbAll();
  // 过滤掉不属于当前报告的孤儿（防御性：即使 cleanStaleEntries 漏掉也能兜底）
  if(KEY)items=items.filter(it=>(it.report_key||"")===KEY);
  // 无待传项 → 确保横幅隐藏
  if(!items.length){offlineCount=0;updateOffbar();_flushing=false;return;}
  let okCount=0, failCount=0;
  for(const it of items){
    if(!navigator.onLine){_flushStatus="error";break;}
    try{
      const upOk=await doUpload(it.blob,it.name||"photo.jpg",it.created_by||"匿名",it.category);
      if(upOk){await dbDel(it.id);okCount++;offlineCount=Math.max(0,offlineCount-1);}
      else{failCount++;}
    }catch(e){failCount++;_flushStatus="error";}
    updateOffbar();
  }
  // 反馈结果
  if(failCount>0&&okCount===0)_flushStatus="error";
  else if(okCount>0)hint("✓ 已补传 "+okCount+" 张","ok");
  updateOffbar();loadList();
}catch(e){_flushStatus="error";updateOffbar();}
finally{_flushing=false;}}
// ── 页面加载时：① 清理孤儿 ② 查服务端清理已上传残留 ──
async function cleanStaleEntries(){
  if(!KEY)return false;
  let cleaned=false;
  try{
    const allItems=await dbAll();
    // ① 清理孤儿：IDB 中 report_key !== 当前 KEY 的记录（来自其他报告的残留）
    const orphans=allItems.filter(it=>(it.report_key||"")!==KEY);
    if(orphans.length>0){
      await dbDelByIds(orphans.map(o=>o.id));
      offlineCount=Math.max(0,offlineCount-orphans.length);
      cleaned=true;
    }
    // ② 联网时查服务端：当前报告已有照片 → 说明之前都上传成功，清掉剩余同KEY的残留
    if(navigator.onLine){
      try{
        const resp=await fetch(withToken(API+"/api/photo/list?report_key="+encodeURIComponent(KEY)));
        const j=await resp.json();
        if(j&&j.ok&&j.photos&&j.photos.length>0){
          await dbClearAll();offlineCount=0;updateOffbar();return true;
        }
      }catch(e){}
    }
    if(cleaned)updateOffbar();
  }catch(e){}
  return cleaned;
}
// ── 手动清空队列（用户点"清空"按钮）──
async function manualClear(){
  if(!confirm("确定清空所有待上传照片？\n（已成功上传到服务器的照片不受影响）"))return;
  await dbClearAll();offlineCount=0;_flushStatus="";updateOffbar();hint("✓ 队列已清空","ok");}

function upload(file){const name=$("#byName").value.trim()||"匿名";
  compress(file,blob=>{doUpload(blob,file.name||"photo.jpg",name,active).catch(()=>enqueue(blob,file.name||"photo.jpg",name,active));});
}
$("#file").addEventListener("change",e=>{const f=e.target.files&&e.target.files[0];if(!f){return;}if(!/image\//.test(f.type)){hint("请选择图片文件","err");return;}upload(f);hint("上传中…");});
function loadList(){fetch(withToken(API+"/api/photo/list?report_key="+encodeURIComponent(KEY))).then(r=>r.json()).then(j=>{if(!j.ok){return;}const w=$("#list");if(!j.photos.length){w.innerHTML='<div class="empty">暂无照片，拍照试试</div>';return;}const names={};CATS.forEach(c=>names[c.id]=c.name);w.innerHTML="";j.photos.forEach(p=>{const d=document.createElement("div");d.className="pc";const nm=names[p.category]||p.category;d.innerHTML='<img src="'+p.url+'" alt=""><button class="x" type="button">×</button><div class="b">'+nm+(p.caption?"："+p.caption:"")+"</div>";d.querySelector(".x").onclick=()=>del(p.id);w.appendChild(d);});}).catch(()=>{});}
function del(id){
  if(!confirm("删除这张照片？"))return;
  const by=encodeURIComponent($("#byName").value.trim()||"匿名");
  const base=withToken(API+"/api/photo/"+id);
  const u=base+(base.indexOf("?")>=0?"&":"?")+"by="+by;
  fetch(u,{method:"DELETE"}).then(r=>r.json()).then(j=>{if(j.ok)loadList();else alert("删除失败："+(j.msg||""));});
}

window.addEventListener("online",()=>{updateOffbar();flushQueue();});
window.addEventListener("offline",()=>{updateOffbar();});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&navigator.onLine)flushQueue();});
const rb=$("#retryBtn");if(rb)rb.addEventListener("click",()=>{if(navigator.onLine){hint("正在重试…");flushQueue();}else hint("仍离线，无法重试","err");});
const cb=$("#clearBtn");if(cb)cb.addEventListener("click",()=>manualClear());
// ── 启动：清理陈旧 → 统计队列 → 联网则自动补传 ──
(async()=>{
  try{
    const cleaned=await cleanStaleEntries();
    const items=await dbAll();offlineCount=items.length;updateOffbar();
    if(offlineCount>0&&navigator.onLine){
      // 有残留记录 → 自动尝试补传
      hint("发现 "+offlineCount+" 张暂存照片，正在补传…");
      await flushQueue();
    }else if(!cleaned&&offlineCount===0){
      // 干净状态：无残留
    }
  }catch(e){}})();

renderCats();setTimeout(loadList,300);
document.querySelector("#copyLink").addEventListener("click",()=>{navigator.clipboard.writeText(location.href).then(()=>hint("链接已复制，发给手机打开即可","ok")).catch(()=>prompt("复制此链接发到手机：",location.href));});
// 注册 Service Worker：支持「离线重开页面」；HTTP 局域网下浏览器不生效会自动降级，不影响上面的离线队列
if("serviceWorker" in navigator){window.addEventListener("load",()=>{navigator.serviceWorker.register("/capture-sw.js").catch(()=>{});});}
</script>
</body>
</html>"""

_CAPTURE_ERR = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>无法打开</title>
<style>body{font-family:-apple-system,"PingFang SC",sans-serif;background:#f1f5f9;color:#0f172a;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px;text-align:center;}
.b{max-width:420px;background:#fff;padding:28px;border-radius:14px;box-shadow:0 4px 16px rgba(0,0,0,.08);} h2{color:#dc2626;margin:0 0 10px;} p{color:#475569;line-height:1.6;}</style>
</head><body><div class="b"><h2>无法定位报告</h2><p>链接无效或报告不存在。<br>请在电脑端打开该报告，点击「📱 手机拍照」按钮重新获取上传链接。</p></div></body></html>"""


# Service Worker：导航 network-first + 缓存兜底，使「离线重开页面」可用（HTTPS/localhost 生效；HTTP 局域网自动降级，不影响离线队列）
_CAPTURE_SW = r"""// 验货拍照页 Service Worker
const CACHE='capture-v1';
const ORIGIN=self.location.origin;
self.addEventListener('install',e=>{self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(self.clients.claim());});
self.addEventListener('fetch',e=>{
  const req=e.request;
  if(req.method!=='GET'){return;}            // 写操作（上传/删除）直接放行，由页面 IndexedDB 队列处理离线
  let url;
  try{url=new URL(req.url);}catch(_){return;}
  if(url.origin!==ORIGIN){return;}
  if(req.mode==='navigate' && url.pathname.startsWith('/capture')){
    e.respondWith((async()=>{
      try{const net=await fetch(req);const c=await caches.open(CACHE);c.put(req,net.clone());return net;}
      catch(_){const hit=await caches.match(req)||await caches.match('/capture');
        if(hit)return hit;
        return new Response('<!DOCTYPE html><meta charset=utf-8><title>离线</title><body style="font-family:sans-serif;padding:20px">📴 当前离线，已拍照片会在恢复网络后自动上传。</body>',{headers:{'Content-Type':'text/html; charset=utf-8'}});}
    })());
    return;
  }
  if(url.pathname.startsWith('/api/photo/')){
    e.respondWith((async()=>{
      try{const net=await fetch(req);const c=await caches.open(CACHE);c.put(req,net.clone());return net;}
      catch(_){const hit=await caches.match(req);return hit||Response.error();}
    })());
    return;
  }
});
"""


def _reports_page():
    """钉钉工作台「调用程序」入口页：列出报告，同事点选后直达拍照页。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<title>验货报告拍照 · 选择报告</title>
<style>
  *{{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}}
  body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#f1f5f9;color:#0f172a;}}
  header{{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;padding:18px 16px 14px;}}
  header .t{{font-size:18px;font-weight:700;}} header .sub{{font-size:12.5px;opacity:.9;margin-top:4px;}}
  main{{padding:14px 14px 40px;max-width:680px;margin:0 auto;}}
  .search{{width:100%;padding:12px 14px;border:1px solid #e2e8f0;border-radius:10px;font-size:15px;margin-bottom:12px;}}
  .list .row{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;margin-bottom:10px;display:flex;align-items:center;gap:10px;cursor:pointer;}}
  .row:active{{background:#eff6ff;}}
  .row .no{{font-weight:700;color:#1d4ed8;font-size:14px;}}
  .row .meta{{flex:1;min-width:0;}}
  .row .prod{{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
  .row .sub{{font-size:12px;color:#64748b;margin-top:2px;}}
  .row .go{{color:#2563eb;font-size:13px;font-weight:700;}}
  .badge{{display:inline-block;font-size:11px;padding:1px 8px;border-radius:20px;background:#e2e8f0;color:#475569;margin-left:6px;}}
  .empty{{text-align:center;color:#94a3b8;padding:30px;font-size:13px;}}
  .tip{{font-size:12px;color:#64748b;text-align:center;margin-top:16px;line-height:1.6;}}
  .legacy{{background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:14px;margin:14px 0;}}
  .legacy h3{{margin:0 0 6px;font-size:15px;color:#9a3412;}}
  .legacy p{{margin:0 0 10px;font-size:12px;color:#7c2d12;line-height:1.5;}}
  .legacy input{{width:100%;padding:11px 12px;border:1px solid #fdba74;border-radius:8px;font-size:14px;margin-bottom:8px;}}
  .legacy button{{width:100%;padding:11px;border:0;border-radius:8px;background:#f97316;color:#fff;font-weight:700;font-size:14px;}}
</style></head>
<body>
<header><div class="t">📷 验货现场拍照</div><div class="sub">选择要拍照的报告 → 进入拍照页（自动归入对应图框）</div></header>
<main>
  <input class="search" id="q" placeholder="搜索报告号 / 产品名 / 供应商…">
  <section class="legacy">
    <h3>📷 旧品 / 无需入报告拍照</h3>
    <p>照片只上传 NAS，不进入在线检验报告图框。请输入产品或批次名称，系统会自动建立独立旧品照片目录。</p>
    <input id="legacyLabel" placeholder="例如：旧款蓝牙耳机 A 批次">
    <button type="button" onclick="openLegacy()">进入旧品独立拍照</button>
  </section>
  <div class="list" id="list"><div class="empty">加载中…</div></div>
  <div class="tip">在电脑端打开报告 → 第 8 项点「📱 二维码」扫码，可直达单一报告拍照页。</div>
</main>
<script>
const API=location.origin;
function openLegacy(){{
  const label=(document.getElementById("legacyLabel").value||"").trim()||"未命名旧品";
  const slug=label.replace(/[^\\u4e00-\\u9fffA-Za-z0-9_-]+/g,"-").replace(/^-+|-+$/g,"").slice(0,48)||"未命名旧品";
  const key="tmp_old_"+slug+"_"+Date.now().toString(36);
  location.href=API+"/capture?mode=legacy&key="+encodeURIComponent(key)+"&label="+encodeURIComponent(label);
}}
async function load(q){{
  let rows=[];
  try{{ const r=await fetch(API+"/api/reports"); const j=await r.json(); rows=j.reports||[]; }}catch(e){{}}
  if(q){{ q=q.toLowerCase(); rows=rows.filter(x=>(x.report_no+" "+(x.product_name||"")+" "+(x.supplier||"")).toLowerCase().includes(q)); }}
  const w=document.getElementById("list");
  if(!rows.length){{ w.innerHTML='<div class="empty">无匹配报告</div>'; return; }}
  w.innerHTML="";
  rows.forEach(x=>{{
    const d=document.createElement("div"); d.className="row";
    const st=x.status||"";
    d.innerHTML='<div class="no">'+x.report_no+'</div><div class="meta"><div class="prod">'+(x.product_name||"未命名")+'</div><div class="sub">'+(x.supplier||"")+(st?'<span class="badge">'+st+'</span>':"")+'</div></div><div class="go">拍照 ›</div>';
    d.onclick=()=>{{ location.href=API+"/capture?rid="+x.id; }};
    w.appendChild(d);
  }});
}}
document.getElementById("q").addEventListener("input",e=>load(e.target.value.trim()));
load("");
</script>
</body></html>"""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _check_token(req_handler):
    if not TOKEN:
        return True
    # URL ?token= 或 Header X-Photo-Token
    q = dict(_parse_qs(req_handler.path.split("?", 1)[-1])) if "?" in req_handler.path else {}
    tok_url = q.get("token", [""])[0]
    tok_hdr = req_handler.headers.get("X-Photo-Token", "")
    return tok_url == TOKEN or tok_hdr == TOKEN


def _parse_qs(qs):
    out = {}
    for pair in qs.split("&"):
        if not pair:
            continue
        k, _, v = pair.partition("=")
        out.setdefault(k, []).append(v)
    return out


# ── multipart 解析（标准库，无 cgi 依赖）──
def _parse_multipart(body, boundary):
    """返回 [(name, filename, content_type, value_bytes), ...]"""
    parts = []
    delim = b"--" + boundary.encode()
    for seg in body.split(delim):
        seg = seg.strip(b"\r\n")
        if not seg or seg == b"--":
            continue
        if b"\r\n\r\n" not in seg:
            continue
        head, _, content = seg.partition(b"\r\n\r\n")
        # head 可能多行
        head_lines = head.decode("utf-8", "replace").split("\r\n")
        disp = ""
        ctype = ""
        for hl in head_lines:
            if hl.lower().startswith("content-disposition:"):
                disp = hl
            elif hl.lower().startswith("content-type:"):
                ctype = hl.split(":", 1)[1].strip()
        name = ""
        filename = ""
        for kv in disp.split(";"):
            kv = kv.strip()
            if kv.startswith("name="):
                name = kv[5:].strip('"')
            elif kv.startswith("filename="):
                filename = kv[9:].strip('"')
        parts.append((name, filename, ctype, content))
    return parts


def _save_local(filename, data):
    # 防重名
    base, ext = os.path.splitext(filename)
    dest = os.path.join(CACHE_DIR, filename)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(CACHE_DIR, f"{base}_{i}{ext}")
        i += 1
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def _ext_from_ct(ctype, fallback=".jpg"):
    if ctype:
        guessed = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ""
        if guessed:
            return guessed
    return fallback


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静默

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, fallback_nas=None):
        data = None
        ctype = "image/jpeg"
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
        elif fallback_nas:
            try:
                data, _ = download_file(fallback_nas)
            except Exception:
                data = None
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_js(self, js, code=200):
        body = js.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/capture":
            qs = _parse_qs(self.path.split("?", 1)[-1]) if "?" in self.path else {}
            key = qs.get("key", [""])[0]
            rid = qs.get("rid", [""])[0]
            no = qs.get("no", [""])[0]
            by = qs.get("by", [""])[0]
            cat = qs.get("cat", [""])[0]
            mode = qs.get("mode", [""])[0] or "new"
            # mode: new=新品（进报告+NAS）；old=旧品（仅NAS归档，缺陷除外）
            meta = _resolve_report(key, int(rid) if rid.isdigit() else None, no)
            if not meta and _is_temp_key(key):
                meta = _build_temp_meta(key)
            if not meta:
                return self._send_html(_CAPTURE_ERR, 404)
            rk = str(key or "").strip() if _is_temp_key(key) else ("r" + str(meta["id"]))
            html = (_CAPTURE_TMPL
                    .replace("__KEY__", rk)
                    .replace("__CATS__", json.dumps(CAPTURE_CATS, ensure_ascii=False))
                    .replace("__TOKEN__", json.dumps(TOKEN))
                    .replace("__META__", _escape_html(_meta_text(meta)))
                    .replace("__PRESET__", json.dumps(cat))
                    .replace("__BY__", _escape_html(by))
                    .replace("__MODE__", _escape_html(mode)))
            return self._send_html(html)
        if path == "/capture-sw.js":
            return self._send_js(_CAPTURE_SW)
        if path == "/api/photo/list":
            if not _check_token(self):
                return self._send_json({"ok": False, "msg": "token 无效"}, 403)
            qs = _parse_qs(self.path.split("?", 1)[-1]) if "?" in self.path else {}
            rk = qs.get("report_key", [""])[0]
            photos = odb.list_photos(report_key=rk) if rk else []
            base = _request_base(self)
            out = [{"id": p["id"], "category": p["category"],
                    "defect_index": p["defect_index"], "caption": p["caption"],
                    "archive_only": int(p.get("archive_only") or 0),
                    "url": f"{base}/api/photo/{p['id']}"} for p in photos]
            return self._send_json({"ok": True, "photos": out})
        if path == "/api/photo/consistency":
            # PDF↔NAS 一致性校验：报告每张照片都应在 NAS 有对应实体文件
            if not _check_token(self):
                return self._send_json({"ok": False, "msg": "token 无效"}, 403)
            qs = _parse_qs(self.path.split("?", 1)[-1]) if "?" in self.path else {}
            rk = qs.get("report_key", [""])[0]
            photos = odb.list_photos(report_key=rk) if rk else []
            issues = []
            try:
                from nas_client import list_files
                import os
            except Exception:
                list_files = None
            for p in photos:
                np_ = p.get("nas_path")
                if not np_:
                    issues.append(f"照片#{p['id']}（{p.get('category')}）尚未上传到 NAS")
                    continue
                if list_files:
                    try:
                        folder = os.path.dirname(np_)
                        name = os.path.basename(np_)
                        lst = list_files(folder)
                        names = [f.get("name") for f in lst] if isinstance(lst, list) else []
                        if name not in names:
                            issues.append(f"照片#{p['id']}（{p.get('category')}）NAS 文件缺失：{os.path.basename(np_)}")
                    except Exception as e:
                        issues.append(f"照片#{p['id']} NAS 校验异常：{e}")
            return self._send_json({"ok": True, "consistent": len(issues) == 0,
                                     "issues": issues, "total": len(photos)})
        if path.startswith("/api/photo/") and path.count("/") == 3:
            pid = path.split("/")[-1]
            if not pid.isdigit():
                return self._send_json({"ok": False, "msg": "bad id"}, 400)
            ph = odb.get_photo(int(pid))
            if not ph or ph.get("deleted"):
                return self._send_json({"ok": False, "msg": "不存在或已删除"}, 404)
            return self._send_file(ph.get("local_path"), ph.get("nas_path"))
        if path == "/reports":
            # 钉钉工作台「调用程序」入口：列出报告，同事点选后直达拍照页（解决报告匹配问题）
            return self._send_html(_reports_page(), 200)
        if path == "/api/reports":
            # 供选择页前端搜索用的 JSON 接口（直接只读连生产库，绕过 get_connection 远程缓存坑）
            try:
                rp = None
                try:
                    import database as _dbmod
                    rp = _dbmod._resolve_remote_audit_db()
                except Exception:
                    rp = None
                if rp:
                    conn = sqlite3.connect(f"file:{rp}?mode=ro", uri=True, timeout=10)
                else:
                    conn = sqlite3.connect(_dbmod.DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, report_no, product_name, supplier, status FROM online_reports ORDER BY id DESC LIMIT 200"
                ).fetchall()
                conn.close()
                reports = [dict(r) for r in rows]
            except Exception:
                reports = []
            return self._send_json({"ok": True, "reports": reports})
        return self._send_json({"ok": False, "msg": "not found"}, 404)

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/photo/") and path.count("/") == 3:
            if not _check_token(self):
                return self._send_json({"ok": False, "msg": "token 无效"}, 403)
            pid = path.split("/")[-1]
            if not pid.isdigit():
                return self._send_json({"ok": False, "msg": "bad id"}, 400)
            qs = _parse_qs(self.path.split("?", 1)[-1]) if "?" in self.path else {}
            by = qs.get("by", [""])[0]
            ok, msg = odb.soft_delete_photo(int(pid), by=by)
            return self._send_json({"ok": ok, "msg": msg}, 200 if ok else 400)
        return self._send_json({"ok": False, "msg": "not found"}, 404)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/photo/upload":
            return self._send_json({"ok": False, "msg": "not found"}, 404)
        if not _check_token(self):
            return self._send_json({"ok": False, "msg": "token 无效"}, 403)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._send_json({"ok": False, "msg": "需 multipart/form-data"}, 400)
        boundary = ctype.split("boundary=")[-1].strip().strip('"')
        parts = _parse_multipart(body, boundary)

        fields = {}
        file_part = None
        for name, filename, pctype, content in parts:
            if name == "file" and filename:
                file_part = (filename, pctype, content)
            else:
                fields[name] = content.decode("utf-8", "replace")

        if not file_part:
            return self._send_json({"ok": False, "msg": "缺少文件"}, 400)

        fname, fctype, fdata = file_part
        report_key = fields.get("report_key", "")
        category = fields.get("category", "other")
        defect_index = fields.get("defect_index")
        defect_index = int(defect_index) if defect_index and defect_index.isdigit() else None
        seq = fields.get("seq", "0")
        seq = int(seq) if seq.isdigit() else 0
        caption = fields.get("caption", "")
        created_by = fields.get("created_by", "")

        # ── 检测旧品模式：旧品非缺陷照片仅存档 NAS，不进入报告 PDF ──
        _archive_only = 0
        _mode_param = (fields.get("mode", "") or "").strip().lower()
        if report_key.startswith("r"):
            try:
                _rid_int = int(report_key[1:])
                _or = odb.get_online_report(_rid_int)
                if _or:
                    import json as _json
                    _d = _json.loads(_or.get("data_json", "{}") or "{}") if isinstance(_or.get("data_json"), str) else (_or.get("data_json") or {})
                    _basic = _d.get("basic", {}) or {}
                    if str(_basic.get("productMode", "") or "").lower() in ("old", "旧品"):
                        if category not in ("defect",):
                            _archive_only = 1
            except Exception:
                pass
        # mode 请求参数兜底（二维码已编码产品模式，即使报告尚未保存也能正确判定）
        if not _archive_only and _mode_param == "old" and category not in ("defect",):
            _archive_only = 1

        if not report_key:
            return self._send_json({"ok": False, "msg": "缺少 report_key"}, 400)

        # 本地缓存
        ext = os.path.splitext(fname)[1].lower() or _ext_from_ct(fctype)
        storage_key = odb.storage_key_for_report_key(report_key)
        safe_name = f"{storage_key}_{category}_{seq}_{datetime.now().strftime('%H%M%S%f')}{ext}".replace("/", "_")
        local_path = _save_local(safe_name, fdata)
        sha = hashlib.sha256(fdata).hexdigest()

        # NAS 上传（不可达则跳过，本地已兜底）
        nas_path = None
        try:
            ok_nas, res = check_connection()
            if ok_nas:
                # 一级目录与正式报告同名，二级目录使用中文拍摄分类。
                nas_base = odb.get_report_nas_photo_folder(report_key)
                category_folder = CAPTURE_CATEGORY_FOLDERS.get(category, "其他检测")
                if nas_base:
                    nas_folder = f"{nas_base}/{category_folder}"
                else:
                    nas_folder = f"{NAS_PHOTO_ROOT}/{storage_key}/{category_folder}"
                nas_name = safe_name
                ok_up, nas_path = upload_file(nas_folder, nas_name, fdata)
                if not ok_up:
                    nas_path = None
        except Exception:
            nas_path = None

        pid = odb.add_photo(
            report_key=report_key, category=category, filename=safe_name,
            local_path=local_path, nas_path=nas_path, sha256=sha,
            caption=caption, seq=seq, defect_index=defect_index,
            created_by=created_by, archive_only=_archive_only,
        )
        odb.add_audit(created_by or "system", "upload_photo", "report_photo", str(pid),
                      f"类别={category} 文件={safe_name} NAS={'是' if nas_path else '否'}")
        return self._send_json({
            "ok": True, "photo_id": pid,
            "url": f"{API_BASE}/api/photo/{pid}",
            "nas": bool(nas_path),
        })

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Photo-Token")
        self.end_headers()


def main():
    odb.init_online_report_table()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"📷 照片后端已启动: http://0.0.0.0:{PORT}  (API_BASE={API_BASE})")
    print(f"   本地缓存: {CACHE_DIR}")
    print(f"   NAS 根: {NAS_PHOTO_ROOT}  | 令牌校验: {'开启' if TOKEN else '关闭(开发)'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
