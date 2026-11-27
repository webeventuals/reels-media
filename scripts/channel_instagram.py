"""Instagram channel path: post due entries in channels/instagram/ to the Web Eventuals Instagram account.
Independent of incoming/, incoming_posts/, post.py, post_posts.py and every other channel.

Entry = channels/instagram/<id>.json plus its media files in the same folder. The shape is picked from the fields:
  "video"            -> reel (MP4); "cover" optional JPG shown in the grid
  "images" 2 to 10   -> carousel (JPG)
  "images" 1         -> single picture post (JPG)
Every entry needs: id (= file name), publish_after_ist (ISO with +05:30), caption.
Optional: "ig_trial": "MANUAL" or "SS_PERFORMANCE" (reels only: trial reel shown to non-followers first),
          "ai_label": true/false (reels only, default true: AI voice disclosure).
An entry posts once: after posting, the run writes posted_url and posted_at into it.
Every API call's raw response goes to publish_log/ig_<id>_<ts>.json (tokens never logged). Media is never deleted.

  python scripts/channel_instagram.py --check   validate only (run before every push; no network, no secrets)
  python scripts/channel_instagram.py           post every due, unposted entry (CI)"""
import datetime, glob, json, os, re, subprocess, sys, time

DIR = "channels/instagram"
REPO = "webeventuals/reels-media"  # public: Instagram fetches media from raw.githubusercontent.com
B = "https://graph.instagram.com/v21.0"


def path(name):
    n = (name or "").replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    if n.startswith(DIR + "/"):
        n = n[len(DIR) + 1:]
    return os.path.join(DIR, n)


def kind(m):
    if m.get("video"):
        return "reel"
    n = len(m.get("images") or [])
    return "carousel" if n >= 2 else "image" if n == 1 else None


def problems(jf):
    try:
        m = json.load(open(jf, encoding="utf-8"))
    except Exception as e:
        return [f"invalid JSON: {e}"], {}
    out = []
    if not m.get("id"):
        out.append("missing 'id'")
    elif os.path.splitext(os.path.basename(jf))[0] != m["id"]:
        out.append(f"id {m['id']!r} does not match file name")
    try:
        if datetime.datetime.fromisoformat(m.get("publish_after_ist", "")).tzinfo is None:
            out.append("publish_after_ist has no timezone (+05:30)")
    except ValueError:
        out.append(f"bad publish_after_ist {m.get('publish_after_ist')!r}")
    cap = m.get("caption") or ""
    if not cap.strip():
        out.append("missing 'caption'")
    if len(cap) > 2200:
        out.append(f"caption {len(cap)} chars, Instagram max 2200")
    if cap.count("#") > 30:
        out.append("more than 30 hashtags")
    if m.get("video") and m.get("images"):
        out.append("use 'video' or 'images', not both")
    if kind(m) is None:
        out.append("needs 'video' (reel) or 'images' (1 = picture post, 2 to 10 = carousel)")
    if len(m.get("images") or []) > 10:
        out.append("max 10 images")
    if m.get("ig_trial") not in (None, "MANUAL", "SS_PERFORMANCE"):
        out.append("ig_trial must be MANUAL or SS_PERFORMANCE")
    if m.get("ig_trial") and not m.get("video"):
        out.append("ig_trial is for reels only")
    if m.get("video") and not m["video"].lower().endswith(".mp4"):
        out.append("video must be .mp4")
    for f in [m.get("cover")] + list(m.get("images") or []):
        if f and not f.lower().endswith((".jpg", ".jpeg")):
            out.append(f"{f}: Instagram takes JPEG only")
    for f in [m.get("video"), m.get("cover")] + list(m.get("images") or []):
        if f and not os.path.isfile(path(f)):
            out.append(f"file not found: {path(f)}")
    if re.search("[–—]", cap):
        out.append("em or en dash in caption")
    return out, m


def main():
    check = "--check" in sys.argv
    now = datetime.datetime.now(datetime.timezone.utc)
    due, bad = [], False
    for jf in sorted(glob.glob(f"{DIR}/*.json")):
        p, m = problems(jf)
        if m.get("posted_url"):
            continue
        if p:
            print("PROBLEM", jf, "; ".join(p))
            bad = True
            continue
        when = datetime.datetime.fromisoformat(m["publish_after_ist"])
        if check:
            print("OK", m["id"], kind(m), "posts at first run after", when.isoformat())
        elif when <= now:
            due.append((jf, m))
        else:
            print(m["id"], "not due until", when.isoformat())
    if check or not due:
        if not check:
            print("nothing due for Instagram")
        sys.exit(1 if bad else 0)

    import requests
    t, u = os.environ["IG_ACCESS_TOKEN"], os.environ["IG_USER_ID"]
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    url = lambda f: f"https://raw.githubusercontent.com/{REPO}/{sha}/{path(f).replace(os.sep, '/')}"
    H = {"Authorization": f"Bearer {t}"}
    os.makedirs("publish_log", exist_ok=True)

    for jf, m in due:  # one bad entry must not block the others
        log = []

        def call(method, endpoint, **kw):
            r = requests.request(method, endpoint, timeout=120, **kw)
            try:
                j = r.json()
            except Exception:
                j = {"raw": r.text[:500]}
            log.append({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "method": method,
                        "url": endpoint.split("?")[0], "status": r.status_code, "response": j})
            if r.status_code >= 400:
                raise RuntimeError(f"{endpoint.split('?')[0]} {r.status_code} {j}")
            return j

        def ready(c):  # a container must be FINISHED before it is used or published
            for _ in range(30):
                time.sleep(10)
                s = call("GET", f"{B}/{c}", headers=H, params={"fields": "status_code,status"})
                if s.get("status_code") == "FINISHED":
                    return
                if s.get("status_code") in ("ERROR", "EXPIRED"):
                    raise RuntimeError(f"container {c} {s}")
            raise RuntimeError(f"container {c} timeout")

        try:
            k = kind(m)
            if k == "reel":
                body = {"media_type": "REELS", "video_url": url(m["video"]), "caption": m["caption"],
                        "is_ai_generated": m.get("ai_label", True)}
                if m.get("cover"):
                    body["cover_url"] = url(m["cover"])
                if m.get("ig_trial"):
                    body["trial_params"] = {"graduation_strategy": m["ig_trial"]}
                c = call("POST", f"{B}/{u}/media", headers=H, json=body)["id"]
            elif k == "image":
                c = call("POST", f"{B}/{u}/media", headers=H, json={"image_url": url(m["images"][0]), "caption": m["caption"]})["id"]
            else:
                kids = [call("POST", f"{B}/{u}/media", headers=H, json={"image_url": url(x), "is_carousel_item": True})["id"]
                        for x in m["images"]]
                for x in kids:
                    ready(x)
                c = call("POST", f"{B}/{u}/media", headers=H,
                         json={"media_type": "CAROUSEL", "children": ",".join(kids), "caption": m["caption"]})["id"]
            ready(c)
            pid = call("POST", f"{B}/{u}/media_publish", headers=H, data={"creation_id": c})["id"]
            m["posted_url"] = call("GET", f"{B}/{pid}", headers=H, params={"fields": "permalink"}).get("permalink", pid)
            m["posted_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            json.dump(m, open(jf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print("posted", m["id"], k, m["posted_url"])
        except Exception as e:
            print("FAILED", m["id"], type(e).__name__, str(e)[:400])
            bad = True
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json.dump(log, open(f"publish_log/ig_{m['id']}_{stamp}.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
