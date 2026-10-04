# Automated Affiliate Site (free, self-owned)

Runs daily on GitHub Actions, publishes to GitHub Pages. Cost: $0 (domain optional).

## Setup (once)
1. Create a GitHub repo (branch `main`), push this folder to it.
2. Repo > Settings > Pages > Source: **GitHub Actions**.
3. Repo > Settings > Secrets and variables > Actions:
   - Secrets: `AFF_ID_1` (your affiliate ID/code), `AFF_ID_2` (optional)
   - Variables: `BASE_URL` = `https://<you>.github.io` (repo must be named `<you>.github.io`) or your custom domain
4. Edit `config.json` (site name, tagline, disclosure). Keep the disclosure.
5. Add products, either way:
   - By hand in `products.json` (use `{"affiliate_url": "...your link..."}`), or
   - Automatically: copy `feeds.example.json` to `feeds.json` and point it at the
     product feed/CSV from your affiliate network. Use `{AFF_ID_1}` in `link_template`.
6. Actions tab > autopilot > **Run workflow**. After that it runs every day by itself.

## Important: root URL required
Links are root-relative (`/go/...`), so the site must live at a domain root. Name the repo
`<you>.github.io` (then `BASE_URL=https://<you>.github.io`) or attach a custom domain.
A plain `github.io/<repo>` project URL will break links.

## Notes
- New feed products are capped per run (`max_new_per_run`) and de-duplicated.
- Click counts are not available on static hosting; see each network's dashboard.
  (`python affiliate.py serve` gives click tracking if you self-host on a VPS.)
- Add real pros/cons/notes to products. Thin pages rank poorly.
- Check each affiliate program's terms on automated pages.
