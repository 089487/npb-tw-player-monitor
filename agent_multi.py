import requests
from bs4 import BeautifulSoup
import time
import schedule
import re
import platform
import subprocess
import os
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 載入 .env 檔案中的環境變數
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ================= 設定區 =================
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
TARGET_PLAYERS = [
    {
        'names': ['林安可', '林 安可' ],
        'team': '西武', # 可將隊伍改成日本 Yahoo 上的隊伍簡稱
        'role': 'Batter'
    }]
""",
    {
        'names': ['宋家豪', '宋 家豪'],
        'team': '楽天',
        'role': 'Pitcher'
    },
    {
        'names': ['孫易磊'],
        'team': '日本ハム',
        'role': 'Pitcher'
    },
    {
        'names': ['古林 睿煬', '古林睿煬', '古林'],
        'team': '日本ハム',
        'role': 'Pitcher'
    },
    {
        'names': ['徐 若熙', '徐若熙'],
        'team': 'ソフトバンク',
        'role': 'Pitcher'
    },
    
]"""

# 抽取 TEAM_NAMES 用於賽程搜尋
TEAM_NAMES = list(set(player['team'] for player in TARGET_PLAYERS))
# ==========================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def send_discord_notify(title, message):
    """發送訊息到 Discord 頻道 (使用 Webhook)"""
    if not DISCORD_WEBHOOK_URL:
        return
        
    payload = {
        "embeds": [
            {
                "title": title,
                "description": message,
                "color": 3447003, # 藍色
                "timestamp": datetime.now().astimezone().isoformat()
            }
        ]
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Discord 通知發送失敗: {e}")

def send_desktop_notify(title, message):
    """跨平台發送桌面推播通知，並同步發送到 Discord"""
    # 1. 桌面通知
    try:
        sys_name = platform.system()
        if sys_name == 'Linux':
            subprocess.run(['notify-send', title, message])
        elif sys_name == 'Darwin': # macOS
            subprocess.run(['osascript', '-e', f'display notification "{message}" with title "{title}"'])
        elif sys_name == 'Windows':
            from plyer import notification
            notification.notify(title=title, message=message, app_name='NPB Monitor')
        else:
            print(f"不支援的系統桌面通知 ({sys_name}): {title} - {message}")
    except Exception as e:
        print(f"桌面通知發送失敗: {e}")
    
    # 2. Discord 通知
    send_discord_notify(title, message)

def get_player_by_name(player_name):
    """根據球員名稱查找 TARGET_PLAYERS 中的球員資訊"""
    for player in TARGET_PLAYERS:
        if any(name in player_name for name in player['names']):
            return player
    return None

def get_today_games():
    """爬取今日賽程，尋找包含目標隊伍的所有比賽 ID"""
    target_games = {}
    url = "https://baseball.yahoo.co.jp/npb/schedule/"
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 尋找所有比賽項目
        games = soup.find_all('li', class_='bb-score__item')
        for game in games:
            game_text = game.text
            # 檢查是否包含任何目標隊伍
            detected_teams = [team for team in TEAM_NAMES if team in game_text]
            if detected_teams:
                a_tag = game.find('a')
                if a_tag and '/game/' in a_tag['href']:
                    game_id = a_tag['href'].split('/game/')[1].replace('/top', '').replace('/', '').replace('index','')
                    start_time_tag = game.find('time', class_='bb-score__status') or game.find('span', class_='bb-score__date')
                    start_time = start_time_tag.text.strip() if start_time_tag else "已開打"
                    # 多個關注的隊伍可能在同一場比賽，所以用 game_id 當 key，避免重複加入
                    target_games[game_id] = {
                        'start_time': start_time,
                        'teams': detected_teams
                    }
    except Exception as e:
        print(f"取得賽程發生錯誤: {e}")
    return target_games

def get_batting_orders(game_id):
    """取得所有目標打者的先發打序"""
    batting_orders = {}
    url = f"https://baseball.yahoo.co.jp/npb/game/{game_id}/score"
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 解析 soup 內的表格找到目標球員對應的棒次
        rows = soup.find_all('tr', class_='bb-splitsTable__row')
        for row in rows:
            name_cell = row.find('td', class_='bb-splitsTable__data--text')
            if name_cell:
                player_name = name_cell.text.strip()
                player = get_player_by_name(player_name)
                if player and player['role'] == 'Batter':
                    order_cell = row.find('td', class_='bb-splitsTable__data')
                    if order_cell and order_cell.text.strip().isdigit():
                        order = int(order_cell.text.strip())
                        # 使用球員的第一個名稱作為 key
                        player_key = player['names'][0]
                        batting_orders[player_key] = order
                        print(f"✓ 確認 {player_name} (隊伍: {player['team']}) 在先發名單中，擔任第 {order} 棒\n")
                        msg = f"{player_name} (隊伍: {player['team']}) 在先發名單中，擔任第 {order} 棒"
                        # also send the notification
                        send_desktop_notify("先發打擊", msg)
    except Exception as e:
        print(f"取得打序錯誤: {e}")
    
    return batting_orders

def monitor_game_pitchers(game_id, soup, last_notified_pitchers, topbot):
    """監測場上投手是否為目標選手"""
    current_pitcher_name = ""
    rslt_table = soup.find('table', id='gm_rslt')
    if rslt_table:
        tbody = rslt_table.find('tbody')
        if tbody:
            player_tds = tbody.find_all('td', class_='bb-splitsTable__data--text')
            if len(player_tds) >= 2:
                current_pitcher_name = player_tds[topbot].text.strip()
    
    if current_pitcher_name:
        # 只有在更換投手時才重新檢查/推播一次
        if current_pitcher_name != last_notified_pitchers.get('current'):
            # 檢查是否為目標投手
            pitcher_info = get_player_by_name(current_pitcher_name)
            if pitcher_info and pitcher_info['role'] == 'Pitcher':
                msg = f"⚾ 準備看電視！目標投手 {current_pitcher_name} ({pitcher_info['team']}) 已經登板！"
                print(f"[Match {game_id}] {msg}")
                send_desktop_notify("⚾ 目標投手登板！", msg)
            
            last_notified_pitchers['current'] = current_pitcher_name
            
    return last_notified_pitchers

def monitor_game_batters(game_id, soup, batting_orders, last_notified_distances, player_batting_flags, player_at_bats):
    """監測打者棒次是否即將輪到目標選手"""
    # 取得最新的 live 區段 (通常是第一筆)
    live_sections = soup.find_all('section', class_='bb-liveText')
    if not live_sections:
        return last_notified_distances, player_batting_flags
        
    latest_section = live_sections[0]
    
    # 從最新區段中找目前的打者標籤
    batter_tag = latest_section.find('p', class_='bb-liveText__batter')
    
    if batter_tag:
        batter_text = batter_tag.text.strip()
        
        # 判斷是否為自家球隊攻擊中
        is_our_team_batting = False
        batting_team = None
        
        detail_tag = latest_section.find('p', class_='bb-liveText__detail')
        if detail_tag and 'の攻撃' in detail_tag.text:
            for team in TEAM_NAMES:
                if team in detail_tag.text:
                    is_our_team_batting = True
                    batting_team = team
                    break
        
        if not is_our_team_batting:
            # 備用判斷：檢核打者文字中是否包含球隊名稱
            for team in TEAM_NAMES:
                if team in batter_text:
                    is_our_team_batting = True
                    batting_team = team
                    break
                
        current_order = -1
        outs = 0
        
        if is_our_team_batting:
            match = re.search(r'(\d+)番', batter_text)
            if match:
                current_order = int(match.group(1))
                
                # 從當前打者的 state 中提取出局數
                state_tag = batter_tag.find('span', class_='bb-liveText__state')
                if state_tag:
                    state_text = state_tag.text.strip()
                    if '三死' in state_text: outs = 3
                    elif '二死' in state_text: outs = 2
                    elif '一死' in state_text: outs = 1
                    elif '無死' in state_text: outs = 0
                    
        remaining_outs = 3 - outs
        
        # 檢查打擊結束並輸出結果
        for player_name in list(player_batting_flags.keys()):
            if player_batting_flags.get(player_name):
                still_batting = False
                player_info = get_player_by_name(player_name)
                if is_our_team_batting and current_order != -1 and player_info:
                    if batting_team and player_info['team'] == batting_team:
                        target_order = batting_orders.get(player_name, -1)
                        if target_order != -1 and ((target_order - current_order) % 9) == 0:
                            still_batting = True
                            
                if not still_batting:
                    # 打擊結束，去 stats 抓出最近一次打擊結果
                    result_text = "未知結果"
                    try:
                        url_stats = f"https://baseball.yahoo.co.jp/npb/game/{game_id}/stats"
                        res_stats = requests.get(url_stats, headers=HEADERS)
                        soup_stats = BeautifulSoup(res_stats.text, 'html.parser')
                        rows = soup_stats.find_all('tr', class_='bb-statsTable__row')
                        for row in rows:
                            player_cell = row.find('td', class_='bb-statsTable__data--player')
                            if player_cell and player_name in player_cell.text:
                                details = row.find_all('div', class_='bb-statsTable__dataDetail')
                                valid_results = [d.text.strip() for d in details if d.text.strip()]
                                if valid_results:
                                    result_text = valid_results[-1]
                                    # 維護陣列
                                    if player_name not in player_at_bats:
                                        player_at_bats[player_name] = []
                                    player_at_bats[player_name] = valid_results
                                break
                    except Exception as e:
                        print(f"取得 stats 錯誤: {e}")
                        
                    msg = f"🔥 {player_name} 打擊剛結束！結果：{result_text}"
                    print(f"[Match {game_id}] {msg}")
                    send_desktop_notify(f"⚾ {player_name} 打席結果", msg)
                    
                    player_batting_flags[player_name] = False

        if is_our_team_batting and current_order != -1:
            # 對每個目標打者檢查
            for player_name, target_order in batting_orders.items():
                # 確保是該球員所屬球隊在進攻，否則不推播該球員
                player_info = get_player_by_name(player_name)
                if player_info and batting_team and player_info['team'] != batting_team:
                    continue
                    
                # 計算距離
                distance = (target_order - current_order) % 9
                
                if player_name not in last_notified_distances:
                    last_notified_distances[player_name] = -1
                    
                if player_name not in player_batting_flags:
                    player_batting_flags[player_name] = False
                    
                if distance == 0:
                    player_batting_flags[player_name] = True
                
                # 判斷邏輯：如果距離小於等於剩餘出局數 (表示該半局有機會上場)
                # distance 為 0 表示正在打擊
                should_notify = (distance == 0) or (distance > 0 and distance <= min(remaining_outs,2))
                
                if should_notify and distance != last_notified_distances[player_name]:
                    out_desc = f"{outs} 出局"
                    if distance == 0:
                        msg = f"🔥 {player_name} 正在打擊！({out_desc})"
                    else:
                        msg = f"🔥 準備看電視！{player_name} 預計在 {distance} 個人次內上場打擊！\n目前：{out_desc}，第 {current_order} 棒。"
                    
                    print(f"[Match {game_id}] {msg}")
                    send_desktop_notify(f"⚾ {player_name} 即將上場！", msg)
                    last_notified_distances[player_name] = distance
                    
                # 當打擊結束或該半局沒機會上場時，重置通知鎖定
                if distance > remaining_outs and distance < 8:
                    if last_notified_distances[player_name] != -1:
                        print(f"[Match {game_id}] [DEBUG] {player_name} 的打擊機會已過或本局難度高，重置通知鎖定狀態")
                    last_notified_distances[player_name] = -1        
    return last_notified_distances, player_batting_flags

def monitor_game_task(game_id, start_time, detected_teams):
    """監控單場比賽的獨立任務"""
    # 解析開賽時間，設定計時器等待到開賽
    match = re.search(r'(\d{1,2}):(\d{2})', start_time)
    if match:
        now = datetime.now()
        target_time = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0) - timedelta(hours=1)
        wait_seconds = (target_time - now).total_seconds()
        
        if wait_seconds > 0:
            print(f"[Match {game_id}] ⚽ 發現比賽！開打時間：{target_time} - 目標隊伍: {', '.join(detected_teams)}")
            msg = f"⚽ 發現比賽！開打時間：{target_time} - 目標隊伍: {', '.join(detected_teams)}"
            # send discord notify
            send_desktop_notify("今晚比賽時程", msg)
            while True:
                current_now = datetime.now()
                remaining_seconds = (target_time - current_now).total_seconds()
                if remaining_seconds <= 0:
                    break
                    
                if remaining_seconds > 600:
                    time.sleep(600)
                else:
                    time.sleep(remaining_seconds)
                    break
            print(f"[Match {game_id}] ⏰ 時間到！開始準備抓取打序與進行比賽監控。")
        else:
            print(f"[Match {game_id}] 👉 已經超過開賽時間，立即啟動監控！目標隊伍: {', '.join(detected_teams)}")

    # 取得打序
    batting_orders = get_batting_orders(game_id)
    
    url_text = f"https://baseball.yahoo.co.jp/npb/game/{game_id}/text"
    url_score = f"https://baseball.yahoo.co.jp/npb/game/{game_id}/score"
    
    last_notified_distances = {}
    last_notified_pitchers = {'current': ''}
    player_batting_flags = {}
    player_at_bats = {}
    inning_switch = 0
    
    print(f"[Match {game_id}] 開始賽程即時監控...")

    
    while True:
        try:
            res_text = requests.get(url_text, headers=HEADERS)
            soup_text = BeautifulSoup(res_text.text, 'html.parser')
            
            res_score = requests.get(url_score, headers=HEADERS)
            soup_score = BeautifulSoup(res_score.text, 'html.parser')
            
            # 判斷比賽是否結束
            status_container = (
                soup_score.find('div', id='result') or 
                soup_score.find('h4', class_='live') or 
                soup_score.find('div', id='liveinfo')
            )
            
            if status_container:
                status_text = status_container.text
                if '試合終了' in status_text or '中止' in status_text:
                    msg = f"⚾ 比賽 {game_id} ({', '.join(detected_teams)}) 已結束或中止！"
                    print(msg)
                    if player_at_bats:
                        summary_msg = "本日打擊成績：\n"
                        for player_name, results in player_at_bats.items():
                            summary_msg += f"{player_name}: {', '.join(results)}\n"
                        print(summary_msg)
                        send_desktop_notify("⚾ 打擊成績總結", summary_msg)
                    # 只有在有目標球員上場（不論打者或投手）過才發送結束通知
                    if batting_orders or last_notified_pitchers.get('current'):
                        send_desktop_notify("⚾ 比賽結束", msg)
                    break
            else:
                if '試合終了' in soup_score.text:
                    msg = f"⚾ 比賽 {game_id} ({', '.join(detected_teams)}) 已結束！"
                    print(msg)
                    if player_at_bats:
                        summary_msg = "本日打擊成績：\n"
                        for player_name, results in player_at_bats.items():
                            summary_msg += f"{player_name}: {', '.join(results)}\n"
                        print(summary_msg)
                        send_desktop_notify("⚾ 打擊成績總結", summary_msg)
                    if batting_orders or last_notified_pitchers.get('current'):
                        send_desktop_notify("⚾ 比賽結束", msg)
                    break
            
            # 判斷攻防狀態
            try:
                topbot = 0 if '表' in soup_score.find('h4', class_='live').get_text() else 1
            except:
                topbot = 0
            
            try:
                result_text = soup_score.find('div', id='result').get_text()
                inning_switch = 1 if 'NEXT' in result_text else inning_switch
                inning_switch = 0 if 'ボール' in result_text else inning_switch
            except:
                pass
            
            # 監測投手
            last_notified_pitchers = monitor_game_pitchers(game_id, soup_score, last_notified_pitchers, topbot)
            
            # 監測打者
            if batting_orders:
                last_notified_distances, player_batting_flags = monitor_game_batters(game_id, soup_text, batting_orders, last_notified_distances, player_batting_flags, player_at_bats)

        except Exception as e:
            print(f"[Match {game_id}] 監控錯誤: {e}")
            
        time.sleep(60 - 45 * inning_switch)

def daily_job():
    print(f"[{datetime.now()}] 執行今日賽程檢查...")
    games = get_today_games()
    
    if games:
        print(f"發現目標球員相關賽事共 {len(games)} 場！")
        # 針對每一場比賽開啟一個執行緒獨立監控
        for game_id, info in games.items():
            t = threading.Thread(target=monitor_game_task, args=(game_id, info['start_time'], info['teams']))
            t.daemon = True # 主程式結束時自動關閉這些子執行緒
            t.start()
    else:
        print("今日無目標隊伍比賽，Agent 繼續睡覺。")

# 每天早上 9:00 喚醒機器人查賽程
schedule.every().day.at("09:00").do(daily_job)

if __name__ == "__main__":
    print("啟動多球員監控 Agent... (支援多場次同步監控)")
    daily_job()
    while True:
        schedule.run_pending()
        time.sleep(60)
