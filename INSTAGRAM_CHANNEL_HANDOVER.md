# Instagram channel: how to upload and schedule

Your job: post Web Eventuals reels, carousels and picture posts to the Web Eventuals Instagram account.

## Where
- Repo: github.com/webeventuals/reels-media (branch main). It is PUBLIC: Instagram downloads the media from raw.githubusercontent.com, so never put anything private in it.
- Your folder: `channels/instagram/` (the only folder you use). Never touch `incoming/`, `incoming_posts/`, `gbp/`, `scripts/post.py` or `scripts/post_posts.py`. Those belong to the old engine.
- Poster: `scripts/channel_instagram.py`, run by workflow `channel-instagram` every hour at about :07 (GitHub can start it up to ~30 min late).
- The account is fixed by the repo secrets `IG_USER_ID` and `IG_ACCESS_TOKEN`. Never change them.
- Local working copy: `D:\Antigravity Folder\Web Eventuals Videos\_igchannel`.

## One entry = one JSON + its media files, all inside channels/instagram/
File name = `<id>.json`, and `id` inside must match. Media file names are relative to the folder.

Reel (MP4, 9:16, cover JPG recommended):
```json
{"id": "ig_2026_12_02_udhaar", "publish_after_ist": "2026-12-02T11:00:00+05:30",
 "caption": "Caption here. Line 1 = the research search term.",
 "video": "ig_2026_12_02_udhaar.mp4", "cover": "ig_2026_12_02_udhaar.jpg",
 "ig_trial": "SS_PERFORMANCE", "ai_label": true}
```
- `ig_trial` (optional, reels only): `SS_PERFORMANCE` = trial reel shown to non-followers, which Instagram moves to followers if it performs well. `MANUAL` = you decide in the app. Leave it out for a normal reel.
- `ai_label` defaults to true (AI voice disclosure). Leave it true for Sarvam-voiced reels.

Carousel (2 to 10 JPGs, 4:5 1080x1350 best, slides in list order):
```json
{"id": "ig_2026_12_03_maps", "publish_after_ist": "2026-12-03T18:00:00+05:30",
 "caption": "Caption here.",
 "images": ["ig_2026_12_03_maps_1.jpg", "ig_2026_12_03_maps_2.jpg", "ig_2026_12_03_maps_3.jpg"]}
```
Picture post (1 JPG):
```json
{"id": "ig_2026_12_04_gst", "publish_after_ist": "2026-12-04T18:00:00+05:30",
 "caption": "Caption here.", "images": ["ig_2026_12_04_gst.jpg"]}
```
Rules the checker enforces: id = file name; `publish_after_ist` with `+05:30`; caption present, max 2200 chars and 30 hashtags; JPEG images and cover only (no PNG); `.mp4` video; max 10 images; every media file exists; `ig_trial` only MANUAL or SS_PERFORMANCE and only on reels; no em or en dashes.

## Schedule and upload
1. Put the JSON and media in `channels/instagram/`.
2. Run `python scripts/channel_instagram.py --check`. It must print OK for every entry and exit 0. Fix any PROBLEM line.
3. Probe each reel before pushing: `ffprobe` must show audio 48000 Hz, 2 channels. If not, stop and fix it.
4. `git add channels/instagram` then commit and `git pull --rebase` then `git push`.
5. The first hourly run after `publish_after_ist` posts it. To post a due entry now: `gh workflow run channel-instagram -R webeventuals/reels-media`.
6. Push a reel only after Sam says "push" in chat.

## Verify
- `gh run list -w channel-instagram -R webeventuals/reels-media -L 3` shows green runs.
- After posting, the run commits `posted_url` (the Instagram permalink) and `posted_at` into the entry's JSON. Pull to see it. An entry with `posted_url` never posts again.
- The raw response of every API call is saved in `publish_log/ig_<id>_<time>.json`.
- A failed entry prints `FAILED <id> ...` in the run log and the run goes red. Other entries still post. Fix it, push, and it retries next hour.
- To cancel a scheduled entry before it posts, push a later `publish_after_ist`. Do not delete files.
- Media stays in the repo after posting. Nothing is deleted.

## Token expiry (important)
`IG_ACCESS_TOKEN` lasts 60 days and was last set on 19 Oct 2026, so it expires around 18 Dec 2026. There is no refresh workflow on the repo right now. Before about 15 Dec, ask Sam to refresh it, or to approve setting up a weekly refresh. The weekly refresh needs a `SECRETS_PAT` secret: a fine-grained token, reels-media only, Secrets read/write. When the token has expired, every run fails with a 190 error.

## Exact-time trigger (Cloudflare)
GitHub's hourly run can be up to ~30 min late. For on-time posts, the Cloudflare worker `instagram-trigger` starts the workflow at fixed times. Files: `D:\Antigravity Folder\Web Eventuals Videos\cloudflare_trigger_instagram\` (worker.js, wrangler.toml). It is NOT deployed yet, and its crons are empty.
1. Set the times in `wrangler.toml` `crons` (UTC; IST = UTC + 5:30). Make each one 5 minutes after the `publish_after_ist` times you schedule. Example: posts at 11:00 IST, cron `"35 5 * * *"`. Max 5 crons per worker.
2. From that folder: Wrangler is already logged in to the webeventuals Cloudflare account. On first setup only, run `npx wrangler@3 secret put GH_TOKEN`. Sam pastes a fine-grained GitHub token for reels-media only, with Actions read/write. The LinkedIn worker's token is for explainer_reels and will not work here. Then run `npx wrangler@3 deploy`.
3. After any cron change, run `npx wrangler@3 deploy` again.
4. Check: in the Cloudflare dashboard, go to Workers, then instagram-trigger, then Logs, and look for `dispatch ... 204`. Then `gh run list -w channel-instagram -R webeventuals/reels-media -L 1` shows a workflow_dispatch run.
The hourly GitHub run stays on as backup. Both firing is safe, because a posted entry is never posted again.

## Caption style
Hinglish is fine for reel captions. Line 1 = the exact research search term. Carousels are English only, with zero Hinglish words. No em or en dashes anywhere.
