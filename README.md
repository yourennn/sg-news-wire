# SG News Wire 新闻电报

A website that collects the latest Singapore news from **联合早报 (zaobao.com.sg)** and **8world** every 30 minutes. Users open one link, tick the stories they want, set how many paragraphs to keep, reorder them, and press **复制报告** to paste the report into Word, WeChat or email.

Nobody has to install or run anything. GitHub runs the scraper on a schedule and hosts the website for free.

```
GitHub (every 30 min)            GitHub Pages (website)
scraper.py ──► docs/news.json ──► docs/index.html ──► users open the link
```

---

## One-time setup (about 10 minutes)

### 1. Create the repository
1. Sign in to GitHub and click **+** (top right) → **New repository**.
2. Name it, e.g. `sg-news-wire`.
3. Choose **Public**. Free GitHub Pages needs a public repository.
4. Click **Create repository**.

### 2. Upload the files
1. On the new repository page, click **uploading an existing file**.
2. Open this `news-wire-site` folder on your computer and select **everything inside it**: `.github`, `docs`, `scraper.py`, `requirements.txt` and `README.md`. Drag them into the browser window. Drag the contents, not the `news-wire-site` folder itself.
3. Click **Commit changes**.
4. Check the file list on GitHub. You should see `.github/workflows/update-news.yml`. If the `.github` folder is missing (some browsers skip it):
   - Click **Add file → Create new file**.
   - Type the name `.github/workflows/update-news.yml`. The slashes create the folders.
   - Paste in the contents of that file from this folder, then click **Commit changes**.

### 3. Turn on the website
1. In the repository, go to **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.

### 4. Run it the first time
1. Open the **Actions** tab. If GitHub asks you to enable workflows, click the green button.
2. Click **Update news** on the left → **Run workflow** → **Run workflow**.
3. Wait 2–3 minutes until the run shows a green tick.
4. Your site is live at:

   **`https://<your-github-username>.github.io/sg-news-wire/`**

   Share this link with your users. It also appears in **Settings → Pages**.

From now on the news updates by itself every 30 minutes. Users can press **↻ 刷新** anytime, and the page shows a banner when newer news arrives.

---

## Checking that scraping works

Open **Actions → Update news →** the latest run **→ update → Scrape news**. A healthy log looks like:

```
[zaobao] 新加坡: 10 headlines
[zaobao] 国际: 10 headlines
[8world] 20 headlines
Saved 40 articles to docs/news.json
```

If one site fails, the website keeps showing that site's previous articles. It also displays a red notice saying that source failed to update.

**If a site blocks GitHub's servers**, the log shows errors such as `403 Forbidden` on every run. News sites sometimes refuse traffic from cloud servers. The fix is to run the scraper from a different machine (a small paid server, or a computer that stays on). Only the "where it runs" part changes; the website stays the same.

## Troubleshooting

| Problem | Fix |
|---|---|
| Run fails at "Save news.json" with a permission error | **Settings → Actions → General → Workflow permissions** → choose **Read and write permissions** → Save, then run again. |
| Run fails at "deploy" | Make sure **Settings → Pages → Source** is set to **GitHub Actions**. |
| News stopped updating after a long time | GitHub pauses scheduled jobs in repositories with no activity for 60 days. Open **Actions → Update news** and click **Enable workflow**. |
| Updates arrive later than every 30 min | Normal. GitHub's free scheduler can run a few minutes late at busy times. |

## Changing things

- **How often it updates:** in `.github/workflows/update-news.yml`, edit `cron: "*/30 * * * *"`. For example, `"*/15 * * * *"` means every 15 minutes, and `"0 * * * *"` means every hour.
- **How many stories or paragraphs:** in `scraper.py`, change `limit=10` in `fetch_zaobao` / `limit_per_tag=10` in `fetch_8world`, or `MAX_PARAGRAPHS`.
- **Section names for 8world:** in `scraper.py`, edit `TAG_LABELS`.
- **Testing on your own computer:** `pip install -r requirements.txt`, then `python scraper.py`, then open `docs/news.json`. To preview the site, run `python -m http.server -d docs` and open http://localhost:8000.

Titles and paragraphs are shown exactly as published by the source sites.
