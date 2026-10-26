"""Post each incoming_posts/<id>/ image carousel to IG, Threads, FB. Same state/log/cleanup contract as post.py:
per-platform state in state/<id>.json makes reruns idempotent; every raw response goes to publish_log/<id>_<ts>.json."""
import os, glob, json, datetime, shutil, importlib.util

# reuse post.py's logged call() and poll() without running its reel loop (no incoming/ dirs exist when only posts are staged)
spec = importlib.util.spec_from_file_location("p", os.path.join(os.path.dirname(__file__), "post.py"))
src = open(spec.origin, encoding="utf-8").read().split("\nfor d in sorted(glob.glob(\"incoming/*/\")):")[0]
P = {}
exec(compile(src, spec.origin, "exec"), P)
make_call, poll, E_, REPO = P["make_call"], P["poll"], P["E_"], P["REPO"]


def urls(m):
    return [f"https://raw.githubusercontent.com/{REPO}/{E_['SHA']}/incoming_posts/{m['id']}/{f}" for f in m["images"]]


def ig(call, m):
    B = "https://graph.instagram.com/v21.0"
    t, u = E_["IG_ACCESS_TOKEN"], E_["IG_USER_ID"]
    h = {"Authorization": f"Bearer {t}"}
    kids = [call("instagram", "POST", f"{B}/{u}/media", headers=h,
                 json={"image_url": x, "is_carousel_item": True})["id"] for x in urls(m)]
    c = call("instagram", "POST", f"{B}/{u}/media", headers=h,
             json={"media_type": "CAROUSEL", "children": ",".join(kids), "caption": m["instagram"]})["id"]
    poll(call, "instagram", f"{B}/{c}", {"fields": "status_code,status", "access_token": t},
         lambda j: j.get("status_code") == "FINISHED", ('"ERROR"', '"EXPIRED"'), wait=5)
    p = call("instagram", "POST", f"{B}/{u}/media_publish", data={"creation_id": c, "access_token": t})["id"]
    return call("instagram", "GET", f"{B}/{p}", params={"fields": "permalink", "access_token": t}).get("permalink", p)


def threads(call, m):
    B = "https://graph.threads.net/v1.0"
    t, u = E_["THREADS_ACCESS_TOKEN"], E_["THREADS_ID"]
    kids = [call("threads", "POST", f"{B}/{u}/threads",
                 data={"media_type": "IMAGE", "image_url": x, "is_carousel_item": "true", "access_token": t})["id"]
            for x in urls(m)]
    for k in kids:  # carousel create rejects children still processing
        poll(call, "threads", f"{B}/{k}", {"fields": "status,error_message", "access_token": t},
             lambda j: j.get("status") == "FINISHED", ('"ERROR"', '"EXPIRED"'), wait=3)
    c = call("threads", "POST", f"{B}/{u}/threads",
             data={"media_type": "CAROUSEL", "children": ",".join(kids), "text": m["threads"], "access_token": t})["id"]
    poll(call, "threads", f"{B}/{c}", {"fields": "status,error_message", "access_token": t},
         lambda j: j.get("status") == "FINISHED", ('"ERROR"', '"EXPIRED"'), wait=5)
    p = call("threads", "POST", f"{B}/{u}/threads_publish", data={"creation_id": c, "access_token": t})["id"]
    return call("threads", "GET", f"{B}/{p}", params={"fields": "permalink", "access_token": t}).get("permalink", p)


def fb(call, m):
    B = "https://graph.facebook.com/v21.0"
    t, pid = E_["FB_PAGE_ACCESS_TOKEN"], E_["FB_PAGE_ID"]
    ids = [call("facebook", "POST", f"{B}/{pid}/photos", data={"url": x, "published": "false", "access_token": t})["id"]
           for x in urls(m)]
    data = {"message": m["facebook"], "access_token": t}
    data.update({f"attached_media[{i}]": json.dumps({"media_fbid": x}) for i, x in enumerate(ids)})
    return call("facebook", "POST", f"{B}/{pid}/feed", data=data)["id"]


for d in sorted(glob.glob("incoming_posts/*/")):
    m = json.load(open(d + "meta.json", encoding="utf-8"))
    rid = m["id"]
    sf = f"state/{rid}.json"
    st = json.load(open(sf, encoding="utf-8")) if os.path.exists(sf) else {}
    log = []
    call = make_call(log)
    plats = [p for p in m.get("platforms", ["instagram", "threads", "facebook"]) if m.get(p)]  # a platform with no caption is skipped
    for name, fn in (("instagram", ig), ("threads", threads), ("facebook", fb)):
        if name not in plats or st.get(name, {}).get("ok"):
            continue
        try:
            st[name] = {"ok": True, "ref": fn(call, m), "at": datetime.datetime.now().isoformat()}
        except Exception as e:
            st[name] = {"ok": False, "error": str(e)[:800], "at": datetime.datetime.now().isoformat()}
        print(name, st[name]["ok"])
    json.dump(st, open(sf, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json.dump(log, open(f"publish_log/{rid}_{stamp}.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    if all(st.get(n, {}).get("ok") for n in plats):
        shutil.rmtree(d)
        print("cleaned", d)
