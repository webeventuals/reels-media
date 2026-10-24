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
    # AI voice on every reel: self-disclose by default; a queue entry can set "ai_label": false
    body = {"media_type": "REELS", "video_url": vurl, "caption": m["instagram"], "is_ai_generated": m.get("ai_label", True)}
    if m.get("cover"):  # JPEG cover shown in the grid/profile instead of a baked-in first frame
        body["cover_url"] = f"https://raw.githubusercontent.com/{REPO}/{E_['SHA']}/incoming/{m['id']}/cover.jpg"
    if m.get("ig_trial"):  # trial reel: shown to non-followers only; value is MANUAL or SS_PERFORMANCE
        body["trial_params"] = {"graduation_strategy": m["ig_trial"]}  # real JSON object, sent as a JSON body
    c = call("instagram", "POST", f"{B}/{u}/media", json=body,
             headers={"Authorization": f"Bearer {t}"})["id"]
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


def youtube(call, m, vpath):
    # token refresh is not routed through call(): its response holds the access token
    r = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": E_["YT_CLIENT_ID"], "client_secret": E_["YT_CLIENT_SECRET"],
        "refresh_token": E_["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"})
    if r.status_code >= 400:
        raise RuntimeError(f"youtube token refresh {r.status_code} {r.text[:300]}")
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    # YouTube gets its own title/description (search-first, #Shorts); fallback only if the queue entry lacks them
    title = m.get("youtube_title") or (m.get("fb_title") or m["instagram"].split("\n")[0])[:90].strip() + " #Shorts"
    desc = m.get("youtube_description") or m.get("facebook") or m["instagram"]
    body = {"snippet": {"title": title[:100], "description": desc, "categoryId": "27", "tags": m.get("youtube_tags", []),
                        "defaultLanguage": "hi", "defaultAudioLanguage": "hi"},  # Hinglish voice and text
            # location was removed from the API in 2017; only the date can be set
            "recordingDetails": {"recordingDate": m["publish_after_ist"][:10] + "T00:00:00Z"},
            "status": {"privacyStatus": m.get("yt_privacy", "public"), "selfDeclaredMadeForKids": False}}
    s = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status,recordingDetails",
                      json=body, timeout=60, headers={**h, "X-Upload-Content-Type": "video/mp4",
                                                      "X-Upload-Content-Length": str(os.path.getsize(vpath))})
    if s.status_code >= 400:
        raise RuntimeError(f"youtube upload start {s.status_code} {s.text[:300]}")
    with open(vpath, "rb") as f:
        v = call("youtube", "PUT", s.headers["Location"], data=f, headers={**h, "Content-Type": "video/mp4"})
    url = f"https://youtube.com/shorts/{v['id']}"
    if m.get("youtube_playlist"):
        # the video is already live: a playlist failure must not mark youtube failed, or a rerun would upload it twice
        try:
            add_to_playlist(call, h, v["id"], m["youtube_playlist"], m.get("youtube_playlist_description", ""))
        except Exception as e:
            print("youtube playlist failed:", str(e)[:300])
    return url


def add_to_playlist(call, h, vid, name, desc):
    # topic playlist by exact title; created on first use so a new topic needs only a new name in the queue
    B = "https://www.googleapis.com/youtube/v3"
    pl, tok = None, None
    while pl is None:
        j = call("youtube", "GET", f"{B}/playlists", headers=h,
                 params={"part": "snippet", "mine": "true", "maxResults": 50, **({"pageToken": tok} if tok else {})})
        pl = next((p["id"] for p in j.get("items", []) if p["snippet"]["title"] == name), None)
        tok = j.get("nextPageToken")
        if not tok:
            break
    if pl is None:
        pl = call("youtube", "POST", f"{B}/playlists", headers=h, params={"part": "snippet,status"},
                  json={"snippet": {"title": name, "description": desc, "defaultLanguage": "hi"},
                        "status": {"privacyStatus": "public"}})["id"]
    call("youtube", "POST", f"{B}/playlistItems", headers=h, params={"part": "snippet"},
         json={"snippet": {"playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": vid}}})


for d in sorted(glob.glob("incoming/*/")):
    m = json.load(open(d + "meta.json", encoding="utf-8"))
    rid = m["id"]
    sf = f"state/{rid}.json"
    st = json.load(open(sf, encoding="utf-8")) if os.path.exists(sf) else {}
    vurl = f"https://raw.githubusercontent.com/{REPO}/{E_['SHA']}/incoming/{rid}/video.mp4"
    log = []
    call = make_call(log)
    plats = m.get("platforms", ["instagram", "threads", "facebook", "youtube"])  # e.g. ["instagram"] for an IG-trial-only test
    for name, fn in (("instagram", ig), ("threads", threads), ("facebook", fb), ("youtube", youtube)):
        if name not in plats or st.get(name, {}).get("ok"):
            continue
        try:
            src = d + "video.mp4" if name == "youtube" else vurl  # YouTube takes the file bytes, not a URL
            st[name] = {"ok": True, "ref": fn(call, m, src), "at": datetime.datetime.now().isoformat()}
        except Exception as e:
            st[name] = {"ok": False, "error": str(e)[:800], "at": datetime.datetime.now().isoformat()}
        print(name, st[name]["ok"])
    json.dump(st, open(sf, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json.dump(log, open(f"publish_log/{rid}_{stamp}.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    if all(st.get(n, {}).get("ok") for n in plats):
        shutil.rmtree(d)  # every requested platform published: remove video and meta from the public repo
        print("cleaned", d)
