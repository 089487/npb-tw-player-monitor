import requests
from bs4 import BeautifulSoup
import time
import schedule
import re
import platform
import subprocess
from datetime import datetime, timedelta

# ================= 設定區 =================
TARGET_PLAYER = ['林安可', '林 安可', '林'] # 日本 Yahoo 可能顯示的名稱
TARGET_PITCHER = ['宋家豪', '宋 家豪', '張奕', '孫易磊'] # 目標投手名單
TEAM_NAME = '西武'
# ==========================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def send_desktop_notify(title, message):
    """跨平台發送桌面推播通知"""
    try:
        sys_name = platform.system()
        if sys_name == 'Linux':
            subprocess.run(['notify-send', title, message])
        elif sys_name == 'Darwin': # macOS
            subprocess.run(['osascript', '-e', f'display notification "{message}" with title "{title}"'])
        elif sys_name == 'Windows':
            # 需安裝 win10toast 或 plyer，這裡示範用 plyer
            from plyer import notification
            notification.notify(title=title, message=message, app_name='NPB Monitor')
        else:
            print(f"不支援的系統桌面通知 ({sys_name}): {title} - {message}")
    except Exception as e:
        print(f"桌面通知發送失敗: {e}")

def get_today_seibu_game():
    """爬取今日賽程，尋找西武獅的比賽 ID"""
    url = "https://baseball.yahoo.co.jp/npb/schedule/"
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 尋找所有比賽項目 (注意: 日本 Yahoo 的 class 偶爾會變動，需依網頁微調)
        games = soup.find_all('li', class_='bb-score__item')
        for game in games:
            if TEAM_NAME in game.text:
                a_tag = game.find('a')
                if a_tag and '/game/' in a_tag['href']:
                    # 擷取 Game ID (例如: 2026040401)
                    game_id = a_tag['href'].split('/game/')[1].replace('/top', '').replace('/', '').replace('index','')
                    # 抓取開賽時間 (Yahoo 可能用 time 代替 span，或者不同 class)
                    start_time_tag = game.find('time', class_='bb-score__status') or game.find('span', class_='bb-score__date')
                    start_time = start_time_tag.text.strip() if start_time_tag else "已開打"
                    return game_id, start_time
    except Exception as e:
        print(f"取得賽程發生錯誤: {e}")
    return None, None

def get_lin_batting_order(game_id):
    """取得林安可今日的先發打序"""
    url = f"https://baseball.yahoo.co.jp/npb/game/{game_id}/score"
    try:
        print("search url : ",url)
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 解析 soup 內的表格找到目標球員對應的棒次
        rows = soup.find_all('tr', class_='bb-splitsTable__row')
        for row in rows:
            name_cell = row.find('td', class_='bb-splitsTable__data--text')
            if name_cell and any(name in name_cell.text for name in TARGET_PLAYER):
                order_cell = row.find('td', class_='bb-splitsTable__data')
                if order_cell and order_cell.text.strip().isdigit():
                    order = int(order_cell.text.strip())
                    print(f"確認林安可在出賽名單中！擔任第 {order} 棒")
                    return order
                    
        print("未找到林安可的先發打序。")
    except Exception as e:
        print(f"取得打序錯誤: {e}")
    return None

def monitor_game_pitcher(soup, last_notified_pitcher):
    """監測場上投手是否為目標選手"""
    print("checking pitcher")
    current_pitcher_name = ""
    rslt_table = soup.find('table', id='gm_rslt')
    if rslt_table:
        tbody = rslt_table.find('tbody')
        print(tbody,'tbodu')
        if tbody:
            # 抓取表格內 td 包含球員名稱的連結，第 1 個是打者，第 2 個是投手
            player_tds = tbody.find_all('td', class_='bb-splitsTable__data--text')
            if len(player_tds) >= 2:
                current_pitcher_name = player_tds[1].text.strip()
                
    if current_pitcher_name:
        # 只有在更換投手時才重新檢查/推播一次
        if current_pitcher_name != last_notified_pitcher:
            print(f"[DEBUG] 當前登板投手: {current_pitcher_name}")
            if any(name in current_pitcher_name for name in TARGET_PITCHER):
                msg = f"⚾ 準備看電視！目標投手 {current_pitcher_name} 已經登板！"
                print(msg)
                send_desktop_notify("⚾ 台灣投手登板！", msg)
                
            last_notified_pitcher = current_pitcher_name
            
    return last_notified_pitcher

def monitor_game_batter(soup, html_text, lin_order, last_notified_distance):
    """監測打者棒次是否即將輪到目標選手"""
    batter_tag = soup.find('p', class_='bb-liveText__batter')
    if batter_tag:
        batter_text = batter_tag.text.strip()
        print(f"[DEBUG] 抓取到當前打者資訊: {batter_text}")
        
        # 判斷是否為自家球隊攻擊中
        is_our_team_batting = False 
        
        # 1. 優先從計分板判斷（尋找當前局數呈現黃色底或是帶有 '-' 的欄位）
        now_cell = soup.find('td', class_='bb-gameScoreTable__data--now')
        if now_cell:
            # 若有找到現在的局數，所在的 row 有包含我們球隊 (TEAM_NAME)，代表我們進攻
            row = now_cell.find_parent('tr')
            if row and TEAM_NAME in row.text:
                is_our_team_batting = True
        else:
            # 2. 備用邏輯：從文字轉播區塊的隊名或打者判斷
            team_tag = soup.find('p', class_='bb-liveText__team')
            if team_tag and TEAM_NAME in team_tag.text:
                is_our_team_batting = True
            elif TEAM_NAME in batter_text:
                is_our_team_batting = True
            else:
                # 當沒有明確標示時，退回預設 True 以免漏訊
                is_our_team_batting = True
                
        print('is our team or not',is_our_team_batting)
        if is_our_team_batting:
            match = re.search(r'(\d+)番', batter_text)
            if match:
                current_order = int(match.group(1))
                
                # 計算距離：(林安可的棒次 - 當前棒次) 如果是負的代表跨局，加 9 即可
                distance = (lin_order - current_order) % 9
                print(f"[DEBUG] 目前打者為第 {current_order} 棒，距離目標(第 {lin_order} 棒) 還有 {distance} 個人次")
                
                # 包含 0 表示他正在打擊 (只要 distance 跟上一次不一樣就跳通知)
                if distance in [0, 1, 2, 3] and distance != last_notified_distance:
                    msg = f"🔥 準備看電視！目標預計在 {distance} 個人次內上場打擊！\n目前打者：第 {current_order} 棒。\n{batter_text}"
                    print(msg)
                    send_desktop_notify("⚾ 林安可即將上場！", msg)
                    last_notified_distance = distance
                    
                # 當目標打擊結束，棒次推進後，重置通知鎖定
                if distance > 3 and distance < 8:
                    if last_notified_distance != -1:
                        print("[DEBUG] 目標打擊已結束，重置通知鎖定狀態")
                    last_notified_distance = -1
    else:
        print("[DEBUG] 尚未出現打者，可能正在換局中或剛開始。")
        
    return last_notified_distance

def monitor_game(game_id, lin_order):
    """即時監控 Play-by-Play"""
    url_text = f"https://baseball.yahoo.co.jp/npb/game/{game_id}/text" # 文字轉播頁面
    url_score = f"https://baseball.yahoo.co.jp/npb/game/{game_id}/score" # 記分板頁面
    last_notified_distance = -1
    last_notified_pitcher = ""
    print(f"[DEBUG] 開始監控比賽 {game_id}，設定目標球員為第 {lin_order} 棒\n")
    
    while True:
        try:
            # 取得文字轉播頁面 (給打者監控用)
            res_text = requests.get(url_text, headers=HEADERS)
            soup_text = BeautifulSoup(res_text.text, 'html.parser')
            
            # 取得記分板頁面 (給投手監控用)
            res_score = requests.get(url_score, headers=HEADERS)
            soup_score = BeautifulSoup(res_score.text, 'html.parser')
            
            # 判斷是否比賽結束 (統一由 score 頁面判斷)
            status_container = (
                soup_score.find('div', id='result') or 
                soup_score.find('h4', class_='live') or 
                soup_score.find('div', id='liveinfo')
            )
            if status_container:
                status_text = status_container.text
                print(f"[DEBUG] 當前比賽狀態: {status_text.strip()}")
                if '試合終了' in status_text or '中止' in status_text:
                    msg = "⚾ 今日西武獅比賽已結束或中止！Agent 進入休息模式。"
                    print(msg)
                    send_desktop_notify("⚾ 比賽結束", msg)
                    break
            else:
                # 備用檢查：直接在全文搜尋
                if '試合終了' in soup_score.text:
                    msg = "⚾ 今日西武獅比賽已結束！Agent 進入休息模式。"
                    print(msg)
                    send_desktop_notify("⚾ 比賽結束", msg)
                    break
                
            # 負責監測投手並推播 (傳入 score 頁面的 soup)
            last_notified_pitcher = monitor_game_pitcher(soup_score, last_notified_pitcher)
                
            # 負責監測打者棒次並推播 (傳入 text 頁面的 soup)
            last_notified_distance = monitor_game_batter(soup_text, res_text.text, lin_order, last_notified_distance)

        except Exception as e:
            print(f"監控錯誤: {e}")
            
        print("[DEBUG] 等待 15 秒後更新... (開發測試用先縮短時間)\n")
        time.sleep(15) # 開發測試可以改短一點，實際上線建議 60 秒免得被 Ban IP

def daily_job(only_pitcher=False):
    print(f"[{datetime.now()}] 執行今日賽程檢查...")
    game_id, start_time = get_today_seibu_game()
    
    if game_id:
        print(f"Game ID: {game_id}")
        msg = f"🦁 發現今日西武獅賽程！開打時間：{start_time}\n將於比賽開打時啟動打擊監控。"
        print(msg)
        
        # 解析開賽時間，設定計時器等待到開賽
        match = re.search(r'(\d{1,2}):(\d{2})', start_time)
        if match:
            now = datetime.now()
            # Yahoo 上顯示的是日本時間，轉為台灣時間需扣除 1 小時
            target_time = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0) - timedelta(hours=1)
            wait_seconds = (target_time - now).total_seconds()
            
            if wait_seconds > 0:
                while True:
                    current_now = datetime.now()
                    remaining_seconds = (target_time - current_now).total_seconds()
                    if remaining_seconds <= 0:
                        break
                        
                    remaining_minutes = int(remaining_seconds // 60)
                    # 使用 \r 讓游標回到行首，並加上 end="" 與 flush=True 就可以在同一行直接覆蓋掉舊訊息
                    print(f"\r👉 距離開賽時間還有約 {remaining_minutes} 分鐘，Agent 休眠等待中... zZZ        ", end="", flush=True)
                    
                    if remaining_seconds > 600:
                        time.sleep(600)  # 大於 10 分鐘，睡 10 分鐘 (600 秒) 後醒來更新狀態
                    else:
                        time.sleep(remaining_seconds)  # 小於 10 分鐘，直接睡到開賽時間
                        break
                        
                print("\n⏰ 時間到！開始準備抓取打序與進行比賽監控。")
            else:
                print("👉 已經超過開賽時間，立即啟動！")

        # 取得打序 (實務上可以寫一個 while 迴圈直到開打前一刻再去抓)
        lin_order = get_lin_batting_order(game_id)
        if not lin_order:
            # 備用防呆機制
            lin_order = 4 
            
        # 啟動監控
        if only_pitcher:
            monitor_game(game_id, -1)
        else:
            monitor_game(game_id,lin_order)
    else:
        print("今日西武獅無賽程，Agent 繼續睡覺。")

# 每天早上 9:00 喚醒機器人查賽程
schedule.every().day.at("09:00").do(daily_job)

if __name__ == "__main__":
    print("啟動林安可上場通知 Agent...")
    daily_job() # 啟動時先檢查一次
    while True:
        schedule.run_pending()
        time.sleep(60)