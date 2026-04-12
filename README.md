# 日職台灣球員出賽監控 Agent (NPB Taiwan Player Monitor)

這是一個基於 Python 的自動化腳本，用來即時監控日本職棒 (NPB) Yahoo 體育的比賽轉播資訊。當指定的台灣球員（打者）即將上場打擊，或是指定的台灣投手登板時，會自動透過 **Linux 桌面通知** 或是 **Telegram 機器人** 發出提醒。讓你能準時打開轉播，不再錯過精彩時刻！

## 🎯 核心功能

- **⚾ 自動賽程查詢**：每天早上 9:00 自動前往 Yahoo 體育爬取目標球員所屬球隊（如「西武」、「楽天」等）的比賽時間。
- **👥 多球員同時監控**：支援同時監控多位台灣球員，不論是打者或投手。
- **⏰ 智慧休眠與倒數**：取得比賽時間後自動計算時差（日本至台灣時間），精準倒數並休眠直到開賽。
- **🔥 即時預警**：
  - **打者**：動態計算打席距離，當目標打者距離上場小於 3 個人次時，觸發通知！
  - **投手**：即時監控比賽進度，當目標投手登板時，立即發出提醒。
- **📱 跨平台桌面通知**：
  - 自動偵測系統 (Linux/macOS/Windows) 並推播通知。
  - macOS 預設使用 AppleScript 觸發系統通知。
  - Windows 環境透過 `plyer` 模組推播。
- **⚠️ 監控邏輯優化**：
  - 開賽前或比賽中若目標打者未先發上場（如可能代打），每 1 分鐘將自動重新查詢打序，隨時掌握上場時機。
  - 根據文字與計分板頁面，即時判斷現在是哪一局、誰進攻及場上投手。

## 🛠 安裝與環境需求

### 系統環境
- **Python 3.x**
- **作業系統**：
  - **Linux**：會呼叫原生的 `notify-send`（需確保系統裝有 `libnotify`）。
  - **macOS**：需透過 Homebrew 安裝 `terminal-notifier` (`brew install terminal-notifier`)。
  - **Windows**：需要安裝 `plyer` 以觸發 Action Center 通知。

### 安裝 Python 套件

請複製專案，並使用 `pip` 安裝 `requirements.txt` 內的依賴套件：

```bash
pip install -r requirements.txt
```

核心相依套件包含：
- `requests` (發送 HTTP 請求)
- `beautifulsoup4` (解析 HTML DOM)
- `schedule` (排程任務)
- `plyer` (提供 Windows 跨平台通知)

## ⚙️ 設定說明

打開 `agent_multi.py`，你可以在頂部的「設定區」修改你的專屬參數：

```python
# ================= 設定區 =================
# TARGET_PLAYERS 格式：每個球員包括 names (可能的名稱變體), team, role (Batter/Pitcher)
TARGET_PLAYERS = [
    {
        'names': ['林安可', '林 安可' ],
        'team': '西武', # 可將隊伍改成日本 Yahoo 上的隊伍簡稱
        'role': 'Batter'
    },
    {
        'names': ['宋家豪', '宋 家豪'],
        'team': '楽天',
        'role': 'Pitcher'
    },
    # ... 支援多個球員監控 ...
]

# 抽取 TEAM_NAMES 用於賽程搜尋
TEAM_NAMES = list(set(player['team'] for player in TARGET_PLAYERS))
# ==========================================
```

## 🚀 使用方式

確保環境與設定檔準備完畢後，直接執行主程式：

```bash
python agent_multi.py
```

- 程式啟動後會先執行一次當天的賽程檢查。
- 如果比賽尚未開打，終端機會出現「倒數時間」並進入休眠。
- 如果比賽已經打完或當天無賽程，將會進入休息狀態，隔天早上 9:00 再次喚醒檢查。

## 🚧 已知限制 / TODO

1. **目前投手監控部份尚未完成且不穩定**：計分板解析投手的欄位位置有可能因 Yahoo 頁面更動而抓取失敗，此部分持續優化中。
2. 若頁面結構改版（例如換行、class 名稱變更等），可能需進一步維護 XPath/CSS Selector 抓取邏輯。
