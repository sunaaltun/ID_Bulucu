#!/usr/bin/env python3
"""ID Bulucu: Instagram, Facebook, X/Twitter ve TikTok kullanıcı adından hesap ID'si bulur.

Kurulum:  pip install flask requests
Çalıştır: python id_bulucu.py   ->  http://127.0.0.1:5000
"""
import html, json, os, re, threading, webbrowser
import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
T = 15


def clean(raw):
    """@kullanici, profil linki veya düz kullanıcı adını temizler."""
    u = (raw or "").strip()
    u = re.sub(r"^https?://[^/]+/", "", u).split("?")[0].strip("/").split("/")[0]
    return u.lstrip("@")


def twitter(u, tok):
    tok = tok or os.getenv("TWITTER_BEARER_TOKEN")
    if not tok:
        raise LookupError("X için Bearer Token gerekli. Ayarlar bölümünden ekleyin.")
    r = S.get(f"https://api.twitter.com/2/users/by/username/{u}",
              params={"user.fields": "name,public_metrics"},
              headers={"Authorization": f"Bearer {tok}"}, timeout=T)
    if r.status_code == 401:
        raise LookupError("Token geçersiz.")
    if r.status_code == 429:
        raise LookupError("İstek limiti aşıldı, biraz bekleyin.")
    d = r.json().get("data")
    if not d:
        raise LookupError("Kullanıcı bulunamadı veya askıya alınmış.")
    return dict(id=d["id"], name=d.get("name"),
                extra={"Takipçi": d.get("public_metrics", {}).get("followers_count")})


def instagram(u, _):
    try:
        r = S.get("https://i.instagram.com/api/v1/users/web_profile_info/",
                  params={"username": u},
                  headers={"x-ig-app-id": "936619743392459",
                           "User-Agent": "Instagram 219.0.0.12.117 Android"}, timeout=T)
        if r.status_code == 404:
            raise LookupError("Kullanıcı bulunamadı.")
        if r.ok:
            us = r.json()["data"]["user"]
            return dict(id=us["id"], name=us.get("full_name"),
                        extra={"Takipçi": us.get("edge_followed_by", {}).get("count"),
                               "Gizli hesap": "Evet" if us.get("is_private") else "Hayır"})
    except (requests.RequestException, KeyError, TypeError, ValueError):
        pass  # i.instagram.com erişilemedi veya beklenmedik yanıt: www ile devam et
    t = S.get(f"https://www.instagram.com/{u}/", timeout=T).text
    m = re.search(r'"profilePage_(\d+)"', t) or re.search(r'"user_id":"(\d+)"', t)
    if m:
        return dict(id=m.group(1), name=None, extra={})
    raise LookupError("Instagram isteği engelledi (giriş duvarı veya limit). Biraz sonra tekrar deneyin.")


def facebook(u, tok):
    tok = tok or os.getenv("FB_ACCESS_TOKEN")
    if tok:
        j = S.get(f"https://graph.facebook.com/v19.0/{u}",
                  params={"fields": "id,name", "access_token": tok}, timeout=T).json()
        if "id" in j:
            return dict(id=j["id"], name=j.get("name"), extra={})
    r = S.get(f"https://www.facebook.com/{u}", timeout=T)
    if r.status_code == 404:
        raise LookupError("Profil veya sayfa bulunamadı.")
    t = r.text
    m = (re.search(r'"(?:userID|entity_id|pageID)":"(\d{5,})"', t)
         or re.search(r"fb://(?:profile|page)/(?:\?id=)?(\d+)", t))
    if not m:
        raise LookupError("Facebook ID'yi vermedi (giriş duvarı). Ayarlardan Graph API token ekleyin.")
    n = re.search(r'<meta property="og:title" content="([^"]+)"', t)
    return dict(id=m.group(1), name=html.unescape(n.group(1)) if n else None, extra={})


def tiktok(u, _):
    t = S.get(f"https://www.tiktok.com/@{u}", timeout=T).text
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', t, re.S)
    if not m:
        raise LookupError("TikTok yanıtı okunamadı (bot koruması). Biraz sonra tekrar deneyin.")
    try:
        d = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
        return dict(id=d["user"]["id"], name=d["user"].get("nickname"),
                    extra={"secUid": d["user"].get("secUid"),
                           "Takipçi": d.get("stats", {}).get("followerCount")})
    except (KeyError, TypeError, ValueError):
        raise LookupError("Kullanıcı bulunamadı.")


FN = dict(instagram=instagram, facebook=facebook, twitter=twitter, tiktok=tiktok)


@app.post("/api/lookup")
def lookup():
    b = request.get_json(force=True, silent=True) or {}
    p, u = b.get("platform"), clean(b.get("username"))
    if p not in FN or not u:
        return jsonify(ok=False, error="Geçersiz istek"), 400
    try:
        return jsonify(ok=True, platform=p, username=u, **FN[p](u, b.get("token")))
    except LookupError as e:
        return jsonify(ok=False, platform=p, username=u, error=str(e))
    except requests.RequestException as e:
        kind = type(e).__name__
        hint = {"SSLError": "SSL/sertifika sorunu (antivirüs veya VPN olabilir).",
                "ProxyError": "Proxy ayarı sorunu.",
                "ConnectTimeout": "Zaman aşımı: site bu ağdan erişilemiyor olabilir.",
                "ReadTimeout": "Zaman aşımı: site yanıt vermedi.",
                "ConnectionError": "Siteye bağlanılamadı (DNS, güvenlik duvarı veya erişim engeli)."}.get(kind, "")
        return jsonify(ok=False, platform=p, username=u,
                       error=f"Bağlantı hatası [{kind}]. {hint} Ayrıntı: {str(e)[:160]}")


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


PAGE = r"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ID Bulucu</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@400;600;800&family=JetBrains+Mono:wght@500;700&display=swap">
<style>
:root{--bg:#e9edf4;--card:#fff;--ink:#141b2d;--mute:#667089;--line:#d5dbe8;--soft:#f3f5fa;--accent:#3b4cca;
--sans:'Bricolage Grotesque',system-ui,sans-serif;--mono:'JetBrains Mono',ui-monospace,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#0e1220;--card:#171d31;--ink:#eef1fa;--mute:#98a2c0;--line:#2a3354;--soft:#1e2540;--accent:#8c9bff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.5 var(--sans)}
.wrap{max-width:1100px;margin:0 auto;padding:48px 20px 80px}
h1{font-size:clamp(34px,6vw,64px);line-height:1;letter-spacing:-.03em;font-weight:800;margin:0 0 14px;max-width:11em}
.lead{color:var(--mute);max-width:46ch;margin:0 0 36px}
.grid{display:grid;grid-template-columns:380px 1fr;gap:24px;align-items:start}
@media(max-width:860px){.grid{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:22px;position:sticky;top:20px}
@media(max-width:860px){.panel{position:static}}
.lbl{font-weight:600;font-size:14px;margin:0 0 10px;display:block}
.chips{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:20px}
.chip{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1.5px solid var(--line);border-radius:12px;background:transparent;color:var(--ink);font:600 14px var(--sans);cursor:pointer;text-align:left}
.chip i{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;font:700 12px var(--sans);font-style:normal;color:#fff;background:var(--c);opacity:.45}
.chip[aria-pressed=true]{border-color:var(--c);background:var(--soft)}
.chip[aria-pressed=true] i{opacity:1}
textarea,input{width:100%;border:1.5px solid var(--line);border-radius:12px;background:var(--soft);color:var(--ink);padding:12px 14px;font:500 14px var(--mono);resize:vertical}
textarea:focus,input:focus,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn{width:100%;margin-top:14px;padding:14px;border:0;border-radius:12px;background:var(--accent);color:#fff;font:700 16px var(--sans);cursor:pointer}
@media(prefers-color-scheme:dark){.btn{color:#0e1220}}
.btn:disabled{opacity:.6;cursor:wait}
details{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}
summary{cursor:pointer;font-weight:600;font-size:14px}
details input{margin-top:8px;font-size:13px}
details small{display:block;color:var(--mute);margin-top:10px;line-height:1.45}
.bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;min-height:34px}
.bar span{color:var(--mute);font-size:14px}
.ghost{border:1.5px solid var(--line);background:transparent;color:var(--ink);border-radius:10px;padding:7px 12px;font:600 13px var(--sans);cursor:pointer}
.empty{border:2px dashed var(--line);border-radius:20px;padding:56px 24px;text-align:center;color:var(--mute)}
.res{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:16px;padding:18px 20px;margin-bottom:12px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.top b{font-weight:800;font-size:18px}
.tag{font-size:13px;color:var(--mute)}
.id{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:14px;padding-top:14px;border-top:2px dashed var(--line)}
.id code{font:700 clamp(18px,3.4vw,28px) var(--mono);letter-spacing:.02em;word-break:break-all}
.meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.meta span{background:var(--soft);border-radius:8px;padding:4px 10px;font-size:13px;color:var(--mute)}
.err{color:#c4372f;margin:10px 0 0;font-size:14px}
@media(prefers-color-scheme:dark){.err{color:#ff8a80}}
.sk{height:26px;margin-top:14px;border-radius:8px;background:linear-gradient(90deg,var(--soft),var(--line),var(--soft));background-size:200% 100%;animation:sh 1.2s linear infinite}
@keyframes sh{to{background-position:-200% 0}}
@media(prefers-reduced-motion:reduce){.sk{animation:none}}
</style></head><body><div class="wrap">
<h1>Kullanıcı adından hesap ID’sine.</h1>
<p class="lead">Instagram, Facebook, X ve TikTok için tek ekrandan ID sorgulayın. Birden fazla kullanıcı adı veya profil linki yapıştırabilirsiniz.</p>
<div class="grid">
<section class="panel">
  <span class="lbl">Platformlar</span>
  <div class="chips" id="chips"></div>
  <label class="lbl" for="names">Kullanıcı adları (her satıra bir tane)</label>
  <textarea id="names" rows="6" placeholder="@kullanici&#10;https://www.tiktok.com/@ornek"></textarea>
  <button class="btn" id="go">ID’leri bul</button>
  <details><summary>Ayarlar (isteğe bağlı API anahtarları)</summary>
    <input id="tw" type="password" placeholder="X Bearer Token" autocomplete="off">
    <input id="fb" type="password" placeholder="Facebook Graph API token" autocomplete="off" style="margin-top:8px">
    <small>X için Bearer Token zorunludur. Facebook tokenı yoksa sayfa kaynağından okuma denenir. Anahtarlar yalnızca bu bilgisayardaki yerel sunucuya gider.</small>
  </details>
</section>
<section>
  <div class="bar"><span id="count"></span><button class="ghost" id="csv" hidden>CSV indir</button></div>
  <div id="out"><div class="empty">Henüz sorgu yok. Soldan platform seçip kullanıcı adı girin.</div></div>
</section>
</div></div>
<script>
const P={instagram:{n:'Instagram',c:'#e1306c',i:'IG'},facebook:{n:'Facebook',c:'#1877f2',i:'f'},
twitter:{n:'X / Twitter',c:'var(--ink)',i:'X'},tiktok:{n:'TikTok',c:'#10b5ae',i:'TT'}};
const sel=new Set(Object.keys(P)),$=id=>document.getElementById(id);
let rows=[];
const chips=$('chips');
for(const k in P){const b=document.createElement('button');b.className='chip';b.style.setProperty('--c',P[k].c);
 b.setAttribute('aria-pressed','true');b.innerHTML=`<i>${P[k].i}</i>${P[k].n}`;
 b.onclick=()=>{sel.has(k)?sel.delete(k):sel.add(k);b.setAttribute('aria-pressed',sel.has(k))};chips.append(b)}
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const detect=l=>l.includes('instagram.com')?'instagram':l.includes('facebook.com')||l.includes('fb.com')?'facebook':
 l.includes('twitter.com')||l.includes('x.com/')?'twitter':l.includes('tiktok.com')?'tiktok':null;
function draw(){
 const o=$('out');
 if(!rows.length){return}
 o.innerHTML=rows.map((r,i)=>{const p=P[r.platform];
  let body=r.state==='load'?'<div class="sk"></div>':r.ok?
  `<div class="id"><code>${esc(r.id)}</code><button class="ghost" data-i="${i}">Kopyala</button></div>
   <div class="meta">${Object.entries(r.extra||{}).filter(([,v])=>v!=null).map(([k,v])=>`<span>${esc(k)}: ${esc(typeof v==='number'?v.toLocaleString('tr-TR'):v)}</span>`).join('')}</div>`
   :`<p class="err">${esc(r.error)}</p>`;
  return `<article class="res" style="--c:${p.c}"><div class="top"><b>${esc(r.name||'@'+r.username)}</b><span class="tag">${p.n} · @${esc(r.username)}</span></div>${body}</article>`}).join('');
 o.querySelectorAll('[data-i]').forEach(b=>b.onclick=async()=>{await navigator.clipboard.writeText(rows[b.dataset.i].id);b.textContent='Kopyalandı';setTimeout(()=>b.textContent='Kopyala',1400)});
 const done=rows.filter(r=>r.state!=='load'),ok=rows.filter(r=>r.ok).length;
 $('count').textContent=`${rows.length} sorgu · ${ok} başarılı`;$('csv').hidden=!ok;
}
$('go').onclick=async()=>{
 const lines=$('names').value.split('\n').map(s=>s.trim()).filter(Boolean);
 if(!lines.length||!sel.size){$('out').innerHTML='<div class="empty">En az bir platform ve bir kullanıcı adı girin.</div>';return}
 const jobs=[];lines.forEach(l=>{const d=detect(l);(d?[d]:[...sel]).forEach(p=>jobs.push({platform:p,username:l.replace(/^https?:\/\/[^/]+\//,'').split(/[/?]/)[0].replace(/^@/,''),state:'load'}))});
 rows=jobs;draw();$('go').disabled=true;
 for(const r of rows){
  try{const res=await fetch('/api/lookup',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({platform:r.platform,username:r.username,token:r.platform==='twitter'?$('tw').value:r.platform==='facebook'?$('fb').value:''})});
   Object.assign(r,await res.json())}catch(e){r.ok=false;r.error='Yerel sunucuya ulaşılamadı.'}
  r.state='done';draw();await new Promise(s=>setTimeout(s,400));
 }
 $('go').disabled=false;
};
$('csv').onclick=()=>{
 const t='platform,kullanici_adi,id,isim\n'+rows.filter(r=>r.ok).map(r=>[r.platform,r.username,r.id,r.name||''].map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')).join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+t],{type:'text/csv'}));a.download='idler.csv';a.click();
};
</script></body></html>"""

if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000)
