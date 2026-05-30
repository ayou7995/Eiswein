# 詳細安裝指南

> English version: [`SETUP_GUIDE.md`](./SETUP_GUIDE.md).

每一個選用整合的詳細步驟。互動式 `make install` wizard 已經會問你
這些值 —— 這份文件解釋你**給的是什麼**、以及**怎麼拿到那些憑證**。

如果你從沒跑過 wizard，先看 [`README`](../README_zhTW.md) 的 quickstart。
這份指南假設你已經 clone 過 repo 並且至少跑過一次 `make install`。

---

## 1. FRED API key（macro 指標）

### 它解鎖什麼

Federal Reserve Economic Data API 提供 Eiswein 12 個指標中的其中
四個：

- **VIX** —— 波動率指數水準 + 趨勢
- **10Y–2Y yield spread** —— 衰退早期警訊
- **Fed Funds Rate** —— 當前利率 + 市場預期
- **DXY** —— 美元指數趨勢
- **CPI / PCE / PPI 公布日** —— 給催化劑日曆用

沒 key 的話，這些 tile 會顯示「資料無法取得」徽章。個股訊號
（price-vs-MA、RSI、MACD 等）會正常跑因為它們用 Yahoo Finance。

### 怎麼拿 key

1. 到
   <https://fred.stlouisfed.org/docs/api/api_key.html>。
2. 點 **My Account**（沒帳號就註冊一個 —— 免費，只要 email）。
3. 點 **Request API Key**。打一句描述（例如「personal market
   dashboard」）。key 會立刻發放。
4. 把 key 字串複製下來。
5. 要嘛重跑 `make install`（它會再問一次），要嘛直接編輯 `.env`：
   設 `FRED_API_KEY=…`，然後 `make stop && make start`。

### 怎麼驗證

`make start` 之後，打：

```
curl http://localhost:8080/api/v1/health
```

回應包含 `data_sources` —— 跑過一次指標查詢後，`fred` 應該顯示
`status: "ok"`。

---

## 2. SMTP email 提醒

有三個選項。wizard 會帶你走你選的那個。

### 選項 A —— Gmail App Password（會真的寄信）

**前置需求**：Gmail 帳號，並且開啟 2-Step Verification（兩步驟驗證）。

1. 到 <https://myaccount.google.com/security>。確認 **2-Step
   Verification** 是開的。沒開就開起來。
2. 到 <https://myaccount.google.com/apppasswords>。
3. 選 **Other (Custom name)** → 取名 "Eiswein" → **Generate**。
4. 複製那 16 字元的密碼（沒有空格）。
5. 跑 `make install`，SMTP 那一題選 Gmail：
   - Gmail address：你完整的 email
   - App Password：貼上那 16 字元
   - From address：預設用你的 email
   - Send to：你要收 digest 的地方（通常就是你自己 email）

催化劑 digest 每次 `daily_update` 成功跑完後寄一次。要關掉的話再
跑一次 `make install`，這次選「skip」。

### 選項 B —— Mailpit（只做本機預覽）

Mailpit 是一個小型 SMTP server，會把寄出的 mail 收到一個網頁
inbox。**它不會真的寄到任何地方**。如果你只想看催化劑 digest 長
什麼樣子、不想真的塞滿自己信箱，或開發用，就用這個。

1. `make install` → SMTP 題 → 選 **m**（Mailpit）。
2. 啟動 stack 時要帶 email profile：
   ```sh
   COMPOSE_PROFILES=email make start
   ```
3. 打開 <http://localhost:8025> —— Mailpit 的收件夾。

### 選項 C —— 跳過

SMTP 題選 **s**（skip），或者直接把 `.env` 裡的 `SMTP_HOST=` 留空。
催化劑 digest job 會 log `email_skipped: not_configured` 然後正常
繼續。不會有錯誤、不會丟資料 —— 就是不寄信。

---

## 3. Schwab 券商整合

這會解鎖 app 內的 **設定 → 連接 Schwab** 卡片，可以讓 app 透過
Schwab 官方 OAuth 流程讀你的券商持倉。**唯讀**。Eiswein 沒有任何
下單的 code path。

### Step 1 —— 註冊 developer app

1. 到 <https://developer.schwab.com/>，用 Schwab 券商帳號登入。
2. 點 **My Apps** → **Add a new app**。
3. App name：隨便（例如「Eiswein」）。Description：一句話。
4. **API products**：選 **Accounts and Trading Production**。
5. **Callback URL**：填**完全一致**：
   ```
   https://localhost:8080/api/v1/broker/schwab/callback
   ```
   結尾斜線、port、path —— 全部要一字不差，否則 OAuth callback
   會 silently 失敗。
6. Submit。app 會卡在 **Approved – Pending** 1–3 個工作天。批准後
   會收到 email，狀態變成 **Approved – Ready for Use**。

### Step 2 —— 裝本機證書

Schwab 規定 callback 要 HTTPS，連 `localhost` 也不例外。`mkcert`
產一對 self-signed 證書，Chrome 信任它（mkcert root 第一次安裝時
加進系統 trust store）。

```sh
# macOS
brew install mkcert nss

# Debian / Ubuntu
sudo apt install libnss3-tools
# 然後從 https://github.com/FiloSottile/mkcert/releases 裝 mkcert binary
```

### Step 3 —— 重跑 wizard

```sh
make install
```

Schwab 那一題回 **yes**。wizard 會：

- 跑 `mkcert -install`（把 mkcert root 加進系統 trust store ——
  一次性，之後瀏覽器都會信任 localhost 證書）。
- 跑 `mkcert localhost 127.0.0.1` 把證書對放到 `certs/`。
- 印出你應該跟 Schwab 註冊的 redirect URI（跟 Step 1.5 對一下）。
- 問你 **Client ID** 跟 **Client Secret** —— 從 Schwab developer
  app 的詳情頁複製。

### Step 4 —— 連接

```sh
make start
```

container 現在用 HTTPS 跑了。打開 <https://localhost:8080> 登入，
到 **設定 → 連接 Schwab**，按 **Connect**。會跳到 Schwab 登入頁 →
授權 → 回到 Eiswein，持倉資料就會跑出來。

### Schwab 故障排解

**「Cookie not present」/ 401 on /broker/schwab/start。** 你進 app
的 hostname 不是 `localhost:8080`。Schwab 註冊的 redirect URI 把
cookie 綁在那個 origin。要嘛去 Schwab 改 redirect URI（然後重跑
bootstrap 配合），要嘛永遠用 `https://localhost:8080`。

**Callback 出現「State mismatch」。** `/broker/schwab/start` 設的
CSRF nonce cookie 在來回路上消失了。幾乎都是因為流程中途清了
cookies、或者同時開兩個瀏覽器 tab 用不同 hostname。從**單一個 tab**
重新點 Connect。

**Bootstrap 時說 `mkcert: command not found`。** wizard 會印出你
作業系統的安裝指令。裝好 mkcert，再跑一次 `make install`。

**`certs/` 有證書對但 app 還是用 HTTP 起來。** entrypoint 預期檔名
**完全是** `certs/localhost-key.pem` + `certs/localhost.pem`。如果
mkcert 寫了不一樣的檔名，把它改名。

---

## 4. 瀏覽器證書警告（「Not Secure」）

不管你用 HTTPS（Schwab 路線）還是 HTTP（預設），Chrome / Safari
第一次都會在 URL bar 顯示警告。**這是預期行為**。

HTTP `localhost:8080` 的話，Chrome 把 `localhost` 當作「secure
context」處理 —— 警告純屬視覺，`Secure` cookies 仍然會帶。

HTTPS + 自簽 `mkcert` 的話，當 `mkcert -install` 把 root 加進系統
trust store 後 Chrome 就會信任。如果還是看到警告，按 **Advanced**
→ **Proceed to localhost (unsafe)** —— 連線本身沒問題，只是 Chrome
還沒在這個 profile 載入新 root。

---

## 5. 更新到新版

每當 maintainer 推新版時：

```sh
cd eiswein
make update
```

那等於 `git pull` + `docker compose build` + `docker compose up -d`。
Migration 會自動在 container 裡跑。你的 `data/eiswein.db` 因為
從 host 掛 volume 進來，所以不會掉。

如果新版引入**新的必填 env var**，maintainer 會在 commit / release
notes 提。再跑一次 `make install` 走完 prompt；wizard 不會在沒確認
的情況下覆蓋你既有的 `.env`。

---

## 6. 檔案在哪裡

```
eiswein/
├── .env                # 你的 secrets —— bootstrap 寫的，chmod 600。
├── data/               # SQLite DB + parquet cache + backups
├── certs/              # mkcert 證書對（只有 Schwab 啟用才有）
├── .venv-bootstrap/    # `make install` 用的私有 venv（bcrypt + zxcvbn）。
│                       # `make uninstall` 會刪掉它。
│                       # 你的系統 Python 完全不會被動到。
├── docker-compose.yml  # stack 定義
├── README.md / README_zhTW.md
├── docs/
│   └── SETUP_GUIDE.md / SETUP_GUIDE_zhTW.md     ← 你正在這
├── scripts/
│   ├── bootstrap.py    # make install 用的 wizard
│   ├── entrypoint.sh   # container 啟動 script
│   ├── uninstall.sh    # 清理 script（會刪資料）
│   └── set_password.py # 獨立的 bcrypt hash 生成工具
└── Makefile
```

---

## 7. 求助

這是個私有 repo、user 數很少。如果你撞到這份指南沒涵蓋的情況：

- 先掃 `make logs` —— 幾乎每個問題都會印一行結構化的 log 寫原因。
- 把那行 log 私訊給 maintainer（請把任何 Schwab token 先剪掉再分享）。
