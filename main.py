import os,re,secrets,sqlite3,subprocess,shutil,json
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask,render_template,request,jsonify,send_file,session,redirect,url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

BASE=Path(__file__).resolve().parent.parent; DB=BASE/"data/downora.db"; TMP=Path("/tmp/downora"); TMP.mkdir(exist_ok=True)
app=Flask(__name__); app.secret_key=os.getenv("DOWNORA_SESSION_SECRET",secrets.token_hex(32))
limiter=Limiter(key_func=get_remote_address,app=app,default_limits=["120/hour"])
ADMIN=os.getenv("DOWNORA_ADMIN_PASSWORD",""); MAXMB=int(os.getenv("DOWNORA_MAX_MB","500"))
HOSTS={"youtube.com","youtu.be","tiktok.com","instagram.com","facebook.com","fb.watch","vimeo.com","x.com","twitter.com"}
def init():
 c=sqlite3.connect(DB); c.execute("create table if not exists stats(k text primary key,v integer default 0)")
 for k in ("analyze","download","error"): c.execute("insert or ignore into stats values(?,0)",(k,))
 c.commit(); c.close()
init()
def inc(k):
 c=sqlite3.connect(DB); c.execute("update stats set v=v+1 where k=?",(k,)); c.commit(); c.close()
def valid(u):
 try:
  p=urlparse(u); h=(p.hostname or "").lower()
  return p.scheme in ("http","https") and any(h==x or h.endswith("."+x) for x in HOSTS)
 except: return False
def info(u):
 p=subprocess.run(["yt-dlp","--no-playlist","--skip-download","--dump-single-json","--no-warnings","--socket-timeout","15","--retries","1",u],capture_output=True,text=True,timeout=45)
 if p.returncode: raise RuntimeError()
 return json.loads(p.stdout)
@app.get("/")
def home(): return render_template("index.html")
@app.post("/api/analyze")
@limiter.limit("12/minute")
def analyze():
 u=(request.json or {}).get("url","").strip()
 if not valid(u): inc("error"); return jsonify(error="الرابط غير مدعوم"),400
 try:
  x=info(u); fs=[]; seen=set()
  for f in sorted(x.get("formats",[]),key=lambda z:z.get("height") or 0,reverse=True):
   if not f.get("url") or f.get("ext") not in ("mp4","webm","m4a","mp3"): continue
   v=f.get("vcodec") not in (None,"none"); a=f.get("acodec") not in (None,"none")
   if not(v or a): continue
   key=(f.get("ext"),f.get("format_note"),f.get("height"),v,a)
   if key in seen: continue
   seen.add(key); fs.append({"id":f.get("format_id"),"ext":f.get("ext"),"q":f.get("format_note") or (str(f.get("height"))+"p" if f.get("height") else "audio"),"v":v,"a":a})
  inc("analyze"); return jsonify(title=x.get("title","Video"),thumbnail=x.get("thumbnail"),uploader=x.get("uploader"),formats=fs[:30])
 except: inc("error"); return jsonify(error="تعذر تحليل الرابط. جرّب رابطًا عامًا آخر."),502
@app.post("/api/download")
@limiter.limit("6/minute")
def download():
 d=request.json or {}; u=d.get("url","").strip(); f=d.get("format_id","").strip()
 if not valid(u) or not re.fullmatch(r"[\w.+-]+",f): return jsonify(error="طلب غير صالح"),400
 job=secrets.token_hex(8); out=TMP/job; out.mkdir(); tmpl=str(out/"%(title).80B.%(ext)s")
 cmd=["yt-dlp","--no-playlist","--no-warnings","--socket-timeout","15","--retries","1","--max-filesize",f"{MAXMB}M","-f",f,"-o",tmpl,u]
 try:
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
  fs=[x for x in out.iterdir() if x.is_file()]
  if p.returncode or not fs: raise RuntimeError()
  inc("download"); return send_file(fs[0],as_attachment=True,download_name=fs[0].name,max_age=0)
 except subprocess.TimeoutExpired:
  inc("error"); shutil.rmtree(out,ignore_errors=True); return jsonify(error="التحميل استغرق وقتًا طويلًا"),504
 except:
  inc("error"); shutil.rmtree(out,ignore_errors=True); return jsonify(error="تعذر تجهيز الملف"),502
@app.get("/admin/login")
def login(): return render_template("login.html",error=None)
@app.post("/admin/login")
def login_post():
 if secrets.compare_digest(request.form.get("password",""),ADMIN):
  session["admin"]=1; return redirect("/admin")
 return render_template("login.html",error="كلمة المرور غير صحيحة")
@app.get("/admin")
def admin():
 if not session.get("admin"): return redirect("/admin/login")
 c=sqlite3.connect(DB); s=dict(c.execute("select k,v from stats")); c.close()
 return render_template("admin.html",stats=s,maxmb=MAXMB)
@app.get("/health")
def health(): return {"ok":True}
