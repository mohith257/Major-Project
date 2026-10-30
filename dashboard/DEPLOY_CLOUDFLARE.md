# Deploy the dashboard to Cloudflare Pages (custom domain)

Goal: open your domain in any browser and run the whole demo — no local code,
no `npm run dev`. The page is a static SPA + a tiny server-side proxy that
holds the API key, so the key never ships to the browser.

## How it works

- `src/` builds to static files in `dist/`.
- `functions/api/[[path]].js` is a Cloudflare Pages Function. The browser calls
  same-origin `/api/rounds` and `/api/incidents`; the function forwards them to
  your AWS API Gateway with the `x-api-key` header read from a server-side env
  var. Only GET on those two endpoints is allowed — it can never POST.
- Because the browser only ever hits same-origin `/api/*`, there's no CORS to
  configure on API Gateway.

## One-time setup

### 1. Get the code to Cloudflare
Two options:

**A. Git (recommended — auto-deploys on every push):** push this repo to GitHub,
then in Cloudflare → Workers & Pages → Create → Pages → connect the repo.

**B. Direct upload (no Git):** from `dashboard/`:
```
npm run build
npx wrangler pages deploy dist --project-name fedgrid-dashboard
```
(Functions in `functions/` are uploaded automatically with `dist`.)

### 2. Build settings (Git option only)
In the Pages project → Settings → Builds & deployments:
- **Root directory:** `dashboard`
- **Build command:** `npm run build`
- **Build output directory:** `dist`

### 3. Environment variables (BOTH options) — this is the security-critical part
Pages project → Settings → Environment variables → add for **Production**
(and Preview if you use it):
- `API_BASE_URL` = your API Gateway base, e.g.
  `https://xxxxxxxx.execute-api.ap-south-1.amazonaws.com/prod`
- `API_KEY` = your API Gateway key

Do **not** name them `VITE_...` — that would inline them into the public bundle.
These are read only by the server-side function.

### 4. Custom domain
Pages project → Custom domains → Set up a domain → enter your domain (e.g.
`fedgrid.yourdomain.com`). If the domain's DNS is already on Cloudflare it wires
the CNAME and TLS automatically; otherwise follow the DNS record it shows you.

## Test locally before shipping (optional)
Runs the real proxy function on your machine:
```
cp .dev.vars.example .dev.vars   # fill in API_BASE_URL + API_KEY
npm run build
npx wrangler pages dev dist
```
Open the printed localhost URL. (`npm run dev` still works too, but that path
uses `.env.local` to hit AWS directly and does not exercise the proxy.)

## Redeploy after changes
- Git option: `git push` → auto-builds.
- Direct upload: `npm run build && npx wrangler pages deploy dist --project-name fedgrid-dashboard`.

## Security notes (read before the viva)
- The proxy is GET-only on `/rounds` + `/incidents`. Even though the key may
  grant more, the public site cannot POST or touch other routes through it.
- The AWS keys were already leaked via the EC2 `/tmp` http.server (see memory).
  Rotate them after the viva and update `API_KEY` here — one place to change.
- This is a read-only observer. The only way to make something happen on screen
  is to actually attack a node from a separate machine.
