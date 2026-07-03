# Robinhood Trading Bridge

A local, guardrailed web app for connecting to Robinhood Crypto, reviewing trade candidates, previewing orders, and placing orders only after explicit safeguards pass.

This app is intentionally conservative:

- Paper mode is the default.
- Live trading is disabled unless `ROBINHOOD_ENABLE_LIVE_TRADING=true`.
- Orders are blocked unless the product is allowlisted and size limits pass.
- Manual live execution requires a typed confirmation phrase.
- Auto execution is disabled unless `AUTO_EXECUTE_ENABLED=true`.
- API secrets stay in environment variables or a local `.env` file.
- Challenge Radar pulls Robinhood crypto and stock candle data for chart context and configurable RSS/search feeds for current news.

This is not financial advice. The app can help evaluate and route a trade, but it should not be treated as a reliable autonomous money manager.

## Setup

1. Create a virtual environment.

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies.

   ```powershell
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and add your Robinhood Crypto API key values.

   ```powershell
   Copy-Item .env.example .env
   ```

4. Start the app.

   ```powershell
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

5. Open http://127.0.0.1:8000.

To test from another device on your home Wi-Fi, start the app on all network interfaces:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open `http://YOUR_PC_WIFI_IP:8000` on the iPhone. That address will not work on LTE because it is private to your home network.

## Robinhood API Key

Use Robinhood Crypto API credentials with the least privilege you need. Put the API key and private key in `.env`; do not paste secrets into the browser.

## Live Trading Checklist

Before enabling live orders:

1. Keep `ROBINHOOD_MODE=paper` until account reads and paper previews work.
2. Set a small `MAX_ORDER_QUOTE_USD`, such as `10`.
3. Set `DAILY_QUOTE_LIMIT_USD` to the most you are willing to spend in a day.
4. Keep `ALLOWED_PRODUCTS` narrow, such as `BTC-USD,ETH-USD,AAPL,NVDA`.
5. Set `ROBINHOOD_ENABLE_LIVE_TRADING=true` only after reviewing the above.

## Challenge Radar

The Challenge Radar panel is a proposal engine for the $10 to $1000 challenge. It scores chart structure from Robinhood crypto and stock candles, then overlays sentiment and news-cycle risk. If the news notes box is blank, it fetches recent RSS and Google News search headlines from `NEWS_FEEDS` plus asset-specific searches, then infers a rough news bias. A proposal still has to pass the normal guardrails and typed confirmation flow before any manual order can execute.

Default feeds are CoinDesk, Cointelegraph, and Decrypt. You can replace or add feeds in `.env` with `NEWS_FEEDS`.

Use **Auto Scan** to let the app discover Robinhood USD crypto markets, add configured stock symbols from `SCAN_STOCK_SYMBOLS`, pull charts, fetch news, rank the setups, and load the best allowed trade idea into the proposal box automatically. The scanner scores both buy pressure and sell pressure for every market. Sell signals are shown even without inventory, but sell orders are created only when the app can detect or is given base-asset inventory. The scanner can research up to `SCAN_MAX_PRODUCTS`, but execution is still constrained by `ALLOWED_PRODUCTS`, size caps, preview, and typed confirmation.

Live order execution in this build is for Robinhood Crypto only. Stock scans and stock proposals work in paper mode; live stock execution is blocked until a legitimate equities trading API is added.

Use **Auto Execute 80+** only after explicitly opting in with `AUTO_EXECUTE_ENABLED=true`. Auto execution scans first, refuses anything below `AUTO_EXECUTE_MIN_SCORE` (minimum 80), runs the normal proposal guardrails, previews the order, and then executes. Live auto execution also requires `ROBINHOOD_MODE=live` and `ROBINHOOD_ENABLE_LIVE_TRADING=true`.

## Using It On LTE

LTE needs a public HTTPS backend. The local addresses `127.0.0.1` and `192.168...` only work on this computer or your home Wi-Fi.

The repo includes `Dockerfile`, `.dockerignore`, and `render.yaml` so you can deploy the backend as a web service. One straightforward path is:

1. Push this repo to GitHub.
2. Create a Render web service from the GitHub repo.
3. Let Render use `render.yaml`.
4. Add any secret values in the host dashboard, not in the repo:
   `ROBINHOOD_API_KEY`, `ROBINHOOD_API_SECRET`, and any limits you want to override.
5. Keep `ROBINHOOD_MODE=paper`, `ROBINHOOD_ENABLE_LIVE_TRADING=false`, and `AUTO_EXECUTE_ENABLED=false` until you have verified the hosted app.
6. Use the hosted `https://...` URL from Safari on iPhone, or set it as `BACKEND_URL` in Bitrise before building the TestFlight app.

Free hosting can sleep between visits. For anything time-sensitive, use an always-on paid backend and keep order limits very small while testing.

For a quick temporary LTE test without deploying, a tunnel such as Cloudflare Tunnel or ngrok can expose your local app over HTTPS, but your Windows computer must stay awake and running the server.

## References

- Robinhood Crypto Trading API docs: https://docs.robinhood.com/crypto/trading/
- Robinhood Crypto API base URL used by this app: https://trading.robinhood.com
- Robinhood market data candle endpoint used by this app: https://api.robinhood.com/marketdata/forex/historicals/

## iOS And TestFlight

The `ios/TradeRadar` folder contains a native SwiftUI/WKWebView wrapper for TestFlight. The root `bitrise.yml` can archive the app on Bitrise and, with Apple signing plus App Store Connect credentials configured, upload it for TestFlight.

For TestFlight beyond your own Wi-Fi, set `BACKEND_URL` in Bitrise to a hosted HTTPS backend. A local URL such as `http://192.168.86.248:8000` only works while your iPhone is on the same network as this computer.

Once the backend is hosted, put that hosted URL into Bitrise as `BACKEND_URL`, for example `https://trade-radar.onrender.com`. The iOS wrapper will load that public backend on Wi-Fi or LTE.
