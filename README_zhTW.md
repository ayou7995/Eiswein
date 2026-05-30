# Eiswein

> English version: [`README.md`](./README.md).

Eiswein 是一個個人股市決策輔助工具。它幫你追蹤一份美股 watchlist、
每天計算 12 個技術指標和市場態勢指標，最後把結果整理成每支股票的
「買 / 持 / 望 / 減 / 出」訊號 + 整體市場態勢（進攻 / 正常 / 防守）。

你在自己的 laptop 上跑它。資料不會離開你的機器。它**不會自動下單**
—— 所有交易決策還是你自己做。

**啟發來源**：Heaton 的 Sherry trading system。**與 Heaton 或其 Patreon
無關**。

---

## 安裝前你需要

| 必要 | 為什麼 |
|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 用一個 container 跑整個 app |
| `git` | 用來 `git clone`，之後也用 `make update` 更新 |
| Python ≥ 3.10 + `venv` | 只在安裝時用一次 —— `make install` 會自己建一個 `.venv-bootstrap/`，**不會碰你系統 Python** |

| 選用（安裝時會問你） | 為什麼 |
|---|---|
| 免費 [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html) | 用來算 macro 指標（CPI、FOMC、yield 曲線、VIX） |
| Gmail + [App Password](https://myaccount.google.com/apppasswords) | 寄每日的催化劑摘要 email |
| Schwab 開發者帳號 ([dev portal](https://developer.schwab.com/)) | 用 app 內「連接 Schwab」卡片讀你的券商持倉 |
| [`mkcert`](https://github.com/FiloSottile/mkcert) | 只有啟用 Schwab 才需要 —— 產生本機可信的 HTTPS 證書 |

每一個「選用」都可以跳過 —— app 仍然用免費的 Yahoo Finance 資料
正常跑純決策輔助模式。

---

## 5 分鐘安裝

```sh
git clone <這個 repo 的 url> eiswein
cd eiswein

# 互動式 wizard。第一次跑會在 .venv-bootstrap/ 裡裝 bcrypt + zxcvbn，
# 再帶你走完 admin 帳密 + FRED / SMTP / Schwab 三段（都可跳過）。
# 你的系統 Python 完全不會被動到。
make install

# 在背景啟動
make start

# 用瀏覽器打開
open http://localhost:8080
```

第一次 boot 需要 ~30 秒 build Docker image。之後 `make start` 都會
是瞬間完成。

用 `make install` 時設定的帳密登入。從左側 sidebar 用 `+` 按鈕加幾支
股票。等到隔天 06:30 ET（或下次啟動 app 時，見下方「自動排程」）
第一次的訊號就會算出來。

---

## 日常操作

| 指令 | 做什麼 |
|---|---|
| `make start` | 在背景啟動 stack。可以重複跑沒問題。 |
| `make stop` | 停掉 container。你的資料會保留。 |
| `make logs` | 在 terminal 看 backend logs。`Ctrl+C` 離開。 |
| `make update` | `git pull` + rebuild image + 重啟。要拿新版本就用這個。 |
| `make uninstall` | **會刪資料**。把 container、image、`.env`、`data/`、`certs/` 都清掉。原始碼會留。 |
| `make help` | 列出所有可用指令。 |

`make dev` 是給你自己改 code 時用的 —— foreground 跑 Vite + uvicorn
帶 hot reload。一般使用者不需要碰。

---

## 自動排程

只要 container 還在跑，內建 scheduler 會自動觸發 4 個 job，不需要
另外設外部 cron。時間都用美東時間（自動處理日光節約）：

| Job | 時間 | 做什麼 |
|---|---|---|
| `daily_update` | 每天 **06:30 ET** | 抓新價格、重算 12 個指標、更新催化劑日曆、選用地寄送 digest email |
| `backup` | 每天 07:00 ET | 把 `data/eiswein.db` 備份一份到 `data/backups/` |
| `token_reminder` | 每天 09:15 ET | 如果你連了 Schwab，當 refresh token 快過期會 email 提醒 |
| `vacuum` | 每月第一個週日 03:00 ET | 對 SQLite 檔做 `VACUUM` 釋放空間 |

如果排程時間時你的 laptop 在睡眠，那一次會 miss **但**下次 container
啟動時 `daily_update` 會自動補跑 —— 它的 gap-detection 邏輯會把缺
的交易日補回來。所以實務上：只要你每隔幾天讓 laptop 上線一次，
指標就會跟上。

---

## 進階設定

### 連 Schwab（讀取持倉）

1. 到 <https://developer.schwab.com/> 註冊一個 Schwab developer app。
2. 選 **Individual Developer**。
3. 把 **Callback URL** 設成 **完全一致**：
   `https://localhost:8080/api/v1/broker/schwab/callback`
4. 等審核通過（Schwab 通常 1–3 個工作天）。
5. 重新跑 `make install`，Schwab 那一題回 yes。wizard 會自動跑
   `mkcert` 在 `certs/` 下產 local HTTPS 證書。
6. 再 `make start` —— app 就會用 HTTPS 跑。打開
   `https://localhost:8080`，到「設定 → 連接 Schwab」按下去。

詳細步驟（含截圖位置）見
[`docs/SETUP_GUIDE_zhTW.md`](./docs/SETUP_GUIDE_zhTW.md)。

### 開 email 提醒

跑 `make install`（可以重跑），在 SMTP 那一題選：

- **Gmail** —— 需要 [App Password](https://myaccount.google.com/apppasswords)
  （Gmail 帳號要先開 2FA）。會真的寄到收件人信箱。
- **Mailpit** —— 不會真的寄，mail 會收集到一個 local 網頁
  <http://localhost:8025>。適合預覽 email 樣式。要用的話 stack
  要這樣啟動：`COMPOSE_PROFILES=email make start`。

### FRED API key

免費、約 30 秒：<https://fred.stlouisfed.org/docs/api/api_key.html>。
沒設的話，macro 指標（CPI、yield 曲線、Fed funds rate、VIX）會
顯示「資料無法取得」徽章。

---

## 故障排解

**瀏覽器顯示「Not Secure」警告。** 預期行為 —— 本機自簽證書都會這樣。
按「進階 → 繼續」。連線本身是 HTTPS，只是 Chrome 不信任 mkcert root
（除非 bootstrap script 跑了 `mkcert -install`，產 Schwab 證書時會
自動跑）。

**`make start` 失敗說 port 8080 被佔用。** 別的 process 在用 8080。
要嘛停掉那個 process，要嘛改 `docker-compose.yml` 用別的 host port。

**`make start` 失敗說「Cannot connect to Docker daemon」。** Docker
Desktop 沒在跑。從 Applications 啟動它。

**登入表單拒絕你的密碼。** `make install` 時你設過一組帳密，密碼
bcrypt-hash 後存在 `.env`。如果忘了，跑 `make uninstall && make install`
（這會連同資料庫一起清掉），或直接用 `scripts/set_password.py` 改
`.env` 裡的 `ADMIN_PASSWORD_HASH`。

**`make update` 說「Your branch is behind」但什麼都沒變。** 可能你
本機有改過 code。先 `git status` 看一下。

**Schwab「連接」按鈕回 401。** 詳見
[`docs/SETUP_GUIDE_zhTW.md`](./docs/SETUP_GUIDE_zhTW.md) —— 通常是
host 對不上（`localhost` vs `127.0.0.1`）；Vite dev 有寫一個 redirect
處理 `make dev` 那邊，production container 因為單一 origin
（`localhost:8080`）所以不會遇到。

---

## 隱私

- **所有東西都在你的 laptop 上。** App 會跟 Yahoo Finance（抓價格）
  講話，選用的還會跟 FRED（macro 資料）、Gmail（寄 email）、Schwab
  （讀持倉）講話。沒有 analytics、沒有 telemetry、沒有 cloud sync。
- SQLite 資料庫、指標 cache、TLS 證書都放在 `./data/` 跟 `./certs/`。
  兩個都不會進 git。
- `.env` 用 plaintext 存你的 secrets（`chmod 600`）。當成其他 secret
  檔一樣對待。

---

## 開發者參考

如果你想讀或改 code，架構跟設計決策在：

- [`CLAUDE.md`](./CLAUDE.md) —— 專案結構、不變量、慣例
- [`docs/IMPLEMENTATION_PLAN.md`](./docs/IMPLEMENTATION_PLAN.md) —— milestone roadmap
- [`docs/STAFF_REVIEW_DECISIONS.md`](./docs/STAFF_REVIEW_DECISIONS.md) —— 鎖定的技術決策
- [`docs/DESIGN_DECISIONS.md`](./docs/DESIGN_DECISIONS.md) —— 原始 scoping
- [`AGENTS.md`](./AGENTS.md) —— distribution 變動時的維護契約

日常開發用 `make dev`（foreground Vite + uvicorn 帶 hot reload）。
測試在 `backend/tests/`（pytest）跟 `frontend/src/**/*.test.tsx`
（vitest）。`make test` 跑 backend；`cd frontend && npm test` 跑前端。

---

## 授權

見 [`NOTICE.md`](./NOTICE.md)。私有 repository，僅授權給受邀請的
collaborator。
