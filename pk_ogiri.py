import os
import json
import re
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import requests
import openpyxl

app = Flask(__name__, template_folder='templates', static_folder='public/static', static_url_path='/static')
CORS(app)
app.secret_key = 'pk_ogiri_secret_key_13579'

def get_current_user_id():
    user_id = request.headers.get('X-User-Id')
    if user_id and str(user_id).strip():
        return str(user_id).strip()
    if 'user_id' in session and str(session['user_id']).strip():
        return str(session['user_id']).strip()
    if request.is_json and request.json and request.json.get('user_id'):
        return str(request.json.get('user_id')).strip()
    if request.args and request.args.get('user_id'):
        return str(request.args.get('user_id')).strip()
    return None

def check_user_id(u1, u2):
    if u1 is None or u2 is None:
        return False
    return str(u1).strip().lower() == str(u2).strip().lower()

# --- Real-Time Battle State ---
# Waiting queues and active state
battle_waiting_players = set()  # Set of user_ids waiting to battle
grading_viewers = set()         # Set of user_ids viewing grader screen

# Active battle details
active_battle = {
    "active": False,
    "player_a": None,  # User ID of Player A
    "player_b": None,  # User ID of Player B
    "a_pokemon": [],   # Copies of Player A's pokemon with dynamic HP, stats, status
    "b_pokemon": [],   # Copies of Player B's pokemon
    "a_active_idx": 0, # Index of active pokemon (0 or 1)
    "b_active_idx": 0,
    "a_selected_move": None, # Move dict selected by A
    "b_selected_move": None, # Move dict selected by B
    "a_damage": 0,    # Damage dealt by Player A in this battle
    "b_damage": 0,    # Damage dealt by Player B in this battle
    "a_swapped": False, # Has A swapped manually in this battle?
    "b_swapped": False, # Has B swapped manually in this battle?
    "swap_request": None, # 'A' or 'B' requesting swap
    "target_player": None, # Current grading target: 'A', 'B', or None (no target)
    "scores": [],          # List of grader scores: e.g. [1, 2, 3, 2, 2, 3]
    "voted_graders": [],   # List of user_ids who have already graded in this round
    "messages": [],        # History of battle log messages
    "last_confirmed_score": None,
    "last_calculated_score": 0,
    "exclude_chikara": [], # List of roles to exclude from receiving Chikara no Moto: e.g. ["A"], ["B"], ["A", "B"]
    "timer": {
        "status": "stopped",
        "start_timestamp": None,
        "elapsed_seconds": 0,
        "duration": 300
    }
}

def get_timer_info():
    timer_data = active_battle.get("timer")
    if not isinstance(timer_data, dict):
        timer_data = {
            "status": "stopped",
            "start_timestamp": None,
            "elapsed_seconds": 0,
            "duration": 300
        }
    status = timer_data.get("status", "stopped")
    elapsed = float(timer_data.get("elapsed_seconds", 0))
    start_ts = timer_data.get("start_timestamp")
    
    if status == "running" and start_ts:
        import time
        elapsed += (time.time() - start_ts)
        
    duration = float(timer_data.get("duration", 300))
    remaining = duration - elapsed
    
    return {
        "status": status,
        "elapsed": elapsed,
        "remaining": remaining,
        "duration": duration,
        "start_timestamp": start_ts
    }

BATTLE_STATE_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'battle_state.json')

def get_kv_credentials():
    url = os.environ.get('KV_REST_API_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
    token = os.environ.get('KV_REST_API_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
    
    if url and token:
        return url, token

    # Support standard Vercel REDIS_URL format (rediss://default:PASSWORD@HOST:PORT)
    redis_url = os.environ.get('REDIS_URL')
    if redis_url:
        try:
            # Parse rediss://default:TOKEN@HOST:PORT or redis://default:TOKEN@HOST:PORT
            clean_url = redis_url.replace('rediss://', '').replace('redis://', '')
            if '@' in clean_url:
                user_pass, host_port = clean_url.split('@', 1)
                token = user_pass.split(':', 1)[1] if ':' in user_pass else user_pass
                host = host_port.split(':', 1)[0]
                
                # Convert TCP host (.db.redis.io) to REST HTTP host (.upstash.io)
                if host.endswith('.db.redis.io'):
                    host = host.replace('.db.redis.io', '.upstash.io')
                
                url = f"https://{host}"
                return url, token
        except Exception as e:
            print(f"Failed to parse REDIS_URL: {e}")

    return None, None

def get_battle_state_kv_key():
    room_id = os.environ.get('ROOM_ID', 'default').strip()
    return f"battle_state_{room_id}"

import sqlite3

def get_sqlite_db_path():
    room_id = os.environ.get('ROOM_ID', 'default').strip()
    return f"/tmp/battle_state_{room_id}.db"

def init_sqlite_db():
    db_path = get_sqlite_db_path()
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"SQLite init error: {e}")

def load_battle_state_sqlite():
    db_path = get_sqlite_db_path()
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT value FROM state WHERE key='data'")
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            data = json.loads(row[0])
            battle_waiting_players.clear()
            battle_waiting_players.update(data.get("waiting_players", []))
            grading_viewers.clear()
            grading_viewers.update(data.get("grading_viewers", []))
            active_battle.clear()
            active_battle.update(data.get("active_battle", {}))
            return True
    except Exception as e:
        print(f"SQLite load error: {e}")
    return False

def save_battle_state_sqlite():
    db_path = get_sqlite_db_path()
    try:
        init_sqlite_db()
        data = {
            "waiting_players": list(battle_waiting_players),
            "grading_viewers": list(grading_viewers),
            "active_battle": active_battle
        }
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('data', ?)", (json.dumps(data, ensure_ascii=False),))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"SQLite save error: {e}")
    return False

def load_battle_state():
    global battle_waiting_players, grading_viewers, active_battle
    
    # 1. Try Vercel KV REST API first (if credentials are set and working)
    KV_REST_API_URL, KV_REST_API_TOKEN = get_kv_credentials()
    if KV_REST_API_URL and KV_REST_API_TOKEN:
        try:
            url = KV_REST_API_URL.rstrip('/')
            headers = {'Authorization': f'Bearer {KV_REST_API_TOKEN}'}
            key = get_battle_state_kv_key()
            res = requests.post(url, headers=headers, json=["GET", key], timeout=1.0)
            if res.status_code == 200:
                result = res.json().get('result')
                if result:
                    data = json.loads(result)
                    battle_waiting_players.clear()
                    battle_waiting_players.update(data.get("waiting_players", []))
                    grading_viewers.clear()
                    grading_viewers.update(data.get("grading_viewers", []))
                    active_battle.clear()
                    active_battle.update(data.get("active_battle", {}))
                    return
        except Exception:
            pass

    # 2. Fallback to /tmp SQLite DB
    if load_battle_state_sqlite():
        return

    # 3. Fallback to local JSON file
    if not os.path.exists(BATTLE_STATE_JSON_PATH):
        try:
            save_battle_state()
        except Exception:
            pass
        return
    import time
    for _ in range(5):
        try:
            with open(BATTLE_STATE_JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            battle_waiting_players.clear()
            battle_waiting_players.update(data.get("waiting_players", []))
            grading_viewers.clear()
            grading_viewers.update(data.get("grading_viewers", []))
            active_battle.clear()
            active_battle.update(data.get("active_battle", {}))
            return
        except Exception:
            time.sleep(0.01)

def save_battle_state():
    # 1. Try Vercel KV REST API
    KV_REST_API_URL, KV_REST_API_TOKEN = get_kv_credentials()
    if KV_REST_API_URL and KV_REST_API_TOKEN:
        try:
            url = KV_REST_API_URL.rstrip('/')
            headers = {'Authorization': f'Bearer {KV_REST_API_TOKEN}'}
            data = {
                "waiting_players": list(battle_waiting_players),
                "grading_viewers": list(grading_viewers),
                "active_battle": active_battle
            }
            key = get_battle_state_kv_key()
            res = requests.post(url, headers=headers, json=["SET", key, json.dumps(data, ensure_ascii=False)], timeout=1.0)
            if res.status_code == 200:
                return
        except Exception:
            pass

    # 2. Fallback to /tmp SQLite DB
    save_battle_state_sqlite()

    # 3. Fallback to local JSON file
    data = {
        "waiting_players": list(battle_waiting_players),
        "grading_viewers": list(grading_viewers),
        "active_battle": active_battle
    }
    temp_path = BATTLE_STATE_JSON_PATH + '.tmp'
    import time
    for _ in range(5):
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(temp_path, BATTLE_STATE_JSON_PATH)
            return
        except Exception:
            time.sleep(0.01)

@app.route('/api/admin/debug_kv', methods=['GET'])
def debug_kv():
    return jsonify({
        "status": "ready",
        "room_id": os.environ.get('ROOM_ID', 'default'),
        "REDIS_URL_exists": os.environ.get('REDIS_URL') is not None
    })

@app.before_request
def before_request():
    load_battle_state()

previous_battle_state = None
previous_players_state = None

def calculate_score(scores):
    if len(scores) < 6:
        return 0
    # Exactly 6 scores
    scores_sorted = sorted(scores[:6])
    # Check if all are max points (3)
    if all(s == 3 for s in scores_sorted):
        return 100
    # Exclude lowest and highest
    mid_scores = scores_sorted[1:5]
    # Product of 4 scores
    prod = 1
    for s in mid_scores:
        prod *= s
    return prod

def get_effectiveness(move_type, defender_types):
    # Weakness/resistance calculation using type_chart
    tc = load_type_chart()
    multiplier = 1.0
    if not move_type or not tc:
        return multiplier, ""
    
    # Clean and check
    m_type = str(move_type).strip()
    for d_type in defender_types:
        if not d_type or d_type == "-":
            continue
        d_type = str(d_type).strip()
        # Look up in type chart
        if m_type in tc and d_type in tc[m_type]:
            val = tc[m_type][d_type]
            multiplier *= val

    eff_msg = ""
    if multiplier > 1.0:
        eff_msg = "こうかは　ばつぐんだ！"
    elif multiplier == 0.0:
        eff_msg = "こうかがない　ようだった…"
    elif multiplier < 1.0:
        eff_msg = "こうかは　いまひとつの　ようだ…"
        
    return multiplier, eff_msg

def calculate_battle_damage(attacker, defender, move):
    import math
    power = move.get('power') or 0
    if int(power) == 100:
        return defender.get('max_hp') or 1
        
    level = attacker.get('level', 50)
    
    # Identify move category (physical/special) from attacker's move list
    move_name = move.get('name')
    category = '物理'
    for m in attacker.get('moves', []):
        if m.get('name') == move_name:
            category = m.get('category', '物理')
            break
            
    if category == '物理':
        A = attacker.get('attack') or 1
        D = defender.get('defense') or 1
    else:
        A = attacker.get('sp_attack') or 1
        D = defender.get('sp_defense') or 1
        
    if A <= 0: A = 1
    if D <= 0: D = 1
        
    term1 = math.floor(level * 2 / 5) + 2
    term2 = math.floor((term1 * power * A) / D)
    term3 = math.floor(term2 / 50) + 2
    
    # Type efficiency modifier
    mult, _ = get_effectiveness(move.get('type'), [defender.get('type1'), defender.get('type2')])
    M = mult
    
    # Same-type attack bonus (STAB) (1.2x)
    if attacker.get('type1') == move.get('type') or attacker.get('type2') == move.get('type'):
        M *= 1.2

    # Attacker Item Boosts
    att_item = attacker.get('item')
    type_boost_item_map = {
        "りゅうのキバ": ("ドラゴン", 1.1),
        "ようせいのハネ": ("フェアリー", 1.1),
        "やわらかいすな": ("じめん", 1.1),
        "もくたん": ("ほのお", 1.1),
        "メタルコート": ("はがね", 1.1),
        "まがったスプーン": ("エスパー", 1.1),
        "のろいのおふだ": ("ゴースト", 1.1),
        "とけないこおり": ("こおり", 1.1),
        "どくバリ": ("どく", 1.1),
        "するどいくちばし": ("ひこう", 1.1),
        "しんぴのしずく": ("みず", 1.1),
        "シルクのスカーフ": ("ノーマル", 1.1),
        "じしゃく": ("でんき", 1.1),
        "くろおび": ("かくとう", 1.1),
        "くろいメガネ": ("あく", 1.1),
        "きせきのタネ": ("くさ", 1.1),
        "かたいいし": ("いわ", 1.1),
    }
    if att_item in type_boost_item_map:
        b_type, b_mult = type_boost_item_map[att_item]
        if move.get('type') == b_type:
            M *= b_mult

    if att_item == 'こだわりハチマキ' and category == '物理':
        M *= 1.2
    elif att_item == 'こだわりメガネ' and category != '物理':
        M *= 1.2

    # Defender Item Reductions (Type-resist berries)
    def_item = defender.get('item')
    type_berry_map = {
        "フェアリー": "ロゼルのみ",
        "くさ": "リンドのみ",
        "はがね": "リリバのみ",
        "いわ": "ヨロギのみ",
        "かくとう": "ヨプのみ",
        "こおり": "ヤチェのみ",
        "ノーマル": "ホズのみ",
        "どく": "ビアーのみ",
        "ドラゴン": "ハバンのみ",
        "ひこう": "バコウのみ",
        "あく": "ナモのみ",
        "むし": "タンガのみ",
        "でんき": "ソクノのみ",
        "じめん": "シュカのみ",
        "ゴースト": "カシブのみ",
        "ほのお": "オッカのみ",
        "エスパー": "ウタンのみ",
        "みず": "イトケのみ"
    }
    if def_item and type_berry_map.get(move.get('type')) == def_item:
        M *= 0.5

    damage = math.floor(term3 * M)
    if att_item == 'いのちのたま':
        damage = math.floor(damage * 1.2)

    if damage <= 0:
        damage = 1
    return damage

# ------------------------------

EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pk_ogiri.xlsm')

def get_workbook():
    return openpyxl.load_workbook(EXCEL_PATH, read_only=True)

def get_sheet_data(sheet):
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = rows[0]
    data = []
    for row in rows[1:]:
        if not row or row[0] is None:
            continue
        data.append(dict(zip(headers, row)))
    return data

import json

PLAYERS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'players.json')
POKEMON_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pokemon_list.json')
MOVES_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'moves_list.json')
TYPE_CHART_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'type_chart.json')
ITEMS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pokemon_items.json')

def load_type_chart():
    try:
        with open(TYPE_CHART_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read type_chart.json: {e}")
        return {}


def convert_player_format(player):
    modified = False
    if '与ダメージ' not in player:
        player['与ダメージ'] = 0
        modified = True
    old_keys_exist = any(k in player for k in ['ポケモン1', 'ポケモン2', 'ポケモン１', 'ポケモン２'])
    if old_keys_exist:
        pokemon_list = []
        for keys in [('ポケモン1', 'ポケモン１'), ('ポケモン2', 'ポケモン２')]:
            poke_name = None
            for k in keys:
                if k in player:
                    poke_name = player.get(k)
                    break
            if poke_name:
                default_moves = []
                try:
                    if os.path.exists(POKEMON_JSON_PATH):
                        with open(POKEMON_JSON_PATH, 'r', encoding='utf-8') as f:
                            master_pokes = json.load(f)
                        master_poke = next((p for p in master_pokes if p.get('名前') == poke_name), None)
                        if master_poke:
                            for zn in ["１", "２", "３", "４", "５"]:
                                m_name = master_poke.get(f'わざ{zn}')
                                if m_name:
                                    default_moves.append(str(m_name).strip())
                except Exception:
                    pass
                
                default_moves = default_moves[:4]
                while len(default_moves) < 4:
                    default_moves.append("-")

                pokemon_list.append({
                    "名前": poke_name,
                    "レベル": 50,
                    "もちもの": None,
                    "わざ": default_moves
                })
        player['ポケモン'] = pokemon_list
        for k in ['ポケモン1', 'ポケモン2', 'ポケモン１', 'ポケモン２']:
            player.pop(k, None)
        modified = True
    return modified

def load_players():
    # 1. Try Vercel KV REST API first (if credentials are set on Vercel)
    KV_REST_API_URL, KV_REST_API_TOKEN = get_kv_credentials()
    if KV_REST_API_URL and KV_REST_API_TOKEN:
        try:
            url = KV_REST_API_URL.rstrip('/')
            headers = {'Authorization': f'Bearer {KV_REST_API_TOKEN}'}
            res = requests.post(url, headers=headers, json=["GET", "players_data"])
            if res.status_code == 200:
                result = res.json().get('result')
                if result:
                    data = json.loads(result)
                    modified = False
                    for p in data:
                        if convert_player_format(p):
                            modified = True
                    if modified:
                        save_players(data)
                    return data
        except Exception as e:
            print(f"Failed to load players from Vercel KV: {e}")

    # 2. Fallback to local JSON file
    if not os.path.exists(PLAYERS_JSON_PATH):
        try:
            wb = get_workbook()
            data = get_sheet_data(wb['プレイヤーデータ'])
            wb.close()
            for p in data:
                convert_player_format(p)
            with open(PLAYERS_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return data
        except Exception:
            with open(PLAYERS_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=4)
            return []
    else:
        try:
            with open(PLAYERS_JSON_PATH, 'r', encoding='utf-8') as f:
                players = json.load(f)
            
            modified = False
            for p in players:
                if convert_player_format(p):
                    modified = True
            if modified:
                save_players(players)
            return players
        except Exception as e:
            print(f"Failed to read players.json: {e}")
            return []

def save_players(players_data):
    # 1. Try Vercel KV REST API first (if credentials are set on Vercel)
    KV_REST_API_URL, KV_REST_API_TOKEN = get_kv_credentials()
    if KV_REST_API_URL and KV_REST_API_TOKEN:
        try:
            url = KV_REST_API_URL.rstrip('/')
            headers = {'Authorization': f'Bearer {KV_REST_API_TOKEN}'}
            data_str = json.dumps(players_data, ensure_ascii=False)
            res = requests.post(url, headers=headers, json=["SET", "players_data", data_str])
            if res.status_code == 200:
                # Also try saving to local file if writable
                try:
                    with open(PLAYERS_JSON_PATH, 'w', encoding='utf-8') as f:
                        f.write(data_str)
                except Exception:
                    pass
                return
        except Exception as e:
            print(f"Failed to save players to Vercel KV: {e}")

    # 2. Fallback to local JSON file
    try:
        with open(PLAYERS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(players_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Failed to write players.json: {e}")

def sync_excel_to_json():
    excel_exists = os.path.exists(EXCEL_PATH)
    if not excel_exists:
        return

    excel_mtime = os.path.getmtime(EXCEL_PATH)
    pokemon_cached = os.path.exists(POKEMON_JSON_PATH)
    moves_cached = os.path.exists(MOVES_JSON_PATH)

    pokemon_up_to_date = pokemon_cached and os.path.getmtime(POKEMON_JSON_PATH) >= excel_mtime
    moves_up_to_date = moves_cached and os.path.getmtime(MOVES_JSON_PATH) >= excel_mtime

    if not pokemon_up_to_date or not moves_up_to_date:
        print("Excel is newer or cache is missing. Syncing static data from Excel to JSON...")
        try:
            wb = get_workbook()
            pokemon_data = get_sheet_data(wb['ポケモン一覧'])
            moves_data = get_sheet_data(wb['わざ一覧'])
            wb.close()
            
            with open(POKEMON_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(pokemon_data, f, ensure_ascii=False, indent=4)
            with open(MOVES_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(moves_data, f, ensure_ascii=False, indent=4)
            print("Successfully refreshed JSON files from Excel.")
        except Exception as e:
            print(f"Error syncing Excel to JSON: {e}")

def get_pokemon_list():
    sync_excel_to_json()
    try:
        with open(POKEMON_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read pokemon_list.json: {e}")
        return []

def get_moves_list():
    sync_excel_to_json()
    try:
        with open(MOVES_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read moves_list.json: {e}")
        return []

def get_items():
    try:
        if os.path.exists(ITEMS_JSON_PATH):
            with open(ITEMS_JSON_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to read pokemon_items.json: {e}")
    return []

def get_item_effect_text(item_name):
    if not item_name:
        return ""
    for item in get_items():
        if item.get('名前') == item_name:
            return item.get('効果')
    return ""

def get_players():
    return load_players()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()
    name = data.get('name', '').strip()

    # Validation: Alphanumeric, 4 characters or more
    if not re.match(r'^[a-zA-Z0-9]{4,}$', user_id):
        return jsonify({
            "success": False,
            "message": "ユーザーIDは4文字以上の半角英数字で入力してください。"
        }), 400

    if not name:
        return jsonify({
            "success": False,
            "message": "名前を入力してください。"
        }), 400

    players = get_players()

    # Check duplicate
    for p in players:
        if check_user_id(p.get('ユーザid'), user_id):
            return jsonify({
                "success": False,
                "message": "このユーザーIDは既に登録されています。"
            }), 400

    # Add new row
    new_row = {
        'ユーザid': user_id,
        '名前': name,
        'ポケモン': [],
        'もちもの': '',
        '所持金': 500,
        '希望1': None,
        '希望2': None,
        '希望3': None,
        '希望4': None
    }
    # Update and save to JSON file
    players.append(new_row)
    save_players(players)

    session['user_id'] = user_id
    st_info = determine_player_status(new_row)
    return jsonify({
        "success": True,
        "user_id": user_id,
        "message": "登録が完了しました。",
        **st_info
    })

def determine_player_status(player):
    p_list = player.get('ポケモン', [])
    pokemon1 = p_list[0].get('名前') if len(p_list) > 0 else None
    pokemon2 = p_list[1].get('名前') if len(p_list) > 1 else None
    wish1 = player.get('希望1')

    if len(p_list) >= 2:
        status = "active"
        step = 2
    elif len(p_list) == 1:
        step = 2
        status = "waiting_2" if wish1 else "select_choices_2"
    else:
        step = 1
        status = "waiting_1" if wish1 else "select_choices_1"

    wishes = [player.get(f'希望{i}') for i in range(1, 5)]

    # Collect all pokemons taken as 1st pokemon by ANY player
    all_players = get_players()
    taken_pokemon1_list = []
    for other_p in all_players:
        other_list = other_p.get('ポケモン', [])
        if len(other_list) > 0:
            first_poke = other_list[0].get('名前')
            if first_poke and first_poke not in taken_pokemon1_list:
                taken_pokemon1_list.append(first_poke)

    return {
        "status": status,
        "step": step,
        "pokemon1": pokemon1,
        "pokemon2": pokemon2,
        "wishes": wishes,
        "taken_pokemon1_list": taken_pokemon1_list
    }

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()

    if not user_id:
        return jsonify({"success": False, "message": "ユーザーIDを入力してください。"}), 400

    players = get_players()

    player = None
    for p in players:
        if check_user_id(p.get('ユーザid'), user_id):
            player = p
            break

    if not player:
        return jsonify({"success": False, "message": "ユーザーIDが見つかりません。"}), 400

    session['user_id'] = user_id
    
    st_info = determine_player_status(player)

    return jsonify({
        "success": True,
        "user_id": user_id,
        **st_info
    })

@app.route('/api/submit_choices', methods=['POST'])
def submit_choices():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    data = request.json or {}
    choices = data.get('choices', [])

    if len(choices) != 4 or len(set(choices)) != 4:
        return jsonify({"success": False, "message": "重複のない4体のポケモンを選択してください。"}), 400

    players = get_players()

    found_player = None
    for p in players:
        if check_user_id(p.get('ユーザid'), user_id) or check_user_id(p.get('名前'), user_id):
            found_player = p
            break

    if not found_player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    p_list = found_player.get('ポケモン', [])
    if len(p_list) >= 2:
        return jsonify({"success": False, "message": "すでに2体のポケモンを入手しています。"}), 400

    existing_poke_names = [pk.get('名前') for pk in p_list]
    for c in choices:
        if c in existing_poke_names:
            return jsonify({"success": False, "message": f"所持済みのポケモン ({c}) は希望に選択できません。"}), 400

    for i, choice in enumerate(choices):
        found_player[f'希望{i+1}'] = choice

    save_players(players)

    st_info = determine_player_status(found_player)

    return jsonify({
        "success": True,
        **st_info
    })

@app.route('/api/status', methods=['GET'])
def get_status():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    players = get_players()

    player = None
    for p in players:
        if check_user_id(p.get('ユーザid'), user_id) or check_user_id(p.get('名前'), user_id):
            player = p
            break

    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    st_info = determine_player_status(player)

    return jsonify({
        "success": True,
        **st_info
    })

@app.route('/api/all_pokemons', methods=['GET'])
def all_pokemons_list():
    pokemon_list = get_pokemon_list()
    result = []
    for p in pokemon_list:
        p_name = p.get('名前')
        if p_name:
            result.append({
                "name": str(p_name).strip(),
                "番号": p.get('番号')
            })
    return jsonify({
        "success": True,
        "all_pokemons": result
    })

@app.route('/api/game_data', methods=['GET'])
def game_data():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    pokemon_list = get_pokemon_list()
    moves_list = get_moves_list()
    players = get_players()

    player = None
    for p in players:
        if check_user_id(p.get('ユーザid'), user_id) or check_user_id(p.get('名前'), user_id):
            player = p
            break

    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    player_pokemon = player.get('ポケモン', [])

    # Build moves map
    moves_map = {}
    for move in moves_list:
        move_name = move.get('わざ')
        if move_name:
            move_name_clean = str(move_name).strip()
            moves_map[move_name_clean] = {
                "name": move_name_clean,
                "type": move.get('タイプ'),
                "power": move.get('威力') or 0,
                "category": move.get('分類') or '物理'
            }

    # Helper to build pokemon map for O(1) lookups
    pokemon_map = {p.get('名前'): p for p in pokemon_list if p.get('名前')}

    # Helper to build pokemon detail object
    def get_pokemon_detail(name, p_data):
        p = pokemon_map.get(name)
        if p:
            poke_moves = []
            custom_moves = p_data.get('わざ')
            if not custom_moves:
                default_moves = []
                for zn in ["１", "２", "３", "４", "５"]:
                    m_name = p.get(f'わざ{zn}')
                    if m_name:
                        default_moves.append(str(m_name).strip())
                custom_moves = default_moves[:4]
                while len(custom_moves) < 4:
                    custom_moves.append("-")
            for m_name in custom_moves:
                if m_name and m_name != "-":
                    m_name_clean = str(m_name).strip()
                    if m_name_clean in moves_map:
                        poke_moves.append(moves_map[m_name_clean])
                    else:
                        poke_moves.append({
                            "name": m_name_clean,
                            "type": "ノーマル",
                            "power": 50,
                            "category": "物理"
                        })
            
            custom_item = p_data.get('もちもの')
            hp_boost = p_data.get('hp_boost', 0)
            attack_boost = p_data.get('attack_boost', 0)
            defense_boost = p_data.get('defense_boost', 0)
            sp_attack_boost = p_data.get('sp_attack_boost', 0)
            sp_defense_boost = p_data.get('sp_defense_boost', 0)

            return {
                "name": p.get('名前'),
                "番号": p.get('番号'),
                "type1": p.get('タイプ１'),
                "type2": p.get('タイプ2'),
                "hp": (p.get('HP（H）') or 0) + hp_boost,
                "attack": (p.get('攻撃（A）') or 0) + attack_boost,
                "defense": (p.get('防御（B）') or 0) + defense_boost,
                "sp_attack": (p.get('特攻（C）') or 0) + sp_attack_boost,
                "sp_defense": (p.get('特防（D）') or 0) + sp_defense_boost,
                "hp_boost": hp_boost,
                "attack_boost": attack_boost,
                "defense_boost": defense_boost,
                "sp_attack_boost": sp_attack_boost,
                "sp_defense_boost": sp_defense_boost,
                "level": p_data.get('レベル') or p.get('レベル') or 50,
                "moves": poke_moves,
                "item": custom_item
            }
        return None

    my_pokemon = []
    for p_data in player_pokemon:
        p_detail = get_pokemon_detail(p_data.get('名前'), p_data)
        if p_detail:
            my_pokemon.append(p_detail)

    # For wild select, return just basic names and details of all pokemons
    all_pokemons = []
    for p in pokemon_list:
        p_name = p.get('名前')
        if p_name:
            detail = get_pokemon_detail(p_name, {})
            if detail:
                all_pokemons.append(detail)

    return jsonify({
        "success": True,
        "my_pokemon": my_pokemon,
        "all_pokemons": all_pokemons,
        "type_chart": load_type_chart(),
        "money": player.get('所持金', 0),
        "items": [i.strip() for i in str(player.get('もちもの') or '').split(',') if i.strip()]
    })


# Shop API: アイテム一覧
@app.route('/api/items', methods=['GET'])
def get_items_list():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    items = get_items()
    players = get_players()
    player = next((p for p in players if check_user_id(p.get('ユーザid'), user_id)), None)
    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400
    owned_raw = player.get('もちもの') or ''
    owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
    return jsonify({
        "success": True,
        "items": items,
        "money": player.get('所持金', 0),
        "owned_items": owned,
        "moves": get_moves_list()
    })


# Shop API: 購入
@app.route('/api/buy', methods=['POST'])
def buy_item():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    data = request.json or {}
    item_name = data.get('item_name', '').strip()

    items = get_items()
    item = next((i for i in items if i.get('名前') == item_name), None)
    if not item:
        return jsonify({"success": False, "message": "アイテムが見つかりません。"}), 400

    price = item.get('値段', 0)

    players = get_players()
    player = next((p for p in players if check_user_id(p.get('ユーザid'), user_id)), None)
    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    money = player.get('所持金', 0)
    if money < price:
        return jsonify({"success": False, "message": "所持金が足りません。"}), 400

    # Deduct money
    player['所持金'] = money - price

    # Add item to もちもの
    owned_raw = player.get('もちもの') or ''
    owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
    owned.append(item_name)
    player['もちもの'] = ','.join(owned)

    save_players(players)

    return jsonify({
        "success": True,
        "message": f"「{item_name}」を購入しました！",
        "money": player['所持金'],
        "owned_items": owned
    })


# Shop API: 売却
@app.route('/api/sell', methods=['POST'])
def sell_item():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    data = request.json or {}
    item_name = data.get('item_name', '').strip()

    sell_price = 0
    if item_name == "ちからのもと":
        sell_price = 2000
    else:
        items = get_items()
        item = next((i for i in items if i.get('名前') == item_name), None)
        if not item:
            return jsonify({"success": False, "message": "アイテムが見つかりません。"}), 400
        sell_price = item.get('値段', 0) // 2

    players = get_players()
    player = next((p for p in players if check_user_id(p.get('ユーザid'), user_id)), None)
    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    owned_raw = player.get('もちもの') or ''
    owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]

    if item_name not in owned:
        return jsonify({"success": False, "message": "そのアイテムを所持していません。"}), 400

    # Remove one instance
    owned.remove(item_name)
    player['もちもの'] = ','.join(owned)

    # Add sell price
    player['所持金'] = player.get('所持金', 0) + sell_price

    save_players(players)

    return jsonify({
        "success": True,
        "message": f"「{item_name}」を{sell_price}円で売却しました！",
        "money": player['所持金'],
        "owned_items": owned
    })


@app.route('/api/use_power_source', methods=['POST'])
def use_power_source():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    data = request.json or {}
    poke_index = data.get('poke_index')
    stat_type = data.get('stat_type') # 'hp', 'attack', 'defense', 'sp_attack', 'sp_defense'

    if stat_type not in ['hp', 'attack', 'defense', 'sp_attack', 'sp_defense']:
        return jsonify({"success": False, "message": "不正なステータスタイプです。"}), 400

    players = get_players()
    player = next((p for p in players if check_user_id(p.get('ユーザid'), user_id)), None)
    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    owned_raw = player.get('もちもの') or ''
    owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
    if "ちからのもと" not in owned:
        return jsonify({"success": False, "message": "ちからのもとを持っていません。"}), 400

    p_list = player.get('ポケモン', [])
    if poke_index is None or poke_index < 0 or poke_index >= len(p_list):
        return jsonify({"success": False, "message": "対象のポケモンが見つかりません。"}), 400

    poke = p_list[poke_index]
    boost_key = f"{stat_type}_boost"
    poke[boost_key] = poke.get(boost_key, 0) + 3

    # Consume power source
    owned.remove("ちからのもと")
    player['もちもの'] = ','.join(owned)

    save_players(players)

    # Translate status key for message
    stat_names = {
        'hp': 'HP',
        'attack': '攻撃',
        'defense': '防御',
        'sp_attack': '特攻',
        'sp_defense': '特防'
    }

    return jsonify({
        "success": True,
        "message": f"{poke['名前']}の{stat_names[stat_type]}が3上昇した！",
        "owned_items": owned,
        "pokemon": player.get('ポケモン', [])
    })


# Admin routes
@app.route('/api/admin/pending', methods=['GET'])
def admin_pending():
    players = get_players()
    pokemon_list = get_pokemon_list()
    all_poke_names = [p.get('名前') for p in pokemon_list if p.get('名前')]
    
    pending = []
    for p in players:
        p_list = p.get('ポケモン', [])
        p1 = p_list[0].get('名前') if len(p_list) > 0 else None
        p2 = p_list[1].get('名前') if len(p_list) > 1 else None
        wish1 = p.get('希望1')
        
        if wish1 and len(p_list) < 2:
            step = len(p_list) + 1 # 1st or 2nd pokemon decision
            pending.append({
                "user_id": p.get('ユーザid'),
                "name": p.get('名前'),
                "step": step,
                "wishes": [p.get(f'希望{i}') for i in range(1, 5)],
                "pokemon1": p1,
                "pokemon2": p2
            })
    return jsonify({
        "success": True, 
        "pending": pending,
        "all_pokemons": all_poke_names
    })

@app.route('/api/admin/approve', methods=['POST'])
def admin_approve():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()
    pokemon = data.get('pokemon', '').strip() or data.get('pokemon1', '').strip()

    if not user_id or not pokemon:
        return jsonify({"success": False, "message": "ユーザーID、割当ポケモンを指定してください。"}), 400

    pokemon_list = get_pokemon_list()
    players = get_players()

    found = False
    for p in players:
        if check_user_id(p.get('ユーザid'), user_id):
            p_list = p.get('ポケモン', [])
            if len(p_list) >= 2:
                return jsonify({"success": False, "message": "このユーザーは既に2体のポケモンを割り当てられています。"}), 400
            
            default_moves = []
            master_poke = next((pk for pk in pokemon_list if pk.get('名前') == pokemon), None)
            if master_poke:
                for zn in ["１", "２", "３", "４", "５"]:
                    m_name = master_poke.get(f'わざ{zn}')
                    if m_name:
                        default_moves.append(str(m_name).strip())
            default_moves = default_moves[:4]
            while len(default_moves) < 4:
                default_moves.append("-")
            
            if 'ポケモン' not in p or not isinstance(p['ポケモン'], list):
                p['ポケモン'] = []

            p['ポケモン'].append({
                "名前": pokemon,
                "レベル": 50,
                "もちもの": None,
                "わざ": default_moves
            })

            # Clear wishes after approval so player can select next wishes or move to active
            for i in range(1, 6):
                if f'希望{i}' in p:
                    p[f'希望{i}'] = None

            found = True
            break

    if not found:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    save_players(players)

    return jsonify({
        "success": True,
        "message": f"ユーザー '{user_id}' に {pokemon} を割り当てて承認しました。"
    })

@app.route('/api/admin/export_wishes_csv', methods=['GET'])
def export_wishes_csv():
    import csv
    import io
    from flask import Response

    players = get_players()
    
    output = io.StringIO()
    # Add BOM for Excel UTF-8 compatibility
    output.write('\ufeff')
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['名前', '第一希望', '第二希望', '第三希望', '第四希望'])
    
    for p in players:
        name = p.get('名前') or p.get('ユーザid') or ''
        w1 = p.get('希望1') or ''
        w2 = p.get('希望2') or ''
        w3 = p.get('希望3') or ''
        w4 = p.get('希望4') or ''
        writer.writerow([name, w1, w2, w3, w4])
        
    response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8-sig')
    response.headers['Content-Disposition'] = 'attachment; filename=wishes.csv'
    return response

@app.route('/api/admin/export_damage_csv', methods=['GET'])
def export_damage_csv():
    import csv
    import io
    from flask import Response

    players = get_players()
    
    output = io.StringIO()
    # Add BOM for Excel UTF-8 compatibility
    output.write('\ufeff')
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['名前', '与ダメージ'])
    
    for p in players:
        name = p.get('名前') or p.get('ユーザid') or ''
        dmg = p.get('与ダメージ', 0)

        # Include ongoing active battle damage if a battle is currently in progress
        if active_battle.get("active"):
            pid = p.get('ユーザid')
            pname = p.get('名前')
            p_a = active_battle.get("player_a")
            p_b = active_battle.get("player_b")
            if (p_a and (check_user_id(pid, p_a) or check_user_id(pname, p_a))):
                dmg += active_battle.get("a_damage", 0)
            elif (p_b and (check_user_id(pid, p_b) or check_user_id(pname, p_b))):
                dmg += active_battle.get("b_damage", 0)

        writer.writerow([name, dmg])
        
    response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8-sig')
    response.headers['Content-Disposition'] = 'attachment; filename=damage.csv'
    return response

@app.route('/api/admin/batch_approve_csv', methods=['POST'])
def batch_approve_csv():
    import csv
    import io

    if 'file' in request.files:
        file_obj = request.files['file']
        content = file_obj.read().decode('utf-8-sig', errors='ignore')
    else:
        data = request.json or {}
        content = data.get('csv_text', '')

    if not content.strip():
        return jsonify({"success": False, "message": "CSVデータが空です。"}), 400

    pokemon_list = get_pokemon_list()
    players = get_players()

    reader = csv.reader(io.StringIO(content))
    
    success_count = 0
    errors = []

    for row_idx, row in enumerate(reader, start=1):
        if not row or len(row) < 2:
            continue
        
        # Header check
        name_input = row[0].strip()
        poke_input = row[1].strip()
        if row_idx == 1 and (name_input in ['名前', 'ユーザid', 'ユーザーID', 'user_id', 'ID'] or poke_input in ['ポケモン', '割当ポケモン', '決定ポケモン']):
            continue
        
        if not name_input or not poke_input:
            continue

        # Match player by name or user_id
        target_player = None
        for p in players:
            if (p.get('名前') and p.get('名前').strip() == name_input) or check_user_id(p.get('ユーザid'), name_input):
                target_player = p
                break

        if not target_player:
            errors.append(f"行 {row_idx}: ユーザー '{name_input}' が見つかりません。")
            continue

        p_list = target_player.get('ポケモン', [])
        if len(p_list) >= 2:
            errors.append(f"行 {row_idx}: ユーザー '{name_input}' は既に2体所持しています。")
            continue

        # Prepare default moves
        default_moves = []
        master_poke = next((pk for pk in pokemon_list if pk.get('名前') == poke_input), None)
        if master_poke:
            for zn in ["１", "２", "３", "４", "５"]:
                m_name = master_poke.get(f'わざ{zn}')
                if m_name:
                    default_moves.append(str(m_name).strip())
        default_moves = default_moves[:4]
        while len(default_moves) < 4:
            default_moves.append("-")

        if 'ポケモン' not in target_player or not isinstance(target_player['ポケモン'], list):
            target_player['ポケモン'] = []

        target_player['ポケモン'].append({
            "名前": poke_input,
            "レベル": 50,
            "もちもの": None,
            "わざ": default_moves
        })

        # Clear wishes
        for i in range(1, 6):
            if f'希望{i}' in target_player:
                target_player[f'希望{i}'] = None

        success_count += 1

    if success_count > 0:
        save_players(players)

    msg = f"{success_count} 名の割当を完了しました。"
    if errors:
        msg += f" (エラー: {len(errors)}件)"

    return jsonify({
        "success": True,
        "message": msg,
        "success_count": success_count,
        "errors": errors
    })

# Shop API: 装備
@app.route('/api/equip', methods=['POST'])
def equip_item():
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"success": False, "message": "ログインしていません。"}), 401
        
        data = request.json or {}
        poke_index = data.get('poke_index') # 0 or 1
        item_name = data.get('item_name') # string or None (unequip)

        players = get_players()
        player = next((p for p in players if check_user_id(p.get('ユーザid'), user_id)), None)
        if not player:
            return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

        p_list = player.get('ポケモン', [])
        if poke_index is None or poke_index < 0 or poke_index >= len(p_list):
            return jsonify({"success": False, "message": "対象のポケモンが見つかりません。"}), 400

        poke = p_list[poke_index]
        old_item = poke.get('もちもの')

        owned_raw = player.get('もちもの') or ''
        owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]

        if item_name:
            if item_name not in owned:
                return jsonify({"success": False, "message": "そのアイテムを所持していません。"}), 400
            owned.remove(item_name)
            poke['もちもの'] = item_name
        else:
            poke['もちもの'] = None

        if old_item:
            owned.append(old_item)

        player['もちもの'] = ','.join(owned)
        save_players(players)

        return jsonify({
            "success": True,
            "message": f"{poke['名前']}に「{item_name or 'なし'}」を装備しました！",
            "owned_items": owned,
            "pokemon": p_list
        })
    except Exception as e:
        print(f"Error in equip: {e}")
        return jsonify({"success": False, "message": f"装備エラー: {str(e)}"}), 500

# Shop API: わざマシン使用
@app.route('/api/use_tm', methods=['POST'])
def use_tm():
    try:
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"success": False, "message": "ログインしていません。"}), 401
        
        data = request.json or {}
        poke_index = data.get('poke_index')
        tm_name = data.get('tm_name') # e.g. "わざマシン10"
        move_index = data.get('move_index') # 0-3

        players = get_players()
        player = next((p for p in players if check_user_id(p.get('ユーザid'), user_id)), None)
        if not player:
            return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

        p_list = player.get('ポケモン', [])
        if poke_index is None or poke_index < 0 or poke_index >= len(p_list):
            return jsonify({"success": False, "message": "対象のポケモンが見つかりません。"}), 400

        owned_raw = player.get('もちもの') or ''
        owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
        if tm_name not in owned:
            return jsonify({"success": False, "message": "わざマシンを持っていません。"}), 400

        # Validate TM (if starts with standard prefixes, skip master check, otherwise check category)
        is_valid_tm = False
        if tm_name.startswith("わざマシン") or tm_name.startswith("わざましん"):
            is_valid_tm = True
        else:
            items = get_items()
            tm_item = next((i for i in items if i.get('名前') == tm_name), None)
            if tm_item and tm_item.get('分類') == 'わざマシン':
                is_valid_tm = True

        if not is_valid_tm:
            return jsonify({"success": False, "message": "有効なわざマシンではありません。"}), 400

        move_name = None
        match = re.search(r'\(([^)]+)\)', tm_name)
        if match:
            move_name = match.group(1).strip()
        else:
            move_name = tm_name.replace("わざマシン", "").replace("わざましん", "")
            move_name = move_name.replace(" ", "").replace("　", "").strip()
            if not move_name:
                move_name = tm_name

        poke = p_list[poke_index]
        poke_moves = poke.get('わざ', ["-", "-", "-", "-"])
        
        # Safe type conversions if moves are stored as a string or other formats
        if isinstance(poke_moves, str):
            poke_moves = [m.strip() for m in poke_moves.split(',') if m.strip()]
        elif not isinstance(poke_moves, list):
            poke_moves = ["-", "-", "-", "-"]

        while len(poke_moves) < 4:
            poke_moves.append("-")

        old_move = poke_moves[move_index]
        poke_moves[move_index] = move_name
        poke['わざ'] = poke_moves

        # Consume TM
        owned.remove(tm_name)
        player['もちもの'] = ','.join(owned)

        save_players(players)

        return jsonify({
            "success": True,
            "message": f"{poke['名前']}は {old_move} を忘れて、{move_name} を覚えた！",
            "owned_items": owned,
            "pokemon": p_list
        })
    except Exception as e:
        print(f"Error in use_tm: {e}")
        return jsonify({"success": False, "message": f"わざマシン使用エラー: {str(e)}"}), 500

@app.route('/battle_view')
@app.route('/battleview')
def battle_view():
    return render_template('battle_view.html')


@app.route('/api/battle/join', methods=['POST'])
def battle_join():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    battle_waiting_players.add(user_id)
    save_battle_state()
    return jsonify({"success": True, "message": "バトル待機列に参加しました。"})


@app.route('/api/battle/leave', methods=['POST'])
def battle_leave():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    if user_id in battle_waiting_players:
        battle_waiting_players.remove(user_id)
    save_battle_state()
    return jsonify({"success": True, "message": "バトル待機列から退出しました。"})


@app.route('/api/battle/status', methods=['GET'])
def battle_status():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    role = None
    if active_battle["active"]:
        if check_user_id(active_battle["player_a"], user_id):
            role = "A"
        elif check_user_id(active_battle["player_b"], user_id):
            role = "B"

    # Is the user waiting?
    waiting = user_id in battle_waiting_players

    res = {
        "success": True,
        "active": active_battle["active"],
        "waiting": waiting,
        "role": role,
        "last_confirmed_score": active_battle["last_confirmed_score"]
    }

    if role:
        my_pokes = active_battle["a_pokemon"] if role == "A" else active_battle["b_pokemon"]
        opp_pokes = active_battle["b_pokemon"] if role == "A" else active_battle["a_pokemon"]
        my_idx = active_battle["a_active_idx"] if role == "A" else active_battle["b_active_idx"]
        opp_idx = active_battle["b_active_idx"] if role == "A" else active_battle["a_active_idx"]
        my_move = active_battle["a_selected_move"] if role == "A" else active_battle["b_selected_move"]
        opp_move = active_battle["b_selected_move"] if role == "A" else active_battle["a_selected_move"]
        my_swapped = active_battle["a_swapped"] if role == "A" else active_battle["b_swapped"]

        res.update({
            "my_pokemon": my_pokes,
            "opp_pokemon": opp_pokes,
            "my_active_idx": my_idx,
            "opp_active_idx": opp_idx,
            "my_selected_move": my_move,
            "opp_selected_move": opp_move,
            "my_swapped": my_swapped,
            "swap_requested": active_battle["swap_request"] == role,
            "target_player": active_battle["target_player"],
            "messages": active_battle["messages"][-5:] if active_battle["messages"] else []
        })

    return jsonify(res)


@app.route('/api/battle/select_move', methods=['POST'])
def battle_select_move():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    if not active_battle["active"]:
        return jsonify({"success": False, "message": "現在アクティブなバトルはありません。"}), 400

    data = request.json or {}
    move_name = data.get('move_name')
    move_power = data.get('move_power', 0)
    move_type = data.get('move_type', 'ノーマル')

    role = None
    if check_user_id(active_battle["player_a"], user_id):
        role = "A"
    elif check_user_id(active_battle["player_b"], user_id):
        role = "B"

    if not role:
        return jsonify({"success": False, "message": "あなたはこの対戦のプレイヤーではありません。"}), 400

    move_data = {
        "name": move_name,
        "power": move_power,
        "type": move_type
    }

    if role == "A":
        active_battle["a_selected_move"] = move_data
    else:
        active_battle["b_selected_move"] = move_data

    save_battle_state()
    return jsonify({"success": True, "message": "わざを選択しました。審査を待っています。"})


@app.route('/api/battle/cancel_move', methods=['POST'])
def battle_cancel_move():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    if not active_battle["active"]:
        return jsonify({"success": False, "message": "現在アクティブなバトルはありません。"}), 400

    role = None
    if check_user_id(active_battle["player_a"], user_id):
        role = "A"
    elif check_user_id(active_battle["player_b"], user_id):
        role = "B"

    if not role:
        return jsonify({"success": False, "message": "あなたはこの対戦のプレイヤーではありません。"}), 400

    if role == "A":
        active_battle["a_selected_move"] = None
        if active_battle.get("target_player") == "A":
            active_battle["target_player"] = None
            active_battle["scores"] = []
            active_battle["voted_graders"] = []
    else:
        active_battle["b_selected_move"] = None
        if active_battle.get("target_player") == "B":
            active_battle["target_player"] = None
            active_battle["scores"] = []
            active_battle["voted_graders"] = []

    save_battle_state()
    return jsonify({"success": True, "message": "選択したわざを取り消しました。"})


@app.route('/api/battle/request_swap', methods=['POST'])
def battle_request_swap():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    if not active_battle["active"]:
        return jsonify({"success": False, "message": "現在アクティブなバトルはありません。"}), 400

    role = None
    if check_user_id(active_battle["player_a"], user_id):
        role = "A"
    elif check_user_id(active_battle["player_b"], user_id):
        role = "B"

    if not role:
        return jsonify({"success": False, "message": "あなたはこの対戦のプレイヤーではありません。"}), 400

    already_swapped = active_battle["a_swapped"] if role == "A" else active_battle["b_swapped"]
    if already_swapped:
        return jsonify({"success": False, "message": "交代は1回までしかできません。"}), 400

    active_battle["swap_request"] = role
    save_battle_state()
    return jsonify({"success": True, "message": "管理者に交代を申請しました。"})


@app.route('/api/battle/grader/join', methods=['POST'])
def grader_join():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    grading_viewers.add(user_id)
    save_battle_state()
    return jsonify({"success": True, "message": "採点画面に入りました。"})


@app.route('/api/battle/grader/leave', methods=['POST'])
def grader_leave():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    if user_id in grading_viewers:
        grading_viewers.remove(user_id)
    save_battle_state()
    return jsonify({"success": True, "message": "採点画面を離れました。"})


def distribute_chikara_no_moto(players_data, active_battle):
    exclude_list = active_battle.get("exclude_chikara", [])
    player_a_id = active_battle.get("player_a")
    player_b_id = active_battle.get("player_b")

    p_a = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_a_id) or check_user_id(p.get('名前'), player_a_id)), None)
    p_b = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_b_id) or check_user_id(p.get('名前'), player_b_id)), None)

    awarded_names = []
    if "A" not in exclude_list and p_a:
        owned_raw = p_a.get('もちもの') or ''
        owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
        owned.extend(["ちからのもと", "ちからのもと"])
        p_a['もちもの'] = ','.join(owned)
        awarded_names.append(p_a.get('名前', 'プレイヤーA'))

    if "B" not in exclude_list and p_b:
        owned_raw = p_b.get('もちもの') or ''
        owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
        owned.extend(["ちからのもと", "ちからのもと"])
        p_b['もちもの'] = ','.join(owned)
        awarded_names.append(p_b.get('名前', 'プレイヤーB'))

    return awarded_names

def reset_active_battle_data():
    active_battle["active"] = False
    active_battle["player_a"] = None
    active_battle["player_b"] = None
    active_battle["a_pokemon"] = []
    active_battle["b_pokemon"] = []
    active_battle["a_active_idx"] = 0
    active_battle["b_active_idx"] = 0
    active_battle["a_selected_move"] = None
    active_battle["b_selected_move"] = None
    active_battle["a_damage"] = 0
    active_battle["b_damage"] = 0
    active_battle["a_swapped"] = False
    active_battle["b_swapped"] = False
    active_battle["swap_request"] = None
    active_battle["target_player"] = None
    active_battle["scores"] = []
    active_battle["voted_graders"] = []
    active_battle["last_calculated_score"] = 0
    active_battle["last_confirmed_score"] = None
    active_battle["exclude_chikara"] = []

def confirm_score_internal(forced_score=None):
    if not active_battle["active"]:
        return False, "アクティブなバトルはありません。"

    # Save snapshot for undo capability
    global previous_battle_state, previous_players_state
    import copy
    previous_battle_state = copy.deepcopy(active_battle)
    previous_players_state = copy.deepcopy(get_players())

    if forced_score is not None:
        score = forced_score
    else:
        score = calculate_score(active_battle["scores"])

    target = active_battle.get("target_player")
    if not target or target == "None":
        return False, "審査対象が選択されていません。"

    if target == "Other":
        # Grader only / Other Player mode
        active_battle["last_confirmed_score"] = score
        active_battle["last_calculated_score"] = score
        active_battle["messages"].append(f"採点結果: {score}点！")
        active_battle["target_player"] = None
        active_battle["scores"] = []
        active_battle["voted_graders"] = []
        save_battle_state()
        return True, f"得点 {score} 点を確定しました。"

    # Player target mode
    active_battle["last_confirmed_score"] = None  # Do not display score in battle_view
    active_battle["last_calculated_score"] = score

    # Attacker and Defender
    attacker_role = target
    defender_role = "B" if attacker_role == "A" else "A"

    att_move = active_battle["a_selected_move"] if attacker_role == "A" else active_battle["b_selected_move"]
    if not att_move:
        return False, "攻撃側のわざが選択されていません。"

    att_pokes = active_battle["a_pokemon"] if attacker_role == "A" else active_battle["b_pokemon"]
    def_pokes = active_battle["b_pokemon"] if attacker_role == "A" else active_battle["a_pokemon"]

    att_idx = active_battle["a_active_idx"] if attacker_role == "A" else active_battle["b_active_idx"]
    def_idx = active_battle["b_active_idx"] if attacker_role == "A" else active_battle["a_active_idx"]

    attacker_poke = att_pokes[att_idx]
    defender_poke = def_pokes[def_idx]

    move_power = att_move.get('power') or 0
    move_name = att_move.get('name')
    move_type = att_move.get('type')

    # Success check: score >= move_power
    success = score >= move_power

    players_data = get_players()
    att_player_name = next((p.get('名前') for p in players_data if p.get('ユーザid') == active_battle[f"player_{attacker_role.lower()}"]), "プレイヤー")

    active_battle["messages"].append(f"{att_player_name}の {attacker_poke['name']}の {move_name}！")

    if success:
        att_item = attacker_poke.get('item')
        category = '物理'
        for m in attacker_poke.get('moves', []):
            if m.get('name') == move_name:
                category = m.get('category', '物理')
                break

        # 1. Type boost items
        type_boost_item_map = {
            "りゅうのキバ": ("ドラゴン", 1.1),
            "ようせいのハネ": ("フェアリー", 1.1),
            "やわらかいすな": ("じめん", 1.1),
            "もくたん": ("ほのお", 1.1),
            "メタルコート": ("はがね", 1.1),
            "まがったスプーン": ("エスパー", 1.1),
            "のろいのおふだ": ("ゴースト", 1.1),
            "とけないこおり": ("こおり", 1.1),
            "どくバリ": ("どく", 1.1),
            "するどいくちばし": ("ひこう", 1.1),
            "しんぴのしずく": ("みず", 1.1),
            "シルクのスカーフ": ("ノーマル", 1.1),
            "じしゃく": ("でんき", 1.1),
            "くろおび": ("かくとう", 1.1),
            "くろいメガネ": ("あく", 1.1),
            "きせきのタネ": ("くさ", 1.1),
            "かたいいし": ("いわ", 1.1),
        }
        if att_item in type_boost_item_map:
            b_type, b_mult = type_boost_item_map[att_item]
            if move_type == b_type:
                active_battle["messages"].append(f"もちもの”{att_item}”が発動！{get_item_effect_text(att_item)}")

        # 2. Choice items (Set choice lock without appending activation messages)
        if att_item in ('こだわりハチマキ', 'こだわりメガネ') and not attacker_poke.get('choice_lock'):
            attacker_poke['choice_lock'] = move_name

        # 3. Life orb
        if att_item == 'いのちのたま':
            active_battle["messages"].append(f"もちもの”{att_item}”が発動！{get_item_effect_text(att_item)}")

        # 4. Type-resist berries
        type_berry_map = {
            "フェアリー": "ロゼルのみ",
            "くさ": "リンドのみ",
            "はがね": "リリバのみ",
            "いわ": "ヨロギのみ",
            "かくとう": "ヨプのみ",
            "こおり": "ヤチェのみ",
            "ノーマル": "ホズのみ",
            "どく": "ビアーのみ",
            "ドラゴン": "ハバンのみ",
            "ひこう": "バコウのみ",
            "あく": "ナモのみ",
            "むし": "タンガのみ",
            "でんき": "ソクノのみ",
            "じめん": "シュカのみ",
            "ゴースト": "カシブのみ",
            "ほのお": "オッカのみ",
            "エスパー": "ウタンのみ",
            "みず": "イトケのみ"
        }
        def_item = defender_poke.get('item')
        if def_item and type_berry_map.get(move_type) == def_item:
            active_battle["messages"].append(f"もちもの”{def_item}”が発動！{get_item_effect_text(def_item)}")

        damage = calculate_battle_damage(attacker_poke, defender_poke, att_move)

        if def_item and type_berry_map.get(move_type) == def_item:
            defender_poke['item'] = None

        # 5. Focus sash
        if def_item == 'きあいのタスキ' and defender_poke['hp'] == defender_poke['max_hp'] and damage >= defender_poke['hp']:
            damage = defender_poke['hp'] - 1
            active_battle["messages"].append(f"もちもの”{def_item}”が発動！{get_item_effect_text(def_item)}")
            defender_poke['item'] = None

        mult, eff_msg = get_effectiveness(move_type, [defender_poke.get('type1'), defender_poke.get('type2')])
        defender_poke['hp'] = max(0, defender_poke['hp'] - damage)
        if attacker_role == "A":
            active_battle["a_damage"] = active_battle.get("a_damage", 0) + damage
        else:
            active_battle["b_damage"] = active_battle.get("b_damage", 0) + damage
        active_battle["messages"].append(f"わざ成功！{defender_poke['name']}に {damage} ダメージ！")
        if eff_msg:
            active_battle["messages"].append(eff_msg)

        # 6. Shell Bell
        if att_item == 'かいがらのすず' and attacker_poke['hp'] > 0 and damage > 0:
            heal_amt = damage // 4
            if heal_amt > 0:
                attacker_poke['hp'] = min(attacker_poke['max_hp'], attacker_poke['hp'] + heal_amt)
                active_battle["messages"].append(f"もちもの”かいがらのすず”が発動！{get_item_effect_text('かいがらのすず')}")
                active_battle["messages"].append(f"{attacker_poke['name']}のHPが {heal_amt} 回復した！")

        # 7. Rocky Helmet
        if def_item == 'ゴツゴツメット' and attacker_poke['hp'] > 0:
            recoil = attacker_poke['max_hp'] // 10
            attacker_poke['hp'] = max(0, attacker_poke['hp'] - recoil)
            active_battle["messages"].append(f"もちもの”ゴツゴツメット”が発動！{get_item_effect_text('ゴツゴツメット')}")
            active_battle["messages"].append(f"{attacker_poke['name']}は ゴツゴツメット で {recoil} ダメージを受けた！")

        # 8. Life Orb recoil
        if att_item == 'いのちのたま' and attacker_poke['hp'] > 0:
            recoil = attacker_poke['max_hp'] // 8
            attacker_poke['hp'] = max(0, attacker_poke['hp'] - recoil)
            active_battle["messages"].append(f"{attacker_poke['name']}は いのちのたま の反動で {recoil} ダメージを受けた！")

        # 9. Leftovers
        if att_item == 'たべのこし' and attacker_poke['hp'] > 0:
            heal_amt = attacker_poke['max_hp'] // 12
            attacker_poke['hp'] = min(attacker_poke['max_hp'], attacker_poke['hp'] + heal_amt)
            active_battle["messages"].append(f"もちもの”たべのこし”が発動！{get_item_effect_text('たべのこし')}")
            active_battle["messages"].append(f"{attacker_poke['name']}のHPが {heal_amt} 回復した！")

        # 10. Oran Berry (オボンのみ)
        for poke in [attacker_poke, defender_poke]:
            if poke['hp'] > 0 and poke['hp'] <= poke['max_hp'] // 2 and poke.get('item') == 'オボンのみ':
                heal_amt = poke['max_hp'] // 3
                poke['hp'] = min(poke['max_hp'], poke['hp'] + heal_amt)
                active_battle["messages"].append(f"もちもの”オボンのみ”が発動！{get_item_effect_text('オボンのみ')}")
                active_battle["messages"].append(f"{poke['name']}のHPが {heal_amt} 回復した！")
                poke['item'] = None

        # Check defender fainted
        if defender_poke['hp'] <= 0:
            defender_poke['choice_lock'] = None
            active_battle["messages"].append(f"{defender_poke['name']}はたおれた！")
            
            # Switch to 2nd pokemon if available
            def_active_idx_key = f"{defender_role.lower()}_active_idx"
            current_def_idx = active_battle[def_active_idx_key]
            if current_def_idx == 0 and len(def_pokes) > 1:
                active_battle[def_active_idx_key] = 1
                active_battle["messages"].append(f"2体目の {def_pokes[1]['name']} がくりだされた！")
            else:
                # Battle over! Winner is attacker
                winner_role = attacker_role
                loser_role = defender_role
                
                winner_id = active_battle[f"player_{winner_role.lower()}"]
                loser_id = active_battle[f"player_{loser_role.lower()}"]

                p_winner = next((p for p in players_data if check_user_id(p.get('ユーザid'), winner_id) or check_user_id(p.get('名前'), winner_id)), None)
                p_loser = next((p for p in players_data if check_user_id(p.get('ユーザid'), loser_id) or check_user_id(p.get('名前'), loser_id)), None)

                # Transfer money: winner gets half of loser's money
                loser_money = p_loser.get('所持金', 0) if p_loser else 0
                prize = loser_money // 2
                if p_loser:
                    p_loser['所持金'] = loser_money - prize
                if p_winner:
                    p_winner['所持金'] = p_winner.get('所持金', 0) + prize

                # Both get Power Sources according to exclude settings
                awarded_names = distribute_chikara_no_moto(players_data, active_battle)

                # Damage calculation: Winner 1.5x, Loser 0.5x
                winner_raw_dmg = active_battle.get(f"{winner_role.lower()}_damage", 0)
                loser_raw_dmg = active_battle.get(f"{loser_role.lower()}_damage", 0)
                if p_winner:
                    p_winner['与ダメージ'] = p_winner.get('与ダメージ', 0) + int(round(winner_raw_dmg * 1.5))
                if p_loser:
                    p_loser['与ダメージ'] = p_loser.get('与ダメージ', 0) + int(round(loser_raw_dmg * 0.5))

                save_players(players_data)

                if len(awarded_names) == 2:
                    item_msg = "両者に「ちからのもと」が2つ付与されました！"
                elif len(awarded_names) == 1:
                    item_msg = f"{awarded_names[0]}に「ちからのもと」が2つ付与されました！"
                else:
                    item_msg = "ちからのもとの配布はありません。"

                active_battle["messages"].append(f"戦闘終了！ {att_player_name} の勝利！")
                active_battle["messages"].append(f"勝者は敗者の所持金の半分（{prize}円）を獲得し、{item_msg}")
                active_battle["active"] = False

        if active_battle.get("active") and attacker_poke['hp'] <= 0:
            active_battle["messages"].append(f"{attacker_poke['name']}はたおれた！")
            attacker_poke['choice_lock'] = None
            # Switch to 2nd pokemon if available
            att_active_idx_key = f"{attacker_role.lower()}_active_idx"
            current_att_idx = active_battle[att_active_idx_key]
            if current_att_idx == 0 and len(att_pokes) > 1:
                active_battle[att_active_idx_key] = 1
                active_battle["messages"].append(f"2体目の {att_pokes[1]['name']} がくりだされた！")
            else:
                # Battle over! Winner is defender
                winner_role = defender_role
                loser_role = attacker_role
                
                winner_id = active_battle[f"player_{winner_role.lower()}"]
                loser_id = active_battle[f"player_{loser_role.lower()}"]

                p_winner = next((p for p in players_data if check_user_id(p.get('ユーザid'), winner_id) or check_user_id(p.get('名前'), winner_id)), None)
                p_loser = next((p for p in players_data if check_user_id(p.get('ユーザid'), loser_id) or check_user_id(p.get('名前'), loser_id)), None)

                # Transfer money: winner gets half of loser's money
                loser_money = p_loser.get('所持金', 0) if p_loser else 0
                prize = loser_money // 2
                if p_loser:
                    p_loser['所持金'] = loser_money - prize
                if p_winner:
                    p_winner['所持金'] = p_winner.get('所持金', 0) + prize

                # Both get Power Sources according to exclude settings
                awarded_names = distribute_chikara_no_moto(players_data, active_battle)

                # Damage calculation: Winner 1.5x, Loser 0.5x
                winner_raw_dmg = active_battle.get(f"{winner_role.lower()}_damage", 0)
                loser_raw_dmg = active_battle.get(f"{loser_role.lower()}_damage", 0)
                if p_winner:
                    p_winner['与ダメージ'] = p_winner.get('与ダメージ', 0) + int(round(winner_raw_dmg * 1.5))
                if p_loser:
                    p_loser['与ダメージ'] = p_loser.get('与ダメージ', 0) + int(round(loser_raw_dmg * 0.5))

                save_players(players_data)

                if len(awarded_names) == 2:
                    item_msg = "両者に「ちからのもと」が2つ付与されました！"
                elif len(awarded_names) == 1:
                    item_msg = f"{awarded_names[0]}に「ちからのもと」が2つ付与されました！"
                else:
                    item_msg = "ちからのもとの配布はありません。"

                def_player_name = next((p.get('名前') for p in players_data if check_user_id(p.get('ユーザid'), active_battle[f"player_{defender_role.lower()}"]) or check_user_id(p.get('名前'), active_battle[f"player_{defender_role.lower()}"])), "プレイヤー")
                active_battle["messages"].append(f"戦闘終了！ {def_player_name} の勝利！")
                active_battle["messages"].append(f"勝者は敗者の所持金の半分（{prize}円）を獲得し、{item_msg}")
                active_battle["active"] = False
    else:
        active_battle["messages"].append("しかし　わざは　しっぱいした！")

    # Reset move choice and target for next turn
    if attacker_role == "A":
        active_battle["a_selected_move"] = None
    else:
        active_battle["b_selected_move"] = None

    active_battle["target_player"] = None
    active_battle["scores"] = []
    active_battle["voted_graders"] = []

    save_battle_state()
    return True, "結果を確定しました。"


@app.route('/api/battle/grader/submit', methods=['POST'])
def grader_submit():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    data = request.json or {}
    score = data.get('score')
    if score not in [1, 2, 3]:
        return jsonify({"success": False, "message": "点数は1, 2, 3のいずれかである必要があります。"}), 400

    if not active_battle["active"]:
        return jsonify({"success": False, "message": "現在アクティブなバトルはありません。"}), 400

    if user_id in active_battle.get("voted_graders", []):
        return jsonify({"success": False, "message": "既に採点済みです。"}), 400

    # Add grader score
    if len(active_battle["scores"]) < 6:
        active_battle["scores"].append(score)
        if "voted_graders" not in active_battle:
            active_battle["voted_graders"] = []
        active_battle["voted_graders"].append(user_id)

    auto_confirmed = False
    confirm_msg = ""
    if len(active_battle["scores"]) == 6:
        success, confirm_msg = confirm_score_internal()
        if success:
            auto_confirmed = True

    save_battle_state()
    return jsonify({
        "success": True, 
        "message": f"{score}点を送信しました。" + (" (結果を自動確定しました)" if auto_confirmed else ""), 
        "scores_count": len(active_battle["scores"]),
        "auto_confirmed": auto_confirmed,
        "confirm_message": confirm_msg
    })


# --- Admin Battle Control APIs ---

@app.route('/api/admin/battle/status', methods=['GET'])
def admin_battle_status():
    # Return waiting players list, active battle details, score count
    players_data = get_players()
    waiting_list = []
    for pid in battle_waiting_players:
        p_info = next((p for p in players_data if check_user_id(p.get('ユーザid'), pid)), None)
        if p_info:
            waiting_list.append({
                "user_id": pid,
                "name": p_info.get("名前")
            })

    grader_list = []
    for pid in grading_viewers:
        p_info = next((p for p in players_data if check_user_id(p.get('ユーザid'), pid)), None)
        if p_info:
            grader_list.append(p_info.get("名前") or pid)

    players_details = {}
    for role in ["A", "B"]:
        pid = active_battle[f"player_{role.lower()}"]
        if pid:
            p_info = next((p for p in players_data if check_user_id(p.get('ユーザid'), pid)), None)
            if p_info:
                players_details[role] = p_info.get("名前") or pid

    return jsonify({
        "success": True,
        "waiting": waiting_list,
        "graders": grader_list,
        "active_battle": active_battle,
        "players_details": players_details,
        "current_score": calculate_score(active_battle["scores"]) if len(active_battle["scores"]) >= 6 else active_battle.get("last_calculated_score", 0),
        "timer": get_timer_info()
    })


@app.route('/api/admin/timer/control', methods=['POST'])
def admin_timer_control():
    data = request.json or {}
    action = data.get('action') # 'start', 'pause', 'reset'

    if "timer" not in active_battle or not isinstance(active_battle["timer"], dict):
        active_battle["timer"] = {
            "status": "stopped",
            "start_timestamp": None,
            "elapsed_seconds": 0,
            "duration": 300
        }

    timer = active_battle["timer"]
    import time

    if action == 'start':
        if timer.get('status') != 'running':
            timer['status'] = 'running'
            timer['start_timestamp'] = time.time()
            save_battle_state()
        return jsonify({"success": True, "message": "タイマーを開始しました。", "timer": get_timer_info()})

    elif action == 'pause':
        if timer.get('status') == 'running':
            if timer.get('start_timestamp'):
                timer['elapsed_seconds'] = float(timer.get('elapsed_seconds', 0)) + (time.time() - timer['start_timestamp'])
            timer['status'] = 'paused'
            timer['start_timestamp'] = None
            save_battle_state()
        return jsonify({"success": True, "message": "タイマーを一時停止しました。", "timer": get_timer_info()})

    elif action == 'reset':
        timer['status'] = 'stopped'
        timer['start_timestamp'] = None
        timer['elapsed_seconds'] = 0
        save_battle_state()
        return jsonify({"success": True, "message": "タイマーをリセットしました。", "timer": get_timer_info()})

    return jsonify({"success": False, "message": "無効なアクションです。"}), 400


@app.route('/api/admin/battle/set_slide', methods=['POST'])
def admin_set_slide():
    data = request.json or {}
    slide_url = data.get('slide_url', '').strip()
    active_battle["slide_url"] = slide_url if slide_url else None
    save_battle_state()
    return jsonify({"success": True, "message": "スライドURLを更新しました。"})


@app.route('/api/admin/battle/start', methods=['POST'])
def admin_battle_start():
    data = request.json or {}
    player_a = data.get('player_a')
    player_b = data.get('player_b')

    if not player_a or not player_b:
        return jsonify({"success": False, "message": "対戦プレイヤーを2名選択してください。"}), 400

    # Retrieve players data to build pokemon list
    players_data = get_players()
    p_a_data = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_a)), None)
    p_b_data = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_b)), None)

    if not p_a_data or not p_b_data:
        return jsonify({"success": False, "message": "プレイヤーが見つかりません。"}), 400

    # Build copies of their pokemon using game_data logic helper
    # Mock games_data details
    pokemon_list = get_pokemon_list()
    moves_list = get_moves_list()
    moves_map = {m.get('わざ').strip(): m for m in moves_list if m.get('わざ')}

    def build_pokes(p_data):
        res = []
        for p_info in p_data.get('ポケモン', []):
            name = p_info.get('名前')
            master = next((pk for pk in pokemon_list if pk.get('名前') == name), None)
            if not master:
                continue

            hp_boost = p_info.get('hp_boost', 0)
            attack_boost = p_info.get('attack_boost', 0)
            defense_boost = p_info.get('defense_boost', 0)
            sp_attack_boost = p_info.get('sp_attack_boost', 0)
            sp_defense_boost = p_info.get('sp_defense_boost', 0)

            hp = (master.get('HP（H）') or 0) + hp_boost
            attack = (master.get('攻撃（A）') or 0) + attack_boost
            defense = (master.get('防御（B）') or 0) + defense_boost
            sp_attack = (master.get('特攻（C）') or 0) + sp_attack_boost
            sp_defense = (master.get('特防（D）') or 0) + sp_defense_boost

            poke_moves = []
            for m in p_info.get('わざ', []):
                if m and m != "-":
                    m_clean = m.strip()
                    if m_clean in moves_map:
                        poke_moves.append({
                            "name": m_clean,
                            "type": moves_map[m_clean].get('タイプ'),
                            "power": moves_map[m_clean].get('威力') or 0,
                            "category": moves_map[m_clean].get('分類') or '物理'
                        })
            res.append({
                "name": name,
                "番号": master.get('番号'),
                "type1": master.get('タイプ１'),
                "type2": master.get('タイプ2'),
                "max_hp": hp,
                "hp": hp,
                "attack": attack,
                "defense": defense,
                "sp_attack": sp_attack,
                "sp_defense": sp_defense,
                "moves": poke_moves,
                "item": p_info.get('もちもの'),
                "level": p_info.get('レベル', 50),
                "choice_lock": None
            })
        return res

    a_pokes = build_pokes(p_a_data)
    b_pokes = build_pokes(p_b_data)

    if not a_pokes or not b_pokes:
        return jsonify({"success": False, "message": "両プレイヤーのポケモンデータが正しく取得できませんでした。"}), 400

    # Start battle
    active_battle.update({
        "active": True,
        "player_a": player_a,
        "player_b": player_b,
        "a_pokemon": a_pokes,
        "b_pokemon": b_pokes,
        "a_active_idx": 0,
        "b_active_idx": 0,
        "a_selected_move": None,
        "b_selected_move": None,
        "a_damage": 0,
        "b_damage": 0,
        "a_swapped": False,
        "b_swapped": False,
        "swap_request": None,
        "target_player": None,
        "scores": [],
        "voted_graders": [],
        "messages": [f"バトル開始！ {p_a_data.get('名前')} VS {p_b_data.get('名前')}"],
        "last_confirmed_score": None,
        "last_calculated_score": 0,
        "exclude_chikara": []
    })

    # Remove from waiting queues
    if player_a in battle_waiting_players:
        battle_waiting_players.remove(player_a)
    if player_b in battle_waiting_players:
        battle_waiting_players.remove(player_b)

    save_battle_state()
    return jsonify({"success": True, "message": "バトルを開始しました。"})


@app.route('/api/admin/battle/select_target', methods=['POST'])
def admin_battle_select_target():
    data = request.json or {}
    target = data.get('target') # 'A', 'B', 'Other', or None

    if target not in ['A', 'B', 'Other', None]:
        return jsonify({"success": False, "message": "無効なターゲットです。"}), 400

    if target == 'A' and not active_battle.get("a_selected_move"):
        return jsonify({"success": False, "message": "プレイヤーAは技を選択していません。"}), 400
    if target == 'B' and not active_battle.get("b_selected_move"):
        return jsonify({"success": False, "message": "プレイヤーBは技を選択していません。"}), 400

    active_battle["target_player"] = target
    active_battle["scores"] = [] # Reset scores for next target
    active_battle["voted_graders"] = []
    active_battle["last_confirmed_score"] = None
    save_battle_state()
    
    target_name = "未選択"
    if target == 'A':
        target_name = "プレイヤーA"
    elif target == 'B':
        target_name = "プレイヤーB"
    elif target == 'Other':
        target_name = "その他のプレイヤー"
    return jsonify({"success": True, "message": f"審査対象を{target_name}に設定しました。"})


@app.route('/api/admin/battle/approve_swap', methods=['POST'])
def admin_battle_approve_swap():
    if not active_battle["active"]:
        return jsonify({"success": False, "message": "アクティブなバトルはありません。"}), 400

    req = active_battle["swap_request"]
    if not req:
        return jsonify({"success": False, "message": "交代要請はありません。"}), 400

    players_data = get_players()
    if req == "A":
        pokes = active_battle["a_pokemon"]
        if len(pokes) < 2:
            return jsonify({"success": False, "message": "控えのポケモンがいません。"}), 400
        # Check if the fainted pokemon swap or active swap
        old_idx = active_battle["a_active_idx"]
        active_battle["a_active_idx"] = 1 - old_idx
        pokes[old_idx]["choice_lock"] = None
        active_battle["a_swapped"] = True
        active_battle["a_selected_move"] = None
        p_name = next((p.get('名前') for p in players_data if check_user_id(p.get('ユーザid'), active_battle["player_a"])), active_battle["player_a"])
        active_battle["messages"].append(f"{p_name}はポケモンを {pokes[active_battle['a_active_idx']]['name']} に交代した！")
    else:
        pokes = active_battle["b_pokemon"]
        if len(pokes) < 2:
            return jsonify({"success": False, "message": "控えのポケモンがいません。"}), 400
        old_idx = active_battle["b_active_idx"]
        active_battle["b_active_idx"] = 1 - old_idx
        pokes[old_idx]["choice_lock"] = None
        active_battle["b_swapped"] = True
        active_battle["b_selected_move"] = None
        p_name = next((p.get('名前') for p in players_data if check_user_id(p.get('ユーザid'), active_battle["player_b"])), active_battle["player_b"])
        active_battle["messages"].append(f"{p_name}はポケモンを {pokes[active_battle['b_active_idx']]['name']} に交代した！")

    active_battle["swap_request"] = None
    save_battle_state()
    return jsonify({"success": True, "message": "交代を承認しました。"})


@app.route('/api/admin/battle/confirm_score', methods=['POST'])
def admin_battle_confirm_score():
    data = request.json or {}
    forced_score = data.get('forced_score')
    if forced_score is not None:
        try:
            forced_score = int(forced_score)
        except ValueError:
            return jsonify({"success": False, "message": "無効な点数です。"}), 400

    success, msg = confirm_score_internal(forced_score=forced_score)
    if not success:
        return jsonify({"success": False, "message": msg}), 400
    return jsonify({"success": True, "message": msg})


@app.route('/api/admin/battle/update_chikara_exclude', methods=['POST'])
def update_chikara_exclude():
    req_data = request.json or {}
    exclude_list = req_data.get('exclude_chikara', [])
    active_battle['exclude_chikara'] = exclude_list
    save_battle_state()
    return jsonify({"success": True, "exclude_chikara": exclude_list})


@app.route('/api/admin/battle/timeout_end', methods=['POST'])
def admin_battle_timeout_end():
    if not active_battle.get("active"):
        return jsonify({"success": False, "message": "進行中のバトルがありません。"}), 400

    player_a_id = active_battle.get("player_a")
    player_b_id = active_battle.get("player_b")

    if not player_a_id or not player_b_id:
        return jsonify({"success": False, "message": "プレイヤー情報が不足しています。"}), 400

    req_data = request.json or {}
    if 'exclude_chikara' in req_data:
        active_battle['exclude_chikara'] = req_data['exclude_chikara']

    players_data = get_players()
    p_a = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_a_id) or check_user_id(p.get('名前'), player_a_id)), None)
    p_b = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_b_id) or check_user_id(p.get('名前'), player_b_id)), None)

    # Determine Winner by remaining HP % / remaining HP, then damage
    a_pokes = active_battle.get('a_pokemon', [])
    b_pokes = active_battle.get('b_pokemon', [])

    a_hp = sum(max(0, p.get('hp', 0)) for p in a_pokes)
    a_max = sum(max(1, p.get('max_hp', 1)) for p in a_pokes)
    b_hp = sum(max(0, p.get('hp', 0)) for p in b_pokes)
    b_max = sum(max(1, p.get('max_hp', 1)) for p in b_pokes)

    a_pct = (a_hp / a_max) if a_max > 0 else 0
    b_pct = (b_hp / b_max) if b_max > 0 else 0

    a_raw_dmg = active_battle.get("a_damage", 0)
    b_raw_dmg = active_battle.get("b_damage", 0)

    if a_pct > b_pct:
        winner_role, loser_role = "A", "B"
    elif b_pct > a_pct:
        winner_role, loser_role = "B", "A"
    else:
        if a_raw_dmg >= b_raw_dmg:
            winner_role, loser_role = "A", "B"
        else:
            winner_role, loser_role = "B", "A"

    p_winner = p_a if winner_role == "A" else p_b
    p_loser = p_b if winner_role == "A" else p_a
    winner_name = p_winner.get('名前', f'プレイヤー{winner_role}') if p_winner else f'プレイヤー{winner_role}'

    # 1. Money transfer: winner gets half of loser's money
    loser_money = p_loser.get('所持金', 0) if p_loser else 0
    prize = loser_money // 2
    if p_loser:
        p_loser['所持金'] = loser_money - prize
    if p_winner:
        p_winner['所持金'] = p_winner.get('所持金', 0) + prize

    # 2. Chikara no Moto distribution according to exclude_chikara
    awarded_names = distribute_chikara_no_moto(players_data, active_battle)

    # 3. Damage stats (Winner 1.5x, Loser 0.5x)
    winner_raw_dmg = a_raw_dmg if winner_role == "A" else b_raw_dmg
    loser_raw_dmg = b_raw_dmg if winner_role == "A" else a_raw_dmg
    if p_winner:
        p_winner['与ダメージ'] = p_winner.get('与ダメージ', 0) + int(round(winner_raw_dmg * 1.5))
    if p_loser:
        p_loser['与ダメージ'] = p_loser.get('与ダメージ', 0) + int(round(loser_raw_dmg * 0.5))

    save_players(players_data)

    # 4. Message log & Battle state reset
    if len(awarded_names) == 2:
        item_msg = "両者に「ちからのもと」が2つ付与されました。"
    elif len(awarded_names) == 1:
        item_msg = f"{awarded_names[0]}に「ちからのもと」が2つ付与されました。"
    else:
        item_msg = "ちからのもとの配布はありません。"

    active_battle["messages"].append(f"時間切れにより戦闘終了！ {winner_name} の判定勝ち！")
    active_battle["messages"].append(f"勝者は敗者の所持金の半分（{prize}円）を獲得し、{item_msg}")

    # Reset active battle state
    reset_active_battle_data()
    save_battle_state()
    return jsonify({"success": True, "message": f"時間切れ終了を処理しました。（勝者: {winner_name}）"})


@app.route('/api/admin/battle/force_end', methods=['POST'])
def admin_battle_force_end():
    player_a_id = active_battle.get("player_a")
    player_b_id = active_battle.get("player_b")

    if player_a_id or player_b_id:
        a_raw_dmg = active_battle.get("a_damage", 0)
        b_raw_dmg = active_battle.get("b_damage", 0)

        players_data = get_players()
        p_a = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_a_id) or check_user_id(p.get('名前'), player_a_id)), None)
        p_b = next((p for p in players_data if check_user_id(p.get('ユーザid'), player_b_id) or check_user_id(p.get('名前'), player_b_id)), None)

        if p_a:
            p_a['与ダメージ'] = p_a.get('与ダメージ', 0) + int(round(a_raw_dmg * 1.0))
        if p_b:
            p_b['与ダメージ'] = p_b.get('与ダメージ', 0) + int(round(b_raw_dmg * 1.0))

        # NO money transfer and NO Chikara no Moto distribution!
        save_players(players_data)

    active_battle["messages"].append("管理者によってバトルが強制終了されました。（所持金の移動およびちからのもとの配布はありません）")
    reset_active_battle_data()
    return jsonify({"success": True, "message": "バトルを強制終了しました。"})


@app.route('/api/admin/battle/reset_scores', methods=['POST'])
def admin_battle_reset_scores():
    active_battle["scores"] = []
    active_battle["voted_graders"] = []
    active_battle["last_calculated_score"] = 0
    active_battle["messages"].append("管理者によって採点がリセットされました。")
    save_battle_state()
    return jsonify({"success": True, "message": "採点をリセットしました。"})


@app.route('/api/admin/battle/undo_confirm', methods=['POST'])
def admin_battle_undo_confirm():
    global previous_battle_state, previous_players_state
    if not previous_battle_state:
        return jsonify({"success": False, "message": "取り消す履歴がありません。"}), 400

    # Restore players
    if previous_players_state:
        save_players(previous_players_state)

    # Restore active_battle
    global active_battle
    active_battle.clear()
    active_battle.update(previous_battle_state)
    
    active_battle["messages"].append("管理者によって直前の審査が取り消されました。")
    
    previous_battle_state = None
    previous_players_state = None

    save_battle_state()
    return jsonify({"success": True, "message": "直前の審査を取り消しました。"})


@app.route('/api/swap_pokemon', methods=['POST'])
def swap_pokemon():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    players = get_players()
    player = next((p for p in players if check_user_id(p.get('ユーザid'), user_id)), None)
    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    p_list = player.get('ポケモン', [])
    if len(p_list) < 2:
        return jsonify({"success": False, "message": "入れ替えるポケモンが2体いません。"}), 400

    p_list[0], p_list[1] = p_list[1], p_list[0]
    player['ポケモン'] = p_list

    save_players(players)

    return jsonify({"success": True, "message": "ポケモンの順番を入れ替えました。"})


@app.route('/api/battle/viewer/status', methods=['GET'])
def battle_viewer_status():
    players_data = get_players()
    res = {
        "success": True,
        "active": active_battle["active"],
        "target_player": active_battle["target_player"],
        "scores": active_battle["scores"],
        "score_count": len(active_battle["scores"]),
        "messages": active_battle["messages"],
        "slide_url": active_battle.get("slide_url"),
        "timer": get_timer_info()
    }

    if active_battle["active"]:
        p_a_name = next((p.get('名前') for p in players_data if p.get('ユーザid') == active_battle["player_a"]), active_battle["player_a"])
        p_b_name = next((p.get('名前') for p in players_data if p.get('ユーザid') == active_battle["player_b"]), active_battle["player_b"])

        res.update({
            "player_a_name": p_a_name,
            "player_b_name": p_b_name,
            "a_pokemon": active_battle["a_pokemon"],
            "b_pokemon": active_battle["b_pokemon"],
            "a_active_idx": active_battle["a_active_idx"],
            "b_active_idx": active_battle["b_active_idx"],
            "last_confirmed_score": active_battle["last_confirmed_score"]
        })
    return jsonify(res)

@app.route('/api/admin/debug_kv', methods=['GET'])
def debug_kv():
    url, token = get_kv_credentials()
    
    if not url or not token:
        return jsonify({
            "status": "missing_credentials",
            "KV_REST_API_URL_exists": os.environ.get('KV_REST_API_URL') is not None,
            "KV_REST_API_TOKEN_exists": os.environ.get('KV_REST_API_TOKEN') is not None,
            "UPSTASH_REDIS_REST_URL_exists": os.environ.get('UPSTASH_REDIS_REST_URL') is not None,
            "UPSTASH_REDIS_REST_TOKEN_exists": os.environ.get('UPSTASH_REDIS_REST_TOKEN') is not None
        })
        
    try:
        url_clean = url.rstrip('/')
        headers = {'Authorization': f'Bearer {token}'}
        res = requests.post(url_clean, headers=headers, json=["PING"])
        return jsonify({
            "status": "connected",
            "http_status": res.status_code,
            "response": res.json() if res.status_code == 200 else res.text,
            "using_upstash_var": os.environ.get('UPSTASH_REDIS_REST_URL') is not None
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
