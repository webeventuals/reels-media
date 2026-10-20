"""Post each incoming/<id>/ reel to IG, Threads, FB. Per-platform state in state/<id>.json makes reruns idempotent.
Every API call's raw response is appended to publish_log/<id>_<ts>.json (tokens are never logged)."""
import os, glob, json, time, datetime, shutil, requests

E_ = os.environ
REPO = "webeventuals/reels-media"
os.makedirs("publish_log", exist_ok=True)
os.makedirs("state", exist_ok=True)


def make_call(log):
    def call(platform, method, url, **kw):
        r = requests.request(method, url, timeout=120, **kw)
        try:
            j = r.json()
        except Exception:
            j = {"raw": r.text[:500]}
        log.append({"at": datetime.datetime.now().isoformat(), "platform": platform, "method": method,
                    "url": url.split("?")[0], "status": r.status_code, "response": j})
        if r.status_code >= 400:
            raise RuntimeError(f"{platform} {url.split('?')[0]} {r.status_code} {j}")
        return j
    return call


def poll(call, platform, url, params, done, bad, tries=30, wait=20):
    for _ in range(tries):
        time.sleep(wait)
        j = call(platform, "GET", url, params=params)
        if any(x in json.dumps(j) for x in bad):
            raise RuntimeError(f"{platform} failed: {j}")
        if done(j):
            return j
    raise RuntimeError(f"{platform} timeout")


def ig(call, m, vurl):
    B = "https://graph.instagram.com/v21.0"
    t, u = E_["IG_ACCESS_TOKEN"], E_["IG_USER_ID"]
    data = {"media_type": "REELS", "video_url": vurl, "caption": m["instagram"], "access_token": t}
    if m.get("ig_trial"):  # trial reel: shown to non-followers only; value is MANUAL or SS_PERFORMANCE
        data["trial_params"] = json.dumps({"graduation_strategy": m["ig_trial"]})
    c = call("instagram", "POST", f"{B}/{u}/media", data=data)["id"]
    poll(call, "instagram", f"{B}/{c}", {"fields": "status_code,status", "access_token": t},
         lambda j: j.get("status_code") == "FINISHED", ('"ERROR"', '"EXPIRED"'))
    p = call("instagram", "POST", f"{B}/{u}/media_publish", data={"creation_id": c, "access_token": t})["id"]
    return call("instagram", "GET", f"{B}/{p}", params={"fields": "permalink", "access_token": t}).get("permalink", p)


def threads(call, m, vurl):
    B = "https://graph.threads.net/v1.0"
    t, u = E_["THREADS_ACCESS_TOKEN"], E_["THREADS_ID"]
    c = call("threads", "POST", f"{B}/{u}/threads",
             data={"media_type": "VIDEO", "video_url": vurl, "text": m["threads"], "access_token": t})["id"]
    poll(call, "threads", f"{B}/{c}", {"fields": "status,error_message", "access_token": t},
         lambda j: j.get("status") == "FINISHED", ('"ERROR"', '"EXPIRED"'))
    p = call("threads", "POST", f"{B}/{u}/threads_publish", data={"creation_id": c, "access_token": t})["id"]
    return call("threads", "GET", f"{B}/{p}", params={"fields": "permalink", "access_token": t}).get("permalink", p)


def fb(call, m, vurl):
    B = "https://graph.facebook.com/v21.0"
    t, pid = E_["FB_PAGE_ACCESS_TOKEN"], E_["FB_PAGE_ID"]
    s = call("facebook", "POST", f"{B}/{pid}/video_reels", data={"upload_phase": "start", "access_token": t})
    vid = s["video_id"]
    call("facebook", "POST", s["upload_url"], headers={"Authorization": f"OAuth {t}", "file_url": vurl})
    poll(call, "facebook", f"{B}/{vid}", {"fields": "status", "access_token": t},
         lambda j: j.get("status", {}).get("uploading_phase", {}).get("status") == "complete", ('"error"',))
    call("facebook", "POST", f"{B}/{pid}/video_reels",
         data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
               "description": m["facebook"], "title": m.get("fb_title", ""), "access_token": t})
    return vid


for d in sorted(glob.glob("incoming/*/")):
    m = json.load(open(d + "meta.json", encoding="utf-8"))
    rid = m["id"]
    sf = f"state/{rid}.json"
    st = json.load(open(sf, encoding="utf-8")) if os.path.exists(sf) else {}
    vurl = f"https://raw.githubusercontent.com/{REPO}/{E_['SHA']}/incoming/{rid}/video.mp4"
    log = []
    call = make_call(log)
    for name, fn in (("instagram", ig), ("threads", threads), ("facebook", fb)):
        if st.get(name, {}).get("ok"):
            continue
        try:
            st[name] = {"ok": True, "ref": fn(call, m, vurl), "at": datetime.datetime.now().isoformat()}
        except Exception as e:
            st[name] = {"ok": False, "error": str(e)[:800], "at": datetime.datetime.now().isoformat()}
        print(name, st[name]["ok"])
    json.dump(st, open(sf, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json.dump(log, open(f"publish_log/{rid}_{stamp}.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    if all(st.get(n, {}).get("ok") for n in ("instagram", "threads", "facebook")):
        shutil.rmtree(d)  # all three published: remove video and meta from the public repo
        print("cleaned", d)
