import os
import re
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import openpyxl

app = Flask(__name__, template_folder='templates', static_folder='public/static', static_url_path='/static')
CORS(app)
app.secret_key = 'pk_ogiri_secret_key_13579'

def get_current_user_id():
    user_id = request.headers.get('X-User-Id')
    if user_id:
        return user_id.strip()
    return None

def check_user_id(u1, u2):
    if u1 is None or u2 is None:
        return False
    return str(u1).strip() == str(u2).strip()

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
    "a_swapped": False, # Has A swapped manually in this battle?
    "b_swapped": False, # Has B swapped manually in this battle?
    "swap_request": None, # 'A' or 'B' requesting swap
    "target_player": None, # Current grading target: 'A', 'B', or None (no target)
    "scores": [],          # List of grader scores: e.g. [1, 2, 3, 2, 2, 3]
    "voted_graders": [],   # List of user_ids who have already graded in this round
    "messages": [],        # History of battle log messages
    "last_confirmed_score": None,
    "last_calculated_score": 0  # Latest calculated score for admin dashboard
}

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
        '希望4': None,
        '希望5': None
    }
    # Update and save to JSON file
    players.append(new_row)
    save_players(players)

    session['user_id'] = user_id
    return jsonify({
        "success": True,
        "user_id": user_id,
        "message": "登録が完了しました。"
    })

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
    
    # Determine status
    p_list = player.get('ポケモン', [])
    pokemon1 = p_list[0].get('名前') if len(p_list) > 0 else None
    pokemon2 = p_list[1].get('名前') if len(p_list) > 1 else None
    wish1 = player.get('希望1')

    if pokemon1 and pokemon2:
        status = "active"
    elif wish1:
        status = "waiting"
    else:
        status = "select_choices"

    return jsonify({
        "success": True,
        "user_id": user_id,
        "status": status,
        "pokemon1": pokemon1,
        "pokemon2": pokemon2
    })

@app.route('/api/submit_choices', methods=['POST'])
def submit_choices():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    data = request.json or {}
    choices = data.get('choices', [])

    if len(choices) != 5 or len(set(choices)) != 5:
        return jsonify({"success": False, "message": "重複のない5体のポケモンを選択してください。"}), 400

    players = get_players()

    found = False
    for p in players:
        if p.get('ユーザid') == user_id:
            for i, choice in enumerate(choices):
                p[f'希望{i+1}'] = choice
            found = True
            break

    if not found:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    save_players(players)

    return jsonify({"success": True, "status": "waiting"})

@app.route('/api/status', methods=['GET'])
def get_status():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    players = get_players()

    player = None
    for p in players:
        if p.get('ユーザid') == user_id:
            player = p
            break

    if not player:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    p_list = player.get('ポケモン', [])
    pokemon1 = p_list[0].get('名前') if len(p_list) > 0 else None
    pokemon2 = p_list[1].get('名前') if len(p_list) > 1 else None
    wish1 = player.get('希望1')

    if pokemon1 and pokemon2:
        status = "active"
    elif wish1:
        status = "waiting"
    else:
        status = "select_choices"

    return jsonify({
        "success": True,
        "status": status,
        "pokemon1": pokemon1,
        "pokemon2": pokemon2
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
        if p.get('ユーザid') == user_id:
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
    player = next((p for p in players if p.get('ユーザid') == user_id), None)
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
    player = next((p for p in players if p.get('ユーザid') == user_id), None)
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
    player = next((p for p in players if p.get('ユーザid') == user_id), None)
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
    player = next((p for p in players if p.get('ユーザid') == user_id), None)
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
        # pending if they have wishes but don't have pokemon1 or pokemon2 assigned
        if p.get('希望1') and (not p1 or not p2):
            pending.append({
                "user_id": p.get('ユーザid'),
                "name": p.get('名前'),
                "wishes": [p.get(f'希望{i}') for i in range(1, 6)],
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
    pokemon1 = data.get('pokemon1', '').strip()
    pokemon2 = data.get('pokemon2', '').strip()

    if not user_id or not pokemon1 or not pokemon2:
        return jsonify({"success": False, "message": "ユーザーID、ポケモン1、ポケモン2を指定してください。"}), 400

    pokemon_list = get_pokemon_list()
    players = get_players()

    found = False
    for p in players:
        if p.get('ユーザid') == user_id:
            p['ポケモン'] = []
            for poke_name in [pokemon1, pokemon2]:
                default_moves = []
                master_poke = next((pk for pk in pokemon_list if pk.get('名前') == poke_name), None)
                if master_poke:
                    for zn in ["１", "２", "３", "４", "５"]:
                        m_name = master_poke.get(f'わざ{zn}')
                        if m_name:
                            default_moves.append(str(m_name).strip())
                default_moves = default_moves[:4]
                while len(default_moves) < 4:
                    default_moves.append("-")
                
                p['ポケモン'].append({
                    "名前": poke_name,
                    "レベル": 50,
                    "もちもの": None,
                    "わざ": default_moves
                })
            found = True
            break

    if not found:
        return jsonify({"success": False, "message": "ユーザーが見つかりません。"}), 400

    save_players(players)

    return jsonify({
        "success": True,
        "message": f"ユーザー '{user_id}' に {pokemon1} と {pokemon2} を割り当てて承認しました。"
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
        player = next((p for p in players if p.get('ユーザid') == user_id), None)
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
        player = next((p for p in players if p.get('ユーザid') == user_id), None)
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
def battle_view():
    return render_template('battle_view.html')


@app.route('/api/battle/join', methods=['POST'])
def battle_join():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    battle_waiting_players.add(user_id)
    return jsonify({"success": True, "message": "バトル待機列に参加しました。"})


@app.route('/api/battle/leave', methods=['POST'])
def battle_leave():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    if user_id in battle_waiting_players:
        battle_waiting_players.remove(user_id)
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
    if active_battle["player_a"] == user_id:
        role = "A"
    elif active_battle["player_b"] == user_id:
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

    return jsonify({"success": True, "message": "わざを選択しました。審査を待っています。"})


@app.route('/api/battle/cancel_move', methods=['POST'])
def battle_cancel_move():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    if not active_battle["active"]:
        return jsonify({"success": False, "message": "現在アクティブなバトルはありません。"}), 400

    role = None
    if active_battle["player_a"] == user_id:
        role = "A"
    elif active_battle["player_b"] == user_id:
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

    return jsonify({"success": True, "message": "選択したわざを取り消しました。"})


@app.route('/api/battle/request_swap', methods=['POST'])
def battle_request_swap():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    if not active_battle["active"]:
        return jsonify({"success": False, "message": "現在アクティブなバトルはありません。"}), 400

    role = None
    if active_battle["player_a"] == user_id:
        role = "A"
    elif active_battle["player_b"] == user_id:
        role = "B"

    if not role:
        return jsonify({"success": False, "message": "あなたはこの対戦のプレイヤーではありません。"}), 400

    already_swapped = active_battle["a_swapped"] if role == "A" else active_battle["b_swapped"]
    if already_swapped:
        return jsonify({"success": False, "message": "交代は1回までしかできません。"}), 400

    active_battle["swap_request"] = role
    return jsonify({"success": True, "message": "管理者に交代を申請しました。"})


@app.route('/api/battle/grader/join', methods=['POST'])
def grader_join():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    grading_viewers.add(user_id)
    return jsonify({"success": True, "message": "採点画面に入りました。"})


@app.route('/api/battle/grader/leave', methods=['POST'])
def grader_leave():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401
    
    if user_id in grading_viewers:
        grading_viewers.remove(user_id)
    return jsonify({"success": True, "message": "採点画面を離れました。"})


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

    target = active_battle["target_player"]
    if not target:
        # Grader only mode
        active_battle["last_confirmed_score"] = score
        active_battle["last_calculated_score"] = score
        active_battle["messages"].append(f"採点結果: {score}点！")
        active_battle["scores"] = []
        active_battle["voted_graders"] = []
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

                p_winner = next((p for p in players_data if check_user_id(p.get('ユーザid'), winner_id)), None)
                p_loser = next((p for p in players_data if check_user_id(p.get('ユーザid'), loser_id)), None)

                # Transfer money: winner gets half of loser's money
                loser_money = p_loser.get('所持金', 0)
                prize = loser_money // 2
                p_loser['所持金'] = loser_money - prize
                p_winner['所持金'] = p_winner.get('所持金', 0) + prize

                # Both get 2 Power Sources
                for p in [p_winner, p_loser]:
                    owned_raw = p.get('もちもの') or ''
                    owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
                    owned.extend(["ちからのもと", "ちからのもと"])
                    p['もちもの'] = ','.join(owned)

                save_players(players_data)

                active_battle["messages"].append(f"戦闘終了！ {att_player_name} の勝利！")
                active_battle["messages"].append(f"勝者は敗者の所持金の半分（{prize}円）を獲得し、両者に「ちからのもと」が2つ付与されました！")
                active_battle["active"] = False

        elif attacker_poke['hp'] <= 0:
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

                p_winner = next((p for p in players_data if check_user_id(p.get('ユーザid'), winner_id)), None)
                p_loser = next((p for p in players_data if check_user_id(p.get('ユーザid'), loser_id)), None)

                # Transfer money: winner gets half of loser's money
                loser_money = p_loser.get('所持金', 0)
                prize = loser_money // 2
                p_loser['所持金'] = loser_money - prize
                p_winner['所持金'] = p_winner.get('所持金', 0) + prize

                # Both get 2 Power Sources
                for p in [p_winner, p_loser]:
                    owned_raw = p.get('もちもの') or ''
                    owned = [i.strip() for i in str(owned_raw).split(',') if i.strip()]
                    owned.extend(["ちからのもと", "ちからのもと"])
                    p['もちもの'] = ','.join(owned)

                save_players(players_data)

                def_player_name = next((p.get('名前') for p in players_data if check_user_id(p.get('ユーザid'), active_battle[f"player_{defender_role.lower()}"])), "プレイヤー")
                active_battle["messages"].append(f"戦闘終了！ {def_player_name} の勝利！")
                active_battle["messages"].append(f"勝者は敗者の所持金の半分（{prize}円）を獲得し、両者に「ちからのもと」が2つ付与されました！")
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
        "current_score": calculate_score(active_battle["scores"]) if len(active_battle["scores"]) >= 6 else active_battle.get("last_calculated_score", 0)
    })


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
        "a_swapped": False,
        "b_swapped": False,
        "swap_request": None,
        "target_player": None,
        "scores": [],
        "voted_graders": [],
        "messages": [f"バトル開始！ {p_a_data.get('名前')} VS {p_b_data.get('名前')}"],
        "last_confirmed_score": None,
        "last_calculated_score": 0
    })

    # Remove from waiting queues
    if player_a in battle_waiting_players:
        battle_waiting_players.remove(player_a)
    if player_b in battle_waiting_players:
        battle_waiting_players.remove(player_b)

    return jsonify({"success": True, "message": "バトルを開始しました。"})


@app.route('/api/admin/battle/select_target', methods=['POST'])
def admin_battle_select_target():
    data = request.json or {}
    target = data.get('target') # 'A', 'B', or None

    if target not in ['A', 'B', None]:
        return jsonify({"success": False, "message": "無効なターゲットです。"}), 400

    if target == 'A' and not active_battle.get("a_selected_move"):
        return jsonify({"success": False, "message": "プレイヤーAは技を選択していません。"}), 400
    if target == 'B' and not active_battle.get("b_selected_move"):
        return jsonify({"success": False, "message": "プレイヤーBは技を選択していません。"}), 400

    active_battle["target_player"] = target
    active_battle["scores"] = [] # Reset scores for next target
    active_battle["voted_graders"] = []
    return jsonify({"success": True, "message": f"審査対象をプレイヤー {target or '未選択'} に設定しました。"})


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
        p_name = next((p.get('名前') for p in players_data if p.get('ユーザid') == active_battle["player_a"]), active_battle["player_a"])
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
        p_name = next((p.get('名前') for p in players_data if p.get('ユーザid') == active_battle["player_b"]), active_battle["player_b"])
        active_battle["messages"].append(f"{p_name}はポケモンを {pokes[active_battle['b_active_idx']]['name']} に交代した！")

    active_battle["swap_request"] = None
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


@app.route('/api/admin/battle/force_end', methods=['POST'])
def admin_battle_force_end():
    active_battle["active"] = False
    active_battle["player_a"] = None
    active_battle["player_b"] = None
    active_battle["a_pokemon"] = []
    active_battle["b_pokemon"] = []
    active_battle["a_selected_move"] = None
    active_battle["b_selected_move"] = None
    active_battle["swap_request"] = None
    active_battle["target_player"] = None
    active_battle["scores"] = []
    active_battle["voted_graders"] = []
    active_battle["last_calculated_score"] = 0
    active_battle["messages"].append("管理者によってバトルが強制終了されました。")
    return jsonify({"success": True, "message": "バトルを強制終了しました。"})


@app.route('/api/admin/battle/reset_scores', methods=['POST'])
def admin_battle_reset_scores():
    active_battle["scores"] = []
    active_battle["voted_graders"] = []
    active_battle["last_calculated_score"] = 0
    active_battle["messages"].append("管理者によって採点がリセットされました。")
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

    return jsonify({"success": True, "message": "直前の審査を取り消しました。"})


@app.route('/api/swap_pokemon', methods=['POST'])
def swap_pokemon():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "message": "ログインしていません。"}), 401

    players = get_players()
    player = next((p for p in players if p.get('ユーザid') == user_id), None)
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
        "messages": active_battle["messages"]
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
