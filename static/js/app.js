// Type chart loaded dynamically from JSON
let TYPE_CHART = {};

// Override fetch to automatically include X-User-Id header if present
const originalFetch = window.fetch;
window.fetch = function(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    
    const userId = sessionStorage.getItem('user_id') || (typeof state !== 'undefined' ? state.userId : '');
    if (userId) {
        if (options.headers instanceof Headers) {
            options.headers.set('X-User-Id', userId);
        } else if (Array.isArray(options.headers)) {
            options.headers.push(['X-User-Id', userId]);
        } else {
            options.headers['X-User-Id'] = userId;
        }
    }
    return originalFetch(url, options);
};


// Application State
const state = {
    userId: '',
    status: '',
    myPokemonChoices: [], // Loaded from API
    allPokemons: [],       // Loaded from API
    money: 0,
    ownedItems: [],        // Current player's items
    shopItems: [],         // All items from pokemon_items.json
    shopCategory: 'きのみ', // Current selected tab category (きのみ/もちもの/わざマシン)
    movesList: [],         // Loaded from /api/items
    
    // Battle State
    battle: {
        active: false,
        turns: 0,
        // Left side pokemon (user controlled)
        left: null,
        // Right side pokemon (target)
        right: null,
    },
    isJoiningOrWaiting: false,
    
    pollingInterval: null
};

// DOM Elements
const el = {
    // Screens
    loginScreen: document.getElementById('login-screen'),
    choiceScreen: document.getElementById('choice-screen'),
    waitingScreen: document.getElementById('waiting-screen'),
    getScreen: document.getElementById('get-screen'),
    mainScreen: document.getElementById('main-screen'),
    
    // Auth Forms
    loginForm: document.getElementById('login-form-container'),
    registerForm: document.getElementById('register-form-container'),
    goToRegister: document.getElementById('go-to-register'),
    goToLogin: document.getElementById('go-to-login'),
    loginIdInput: document.getElementById('login-id-input'),
    registerIdInput: document.getElementById('register-id-input'),
    registerNameInput: document.getElementById('register-name-input'),
    loginBtn: document.getElementById('login-btn'),
    registerBtn: document.getElementById('register-btn'),
    authError: document.getElementById('auth-error'),
    
    // Choices Form
    wishSelects: [
        document.getElementById('wish-1'),
        document.getElementById('wish-2'),
        document.getElementById('wish-3'),
        document.getElementById('wish-4'),
        document.getElementById('wish-5')
    ],
    submitWishesBtn: document.getElementById('submit-wishes-btn'),
    choiceError: document.getElementById('choice-error'),
    
    // Waiting Screen
    waitingUsername: document.getElementById('waiting-username'),
    
    // Get Screen
    obtainedName1: document.getElementById('obtained-name-1'),
    obtainedName2: document.getElementById('obtained-name-2'),
    startGameBtn: document.getElementById('start-game-btn'),
    
    // Main Game Elements
    tabs: document.querySelectorAll('.tab-item'),
    tabContents: document.querySelectorAll('.tab-content'),
    
    // Simulation Selection
    myPokeSelect: document.getElementById('my-poke-select'),
    enemyPokeSelect: document.getElementById('enemy-poke-select'),
    startBattleBtn: document.getElementById('start-battle-btn'),
    simSelectSubscreen: document.getElementById('sim-select-subscreen'),
    simBattleSubscreen: document.getElementById('sim-battle-subscreen'),
    
    // Battle Screen
    myBattleCard: document.getElementById('my-battle-card'),
    myBattleName: document.getElementById('my-battle-name'),
    myBattleLevel: document.getElementById('my-battle-level'),
    myHpFill: document.getElementById('my-hp-fill'),
    myBattleTypes: document.getElementById('my-battle-types'),
    myCurrHp: document.getElementById('my-curr-hp'),
    myMaxHp: document.getElementById('my-max-hp'),
    mySprite: document.getElementById('my-sprite'),
    
    enemyBattleCard: document.getElementById('enemy-battle-card'),
    enemyBattleName: document.getElementById('enemy-battle-name'),
    enemyBattleLevel: document.getElementById('enemy-battle-level'),
    enemyHpFill: document.getElementById('enemy-hp-fill'),
    enemyBattleTypes: document.getElementById('enemy-battle-types'),
    enemyCurrHp: document.getElementById('enemy-curr-hp'),
    enemyMaxHp: document.getElementById('enemy-max-hp'),
    enemySprite: document.getElementById('enemy-sprite'),
    
    swapBtn: document.getElementById('swap-btn'),
    turnCount: document.getElementById('turn-count'),
    movesPanel: document.getElementById('moves-panel'),
    moveBtns: [
        document.getElementById('move-0'),
        document.getElementById('move-1'),
        document.getElementById('move-2'),
        document.getElementById('move-3')
    ],
    
    // Battle Finish Overlay
    battleFinishOverlay: document.getElementById('battle-finish-overlay'),
    finishResultText: document.getElementById('finish-result-text'),
    finishCloseBtn: document.getElementById('finish-close-btn'),
    battleMessageBanner: document.getElementById('battle-message-banner')
};

// UI Screen Navigation
function showScreen(screen) {
    // Hide all screens
    [el.loginScreen, el.choiceScreen, el.waitingScreen, el.getScreen, el.mainScreen].forEach(s => {
        s.classList.remove('active');
        s.style.display = 'none';
    });
    
    // Show target screen
    screen.style.display = 'flex';
    // Force reflow
    screen.offsetHeight;
    screen.classList.add('active');
}

// Show specific subscreen in Simulation tab
function showSubscreen(subscreen) {
    [el.simSelectSubscreen, el.simBattleSubscreen].forEach(s => {
        s.classList.remove('active-sub');
        s.style.display = 'none';
    });
    subscreen.style.display = 'flex';
    subscreen.offsetHeight;
    subscreen.classList.add('active-sub');
}

// Routing helper based on user status
function routeUserStatus(status, pokemon1, pokemon2) {
    state.status = status;
    
    if (status === 'active') {
        // Go straight to main dashboard
        loadGameData().then(() => {
            showScreen(el.mainScreen);
        });
    } else if (status === 'select_choices') {
        // Load poke list for dropdowns first
        loadWishesOptions().then(() => {
            showScreen(el.choiceScreen);
        });
    } else if (status === 'waiting') {
        // Go to waiting screen and start polling
        el.waitingUsername.textContent = state.userId;
        showScreen(el.waitingScreen);
        startPolling();
    } else if (status === 'ready') {
        loadGameData().then(() => {
            el.obtainedName1.textContent = pokemon1;
            el.obtainedName2.textContent = pokemon2;
            const poke1 = state.allPokemons.find(p => p.name === pokemon1);
            const poke2 = state.allPokemons.find(p => p.name === pokemon2);
            setPokemonSprite(document.getElementById('obtained-sprite-1'), poke1 ? poke1.番号 : null, pokemon1);
            setPokemonSprite(document.getElementById('obtained-sprite-2'), poke2 ? poke2.番号 : null, pokemon2);
            showScreen(el.getScreen);
        });
    }
}

// ----------------------------------------------------
// AUTHENTICATION & REGISTRATION
// ----------------------------------------------------

el.goToRegister.addEventListener('click', () => {
    el.loginForm.classList.add('hidden');
    el.registerForm.classList.remove('hidden');
    el.authError.classList.add('hidden');
});

el.goToLogin.addEventListener('click', () => {
    el.registerForm.classList.add('hidden');
    el.loginForm.classList.remove('hidden');
    el.authError.classList.add('hidden');
});

// Login button click
el.loginIdInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        el.loginBtn.click();
    }
});

el.loginBtn.addEventListener('click', async () => {
    const userId = el.loginIdInput.value.trim();
    if (!userId) {
        showAuthError("ユーザーIDを入力してください。");
        return;
    }
    
    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json();
        
        if (res.ok && data.success) {
            state.userId = data.user_id;
            sessionStorage.setItem('user_id', data.user_id);
            routeUserStatus(data.status, data.pokemon1, data.pokemon2);
        } else {
            showAuthError(data.message || "ログインに失敗しました。");
        }
    } catch (err) {
        console.error(err);
        showAuthError("サーバーとの通信に失敗しました。");
    }
});

// Register button click
el.registerBtn.addEventListener('click', async () => {
    const userId = el.registerIdInput.value.trim();
    const name = el.registerNameInput.value.trim();
    if (!userId) {
        showAuthError("新規ユーザーIDを入力してください。");
        return;
    }
    if (!name) {
        showAuthError("名前を入力してください。");
        return;
    }
    
    // Regexp validation check: alphanumeric, 4 chars or more
    if (!/^[a-zA-Z0-9]{4,}$/.test(userId)) {
        showAuthError("ユーザーIDは4文字以上の半角英数字にしてください。");
        return;
    }
    
    try {
        const res = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, name: name })
        });
        const data = await res.json();
        
        if (res.ok && data.success) {
            state.userId = data.user_id;
            sessionStorage.setItem('user_id', data.user_id);
            routeUserStatus('select_choices', null, null);
        } else {
            showAuthError(data.message || "アカウント作成に失敗しました。");
        }
    } catch (err) {
        console.error(err);
        showAuthError("サーバーとの通信に失敗しました。");
    }
});

function showAuthError(msg) {
    el.authError.textContent = msg;
    el.authError.classList.remove('hidden');
}

// ----------------------------------------------------
// CHOICES (WISH LIST) SCREEN
// ----------------------------------------------------

async function loadWishesOptions() {
    try {
        // Fetch all pokemons first by requesting a subset of game data
        // Just need poke list so we can fill dropdowns
        const res = await fetch('/api/game_data');
        const data = await res.json();
        
        if (res.ok && data.success) {
            state.allPokemons = data.all_pokemons;
            if (data.type_chart) {
                TYPE_CHART = data.type_chart;
            }
            
            // Populate select dropdowns
            el.wishSelects.forEach(select => {
                select.innerHTML = '<option value="">選択してください</option>';
                data.all_pokemons.forEach(poke => {
                    const opt = document.createElement('option');
                    opt.value = poke.name;
                    opt.textContent = poke.name;
                    select.appendChild(opt);
                });
            });
        }
    } catch (err) {
        console.error("Failed to load wishes dropdowns:", err);
    }
}

// Monitor dropdown changes to ensure unique options and enable submit
el.wishSelects.forEach(select => {
    select.addEventListener('change', () => {
        el.choiceError.classList.add('hidden');
        
        const selectedValues = el.wishSelects.map(s => s.value).filter(val => val !== '');
        const uniqueValues = new Set(selectedValues);
        
        // Check for duplicates
        if (selectedValues.length !== uniqueValues.size) {
            el.choiceError.textContent = "すでに選択されているポケモンは再度選択できません。";
            el.choiceError.classList.remove('hidden');
            el.submitWishesBtn.disabled = true;
            return;
        }
        
        // Must select all 5
        if (selectedValues.length === 5) {
            el.submitWishesBtn.disabled = false;
        } else {
            el.submitWishesBtn.disabled = true;
        }
    });
});

// Submit choices click
el.submitWishesBtn.addEventListener('click', async () => {
    const choices = el.wishSelects.map(s => s.value);
    
    try {
        const res = await fetch('/api/submit_choices', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ choices: choices })
        });
        const data = await res.json();
        
        if (res.ok && data.success) {
            routeUserStatus('waiting', null, null);
        } else {
            el.choiceError.textContent = data.message || "送信に失敗しました。";
            el.choiceError.classList.remove('hidden');
        }
    } catch (err) {
        console.error(err);
        el.choiceError.textContent = "通信エラーが発生しました。";
        el.choiceError.classList.remove('hidden');
    }
});

// ----------------------------------------------------
// POLLING STATUS (WAITING SCREEN)
// ----------------------------------------------------

function startPolling() {
    if (state.pollingInterval) clearInterval(state.pollingInterval);
    
    state.pollingInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            if (res.ok && data.success) {
                if (data.status === 'active') {
                    // Stopping polling
                    clearInterval(state.pollingInterval);
                    state.pollingInterval = null;
                    
                    // Show celebration screen
                    el.obtainedName1.textContent = data.pokemon1;
                    el.obtainedName2.textContent = data.pokemon2;
                    
                    loadGameData().then(() => {
                        const poke1 = state.allPokemons.find(p => p.name === data.pokemon1);
                        const poke2 = state.allPokemons.find(p => p.name === data.pokemon2);
                        setPokemonSprite(document.getElementById('obtained-sprite-1'), poke1 ? poke1.番号 : null, data.pokemon1);
                        setPokemonSprite(document.getElementById('obtained-sprite-2'), poke2 ? poke2.番号 : null, data.pokemon2);
                        showScreen(el.getScreen);
                    });
                }
            }
        } catch (err) {
            console.error("Polling error:", err);
        }
    }, 2000);
}

el.startGameBtn.addEventListener('click', () => {
    loadGameData().then(() => {
        showScreen(el.mainScreen);
    });
});

// ----------------------------------------------------
// DASHBOARD & TABS BAR
// ----------------------------------------------------

function initTabNavigation() {
    el.tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Remove active classes
            el.tabs.forEach(t => t.classList.remove('active'));
            el.tabContents.forEach(c => {
                c.classList.remove('active-content');
            });
            
            // Add active class to clicked tab
            tab.classList.add('active');
            
            const tabId = tab.dataset.tab;
            const targetContent = document.getElementById(`tab-${tabId}`);
            if (targetContent) {
                targetContent.classList.add('active-content');
            }
            if (tabId === 'strength') {
                renderStrengthTab();
            }
        });
    });
}

// ----------------------------------------------------
// GAME DATA LOADING & SIMULATION SELECTOR
// ----------------------------------------------------

async function loadGameData() {
    try {
        const res = await fetch('/api/game_data');
        const data = await res.json();
        
        if (res.ok && data.success) {
            state.myPokemonChoices = data.my_pokemon;
            state.allPokemons = data.all_pokemons;
            state.money = data.money || 0;
            state.ownedItems = data.items || [];
            if (data.type_chart) {
                TYPE_CHART = data.type_chart;
            }
            
            // Populate select dropdowns for simulation
            // 1. My Pokemons select (contains 2 pokemons)
            el.myPokeSelect.innerHTML = '<option value="">選択してください</option>';
            state.myPokemonChoices.forEach(poke => {
                const opt = document.createElement('option');
                opt.value = poke.name;
                opt.textContent = poke.name;
                el.myPokeSelect.appendChild(opt);
            });
            
            // 2. Enemy Pokemons select (all 72 pokemons)
            el.enemyPokeSelect.innerHTML = '<option value="">選択してください</option>';
            state.allPokemons.forEach(poke => {
                const opt = document.createElement('option');
                opt.value = poke.name;
                opt.textContent = poke.name;
                el.enemyPokeSelect.appendChild(opt);
            });

            // Update shop and bag displays
            updateMoneyDisplays();
            renderBagTab();
        }
    } catch (err) {
        console.error("Failed to load game data:", err);
    }
}

// Monitor simulation selects
function checkSimSelects() {
    const myVal = el.myPokeSelect.value;
    const enemyVal = el.enemyPokeSelect.value;
    el.startBattleBtn.disabled = !(myVal && enemyVal);
}

el.myPokeSelect.addEventListener('change', checkSimSelects);
el.enemyPokeSelect.addEventListener('change', checkSimSelects);

el.startBattleBtn.addEventListener('click', () => {
    const myPokeName = el.myPokeSelect.value;
    const enemyPokeName = el.enemyPokeSelect.value;
    
    startBattle(myPokeName, enemyPokeName);
});

// ----------------------------------------------------
// SIMULATION BATTLE LOGIC
// ----------------------------------------------------

function startBattle(myPokeName, enemyPokeName) {
    // Lookup full pokemon details
    const myData = state.myPokemonChoices.find(p => p.name === myPokeName);
    const enemyData = state.allPokemons.find(p => p.name === enemyPokeName);
    
    if (!myData || !enemyData) return;
    
    // Create copy for battle state to track current HP
    state.battle.left = {
        name: myData.name,
        番号: myData.番号,
        level: myData.level,
        type1: myData.type1,
        type2: myData.type2,
        maxHp: myData.hp,
        currHp: myData.hp,
        attack: myData.attack,
        defense: myData.defense,
        spAttack: myData.sp_attack,
        spDefense: myData.sp_defense,
        moves: myData.moves,
        item: myData.item,
        isPlayer: true, // Helper flag
        choiceLockMove: null
    };
    
    state.battle.right = {
        name: enemyData.name,
        番号: enemyData.番号,
        level: enemyData.level,
        type1: enemyData.type1,
        type2: enemyData.type2,
        maxHp: enemyData.hp,
        currHp: enemyData.hp,
        attack: enemyData.attack,
        defense: enemyData.defense,
        spAttack: enemyData.spAttack || enemyData.sp_attack,
        spDefense: enemyData.spDefense || enemyData.sp_defense,
        moves: enemyData.moves,
        item: enemyData.item,
        isPlayer: false,
        choiceLockMove: null
    };
    
    state.battle.turns = 0;
    state.battle.active = true;
    
    // Render initial battle screen
    updateBattleUI();
    el.battleFinishOverlay.classList.add('hidden');
    if (el.battleMessageBanner) el.battleMessageBanner.classList.add('hidden');
    if (battleMessageTimeout) clearTimeout(battleMessageTimeout);
    
    // Show battle screen
    showSubscreen(el.simBattleSubscreen);
}

function updateBattleUI() {
    const left = state.battle.left;
    const right = state.battle.right;
    
    // Left side UI (Controlled pokemon)
    el.myBattleName.textContent = left.name;
    el.myBattleLevel.textContent = `Lv.${left.level}`;
    el.myCurrHp.textContent = left.currHp;
    el.myMaxHp.textContent = left.maxHp;
    
    const leftTypes = [left.type1, left.type2].filter(t => t).join('/');
    el.myBattleTypes.textContent = leftTypes;
    
    // HP bar calculations
    const leftHpPercent = Math.max(0, (left.currHp / left.maxHp) * 100);
    el.myHpFill.style.width = `${leftHpPercent}%`;
    setHpBarColor(el.myHpFill, leftHpPercent);
    
    // Sprite images based on sprite sheet
    setPokemonSprite(el.mySprite, left.番号, left.name);
    updateMatchupDisplay(left, 'my-matchup-effective', 'my-matchup-ineffective');
    
    // Right side UI (Target pokemon)
    el.enemyBattleName.textContent = right.name;
    el.enemyBattleLevel.textContent = `Lv.${right.level}`;
    el.enemyCurrHp.textContent = right.currHp;
    el.enemyMaxHp.textContent = right.maxHp;
    
    const rightTypes = [right.type1, right.type2].filter(t => t).join('/');
    el.enemyBattleTypes.textContent = rightTypes;
    
    const rightHpPercent = Math.max(0, (right.currHp / right.maxHp) * 100);
    el.enemyHpFill.style.width = `${rightHpPercent}%`;
    setHpBarColor(el.enemyHpFill, rightHpPercent);
    setPokemonSprite(el.enemySprite, right.番号, right.name);
    updateMatchupDisplay(right, 'enemy-matchup-effective', 'enemy-matchup-ineffective');
    
    // Turn counter removed
    
    // Load moves for active left side pokemon
    for (let i = 0; i < 4; i++) {
        const btn = el.moveBtns[i];
        const move = left.moves[i];
        
        if (move) {
            const isChoiceItem = (left.item === 'こだわりハチマキ' || left.item === 'こだわりメガネ');
            if (isChoiceItem && left.choiceLockMove && move.name !== left.choiceLockMove) {
                btn.disabled = true;
            } else {
                btn.disabled = false;
            }
            btn.querySelector('.move-title').textContent = move.name;
            btn.querySelector('.move-type').textContent = move.type;
            btn.querySelector('.move-power').textContent = `威力 ${move.power}`;
        } else {
            // Disabled if no move in slot
            btn.disabled = true;
            btn.querySelector('.move-title').textContent = '-';
            btn.querySelector('.move-type').textContent = '-';
            btn.querySelector('.move-power').textContent = '威力 -';
        }
    }
}

// Help set color based on remaining HP percentage
function setHpBarColor(barFill, pct) {
    barFill.classList.remove('hp-high', 'hp-medium', 'hp-low');
    if (pct > 50) {
        barFill.classList.add('hp-high');
    } else if (pct > 20) {
        barFill.classList.add('hp-medium');
    } else {
        barFill.classList.add('hp-low');
    }
}

// Cute emoji representations for Pokemon types or specific names
function getPokeEmoji(name) {
    if (name.includes('シャワーズ')) return '💧';
    if (name.includes('デンリュウ')) return '⚡';
    if (name.includes('リザードン')) return '🔥';
    if (name.includes('ピカチュウ')) return '⚡';
    if (name.includes('フシギバナ')) return '🍃';
    if (name.includes('カメックス')) return '🐢';
    if (name.includes('カイリュー')) return '🐉';
    if (name.includes('ハッサム')) return '✂️';
    if (name.includes('ゲンガー')) return '👻';
    if (name.includes('バンギラス')) return '🦖';
    return '👾';
}

// Set pokemon sprite based on ID (番号)
function setPokemonSprite(element, pokemonNumber, nameFallback = '') {
    if (!element) return;
    element.textContent = '';
    element.style.backgroundImage = 'none';
    element.classList.remove('pokemon-sprite');
    
    if (!pokemonNumber) {
        element.textContent = getPokeEmoji(nameFallback);
        return;
    }
    
    const N = parseInt(pokemonNumber, 10);
    const row = Math.floor((N - 1) / 10);
    const col = (N - 1) % 10;
    
    const spriteInner = document.createElement('div');
    spriteInner.classList.add('pokemon-sprite');
    
    // Percentage positioning
    const posX = (col * 100) / 9;
    const posY = (row * 100) / 9;
    spriteInner.style.backgroundPosition = `${posX}% ${posY}%`;
    
    element.appendChild(spriteInner);
}

// ----------------------------------------------------
// DAMAGE FORMULA & CALCULATION
// ----------------------------------------------------

// Calculate matchups based on defender types
function getMatchups(type1, type2) {
    const types = ["ノーマル", "ほのお", "みず", "でんき", "くさ", "こおり", "かくとう", "どく", "じめん", "ひこう", "エスパー", "むし", "いわ", "ゴースト", "ドラゴン", "あく", "はがね", "フェアリー"];
    const effective = [];
    const ineffective = [];
    for (let attacking_type of types) {
        let m = 1.0;
        if (type1 && TYPE_CHART[attacking_type] && TYPE_CHART[attacking_type][type1] !== undefined) {
            m *= TYPE_CHART[attacking_type][type1];
        }
        if (type2 && TYPE_CHART[attacking_type] && TYPE_CHART[attacking_type][type2] !== undefined) {
            m *= TYPE_CHART[attacking_type][type2];
        }
        if (m > 1.0) {
            effective.push(attacking_type);
        } else if (m < 1.0) {
            ineffective.push(attacking_type);
        }
    }
    return { effective, ineffective };
}

// Helper to update matchup displays
function updateMatchupDisplay(poke, effectiveElId, ineffectiveElId) {
    const effectiveEl = document.getElementById(effectiveElId);
    const ineffectiveEl = document.getElementById(ineffectiveElId);
    if (!effectiveEl || !ineffectiveEl) return;

    if (!poke || (!poke.type1 && !poke.type2)) {
        effectiveEl.textContent = '-';
        ineffectiveEl.textContent = '-';
        return;
    }

    const { effective, ineffective } = getMatchups(poke.type1, poke.type2);
    effectiveEl.textContent = effective.length > 0 ? effective.join(', ') : 'なし';
    ineffectiveEl.textContent = ineffective.length > 0 ? ineffective.join(', ') : 'なし';
}

// Calculate type multiplier
function getTypeMultiplier(moveType, defender) {
    let m = 1.0;
    
    // Check type 1
    if (defender.type1 && TYPE_CHART[moveType] && TYPE_CHART[moveType][defender.type1] !== undefined) {
        m *= TYPE_CHART[moveType][defender.type1];
    }
    
    // Check type 2
    if (defender.type2 && TYPE_CHART[moveType] && TYPE_CHART[moveType][defender.type2] !== undefined) {
        m *= TYPE_CHART[moveType][defender.type2];
    }
    
    return m;
}

// Calculate battle damage using formula:
// ダメージ = (((レベル × 2/5 + 2) × 威力 × A/D) / 50 + 2) × M
// Floor each parenthesis, if 0 then correct to 1.
function calculateDamage(attacker, defender, move) {
    if (Number(move.power) === 100) {
        return defender.maxHp;
    }
    const level = attacker.level;
    const power = move.power;
    
    // Determine stats A and D based on category
    let A = 0;
    let D = 0;
    
    if (move.category === '物理') {
        A = attacker.attack;
        D = defender.defense;
    } else { // 特殊
        A = attacker.spAttack;
        D = defender.spDefense;
    }
    
    // Fallback if stats are zero or missing
    if (A <= 0) A = 1;
    if (D <= 0) D = 1;
    
    // Level bracket: Math.floor(level * 2 / 5) + 2
    const term1 = Math.floor(level * 2 / 5) + 2;
    
    // Power & Ratio: Math.floor(term1 * power * A / D)
    const term2 = Math.floor((term1 * power * A) / D);
    
    // Scale and constant: Math.floor(term2 / 50) + 2
    const term3 = Math.floor(term2 / 50) + 2;
    
    // Type chart modifier M
    let M = getTypeMultiplier(move.type, defender);
    
    // Same-type attack bonus (STAB) multiplier
    if (attacker.type1 === move.type || attacker.type2 === move.type) {
        M *= 1.2;
    }

    // Attacker Item Boosts
    const attItem = attacker.item;
    const typeBoostItemMap = {
        "りゅうのキバ": ["ドラゴン", 1.1],
        "ようせいのハネ": ["フェアリー", 1.1],
        "やわらかいすな": ["じめん", 1.1],
        "もくたん": ["ほのお", 1.1],
        "メタルコート": ["はがね", 1.1],
        "まがったスプーン": ["エスパー", 1.1],
        "のろいのおふだ": ["ゴースト", 1.1],
        "とけないこおり": ["こおり", 1.1],
        "どくバリ": ["どく", 1.1],
        "するどいくちばし": ["ひこう", 1.1],
        "しんぴのしずく": ["みず", 1.1],
        "シルクのスカーフ": ["ノーマル", 1.1],
        "じしゃく": ["でんき", 1.1],
        "くろおび": ["かくとう", 1.1],
        "くろいメガネ": ["あく", 1.1],
        "きせきのタネ": ["くさ", 1.1],
        "かたいいし": ["いわ", 1.1]
    };
    if (typeBoostItemMap[attItem]) {
        const [bType, bMult] = typeBoostItemMap[attItem];
        if (move.type === bType) {
            M *= bMult;
        }
    }

    if (attItem === 'こだわりハチマキ' && move.category === '物理') {
        M *= 1.2;
    } else if (attItem === 'こだわりメガネ' && move.category !== '物理') {
        M *= 1.2;
    }

    // Defender Item Reductions (Type-resist berries)
    const defItem = defender.item;
    const typeBerryMap = {
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
    };
    if (defItem && typeBerryMap[move.type] === defItem) {
        M *= 0.5;
    }
    
    // Final product: Math.floor(term3 * M)
    let damage = Math.floor(term3 * M);
    if (attItem === 'いのちのたま') {
        damage = Math.floor(damage * 1.2);
    }
    
    // Correct if result is 0
    if (damage <= 0) {
        damage = 1;
    }
    
    return damage;
}

let battleMessageTimeout = null;
let battleMessageQueue = [];
let processingMessages = false;

function showBattleMessage(msg) {
    battleMessageQueue.push(msg);
    if (!processingMessages) {
        processNextBattleMessage();
    }
}

function processNextBattleMessage() {
    if (battleMessageQueue.length === 0) {
        processingMessages = false;
        return;
    }
    processingMessages = true;
    const msg = battleMessageQueue.shift();
    if (el.battleMessageBanner) {
        el.battleMessageBanner.innerHTML = msg.replace(/\n/g, '<br>');
        el.battleMessageBanner.classList.remove('hidden');
    }
    if (battleMessageTimeout) clearTimeout(battleMessageTimeout);
    battleMessageTimeout = setTimeout(() => {
        if (el.battleMessageBanner) {
            el.battleMessageBanner.classList.add('hidden');
        }
        setTimeout(processNextBattleMessage, 200);
    }, 2000);
}

function getItemEffectText(itemName) {
    if (!itemName) return "";
    const item = state.shopItems.find(i => i['名前'] === itemName);
    if (item) return item['効果'];
    if (itemName === 'ちからのもと') {
        return "ポケモンにつかうと、いずれかのステータスを +3 上昇させる。";
    }
    return "";
}

// Move Click Action
el.movesPanel.addEventListener('click', async (e) => {
    const btn = e.target.closest('.move-box');
    if (!btn || btn.disabled || !state.battle.active) return;
    
    const moveIdx = parseInt(btn.dataset.idx, 10);
    const attacker = state.battle.left;
    const defender = state.battle.right;
    const move = attacker.moves[moveIdx];
    
    if (!move) return;
    
    // Set choice lock for simulation mode
    if ((attacker.item === 'こだわりハチマキ' || attacker.item === 'こだわりメガネ') && !attacker.choiceLockMove) {
        attacker.choiceLockMove = move.name;
    }
    
    // Disable moves to prevent double clicking during resolution
    el.moveBtns.forEach(b => b.disabled = true);
    
    const attItem = attacker.item;
    const defItem = defender.item;
    const moveType = move.type;

    // Clear previous messages queue when starting a new turn/move
    battleMessageQueue = [];

    // 1. Type boost items
    const typeBoostItemMap = {
        "りゅうのキバ": "ドラゴン",
        "ようせいのハネ": "フェアリー",
        "やわらかいすな": "じめん",
        "もくたん": "ほのお",
        "メタルコート": "はがね",
        "まがったスプーン": "エスパー",
        "のろいのおふだ": "ゴースト",
        "とけないこおり": "こおり",
        "どくバリ": "どく",
        "するどいくちばし": "ひこう",
        "しんぴのしずく": "みず",
        "シルクのスカーフ": "ノーマル",
        "じしゃく": "でんき",
        "くろおび": "かくとう",
        "くろいメガネ": "あく",
        "きせきのタネ": "くさ",
        "かたいいし": "いわ"
    };
    if (typeBoostItemMap[attItem] && moveType === typeBoostItemMap[attItem]) {
        showBattleMessage(`もちもの”${attItem}”が発動！\n${getItemEffectText(attItem)}`);
    }

    // 2. Choice items (activation log removed)

    // 3. Life orb
    if (attItem === 'いのちのたま') {
        showBattleMessage(`もちもの”${attItem}”が発動！\n${getItemEffectText(attItem)}`);
    }

    // 4. Type-resist berries
    const typeBerryMap = {
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
    };
    if (defItem && typeBerryMap[moveType] === defItem) {
        showBattleMessage(`もちもの”${defItem}”が発動！\n${getItemEffectText(defItem)}`);
    }

    // Perform damage calculation
    let dmg = calculateDamage(attacker, defender, move);

    // Consume resist berry
    if (defItem && typeBerryMap[moveType] === defItem) {
        defender.item = null;
    }

    // 5. Focus sash
    if (defItem === 'きあいのタスキ' && defender.currHp === defender.maxHp && dmg >= defender.currHp) {
        dmg = defender.currHp - 1;
        showBattleMessage(`もちもの”${defItem}”が発動！\n${getItemEffectText(defItem)}`);
        defender.item = null;
    }

    defender.currHp = Math.max(0, defender.currHp - dmg);
    
    // Progress turns
    state.battle.turns += 1;
    
    // Display type effectiveness message based on multiplier
    const mult = getTypeMultiplier(move.type, defender);
    if (mult > 1.0) {
        showBattleMessage("こうかは　ばつぐんだ！");
    } else if (mult > 0 && mult < 1.0) {
        showBattleMessage("こうかは　いまひとつのようだ...");
    } else if (mult === 0) {
        showBattleMessage("こうかがない　ようだ…");
    }
    
    // Add visual hit effect to enemy card
    el.enemyBattleCard.classList.add('shake');
    setTimeout(() => {
        el.enemyBattleCard.classList.remove('shake');
    }, 200);
    
    // Update HP values and bars in the UI
    updateBattleUI();
    
    // Check if target is defeated initially
    if (defender.currHp <= 0) {
        finishBattle(defender.name + "を倒した！");
        return;
    }

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    // 6. Shell Bell
    if (attItem === 'かいがらのすず' && attacker.currHp > 0 && dmg > 0) {
        const healAmt = Math.floor(dmg / 4);
        if (healAmt > 0) {
            await sleep(1000);
            attacker.currHp = Math.min(attacker.maxHp, attacker.currHp + healAmt);
            showBattleMessage(`もちもの”かいがらのすず”が発動！\n${getItemEffectText('かいがらのすず')}`);
            showBattleMessage(`${attacker.name}のHPが ${healAmt} 回復した！`);
            updateBattleUI();
        }
    }

    // 7. Rocky Helmet
    if (defItem === 'ゴツゴツメット' && attacker.currHp > 0) {
        const recoil = Math.floor(attacker.maxHp / 10);
        await sleep(1000);
        attacker.currHp = Math.max(0, attacker.currHp - recoil);
        showBattleMessage(`もちもの”ゴツゴツメット”が発動！\n${getItemEffectText('ゴツゴツメット')}`);
        showBattleMessage(`${attacker.name}は ゴツゴツメット で ${recoil} ダメージを受けた！`);
        updateBattleUI();
        if (attacker.currHp <= 0) {
            finishBattle(attacker.name + "は力尽きた！");
            return;
        }
    }

    // 8. Life Orb recoil
    if (attItem === 'いのちのたま' && attacker.currHp > 0) {
        const recoil = Math.floor(attacker.maxHp / 8);
        await sleep(1000);
        attacker.currHp = Math.max(0, attacker.currHp - recoil);
        showBattleMessage(`${attacker.name}は いのちのたま の反動で ${recoil} ダメージを受けた！`);
        updateBattleUI();
        if (attacker.currHp <= 0) {
            finishBattle(attacker.name + "は力尽きた！");
            return;
        }
    }

    // 9. Leftovers
    if (attItem === 'たべのこし' && attacker.currHp > 0) {
        const healAmt = Math.floor(attacker.maxHp / 12);
        await sleep(1000);
        attacker.currHp = Math.min(attacker.maxHp, attacker.currHp + healAmt);
        showBattleMessage(`もちもの”たべのこし”が発動！\n${getItemEffectText('たべのこし')}`);
        showBattleMessage(`${attacker.name}のHPが ${healAmt} 回復した！`);
        updateBattleUI();
    }

    // 10. Oran Berry (オボンのみ)
    for (let poke of [attacker, defender]) {
        if (poke.currHp > 0 && poke.currHp <= Math.floor(poke.maxHp / 2) && poke.item === 'オボンのみ') {
            const healAmt = Math.floor(poke.maxHp / 3);
            await sleep(1000);
            poke.currHp = Math.min(poke.maxHp, poke.currHp + healAmt);
            showBattleMessage(`もちもの”オボンのみ”が発動！\n${getItemEffectText('オボンのみ')}`);
            showBattleMessage(`${poke.name}のHPが ${healAmt} 回復した！`);
            poke.item = null;
            updateBattleUI();
        }
    }
    
    // Check if target is defeated at the end of turn
    if (defender.currHp <= 0) {
        finishBattle(defender.name + "を倒した！");
    } else if (attacker.currHp <= 0) {
        finishBattle(attacker.name + "は力尽きた！");
    } else {
        // Re-enable moves for active left side pokemon
        if (state.battle.active) {
            updateBattleUI();
        }
    }
});

// Swap button logic: swaps Left and Right pokemon and updates moves
el.swapBtn.addEventListener('click', () => {
    if (!state.battle.active) return;
    
    // Rotate cards visually
    el.myBattleCard.style.transform = 'scale(0.9)';
    el.enemyBattleCard.style.transform = 'scale(0.9)';
    
    setTimeout(() => {
        // Swap state
        const temp = state.battle.left;
        state.battle.left = state.battle.right;
        state.battle.right = temp;
        
        if (state.battle.left) state.battle.left.choiceLockMove = null;
        if (state.battle.right) state.battle.right.choiceLockMove = null;
        
        updateBattleUI();
        
        // Hide message banner on swap
        if (el.battleMessageBanner) el.battleMessageBanner.classList.add('hidden');
        if (battleMessageTimeout) clearTimeout(battleMessageTimeout);
        
        el.myBattleCard.style.transform = 'scale(1)';
        el.enemyBattleCard.style.transform = 'scale(1)';
    }, 150);
});

// Battle finished
function finishBattle(msg) {
    state.battle.active = false;
    
    // Disable all move buttons
    el.moveBtns.forEach(btn => btn.disabled = true);
    
    // Set overlay texts
    el.finishResultText.textContent = msg;
    el.battleFinishOverlay.classList.remove('hidden');
}

// Reset and go back to selection screen
el.finishCloseBtn.addEventListener('click', () => {
    el.battleFinishOverlay.classList.add('hidden');
    
    // Reset selects and refresh game data lists just in case
    el.myPokeSelect.value = "";
    el.enemyPokeSelect.value = "";
    el.startBattleBtn.disabled = true;
    
    showSubscreen(el.simSelectSubscreen);
});

// ----------------------------------------------------
// APPLICATION INITIALIZATION
// ----------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    initTabNavigation();
    initShopTab();
    initStrengthTab();
    
    const savedUserId = sessionStorage.getItem('user_id');
    if (savedUserId) {
        state.userId = savedUserId;
        fetch('/api/status')
            .then(res => {
                if (res.ok) return res.json();
                throw new Error("Session expired");
            })
            .then(data => {
                if (data.success) {
                    routeUserStatus(data.status, data.pokemon1, data.pokemon2);
                } else {
                    sessionStorage.removeItem('user_id');
                    showScreen(el.loginScreen);
                }
            })
            .catch(() => {
                sessionStorage.removeItem('user_id');
                showScreen(el.loginScreen);
            });
    } else {
        showScreen(el.loginScreen);
    }
});

// ============================================================
// SHOP TAB LOGIC
// ============================================================

let shopToastTimer = null;

function showShopToast(msg, isError = false) {
    // Remove existing toast
    const old = document.querySelector('.shop-toast');
    if (old) old.remove();
    if (shopToastTimer) clearTimeout(shopToastTimer);

    const toast = document.createElement('div');
    toast.className = 'shop-toast' + (isError ? ' error-toast' : '');
    toast.textContent = msg;

    // Append to the tab-shop div so positioning works within it
    document.getElementById('tab-shop').appendChild(toast);
    shopToastTimer = setTimeout(() => toast.remove(), 2500);
}

function updateMoneyDisplays() {
    const m = state.money;
    document.getElementById('shop-money-display').textContent = m.toLocaleString();
    document.getElementById('bag-money-display').textContent = m.toLocaleString();
}

// ---- Shop: choose screen (buy / sell) ----
function showShopChooseScreen() {
    document.getElementById('shop-choose-screen').style.display = '';
    document.getElementById('shop-buy-browser').classList.remove('active');
    document.getElementById('shop-sell-browser').classList.remove('active');

    // Grey out sell if no items
    const sellBox = document.getElementById('shop-sell-box');
    if (state.ownedItems.length === 0) {
        sellBox.classList.add('disabled-box');
        sellBox.classList.remove('sell-box');
    } else {
        sellBox.classList.remove('disabled-box');
        sellBox.classList.add('sell-box');
    }
}

function updateShopSubTabUI(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('.shop-sub-tab').forEach(btn => {
        if (btn.dataset.category === state.shopCategory) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

function showShopBuyBrowser() {
    document.getElementById('shop-choose-screen').style.display = 'none';
    document.getElementById('shop-sell-browser').classList.remove('active');
    document.getElementById('shop-buy-browser').classList.add('active');
    state.shopCategory = 'きのみ';
    updateShopSubTabUI('shop-buy-sub-tabs');
    renderShopBuyList();
    // reset detail panel
    document.getElementById('shop-buy-placeholder').style.display = '';
    document.getElementById('shop-buy-detail').classList.remove('visible');
    document.getElementById('shop-buy-action-btn').disabled = true;
}

function showShopSellBrowser() {
    if (state.ownedItems.length === 0) return;
    document.getElementById('shop-choose-screen').style.display = 'none';
    document.getElementById('shop-buy-browser').classList.remove('active');
    document.getElementById('shop-sell-browser').classList.add('active');
    state.shopCategory = 'きのみ';
    updateShopSubTabUI('shop-sell-sub-tabs');
    renderShopSellList();
    document.getElementById('shop-sell-placeholder').style.display = '';
    document.getElementById('shop-sell-detail').classList.remove('visible');
    document.getElementById('shop-sell-action-btn').disabled = true;
}

// ---- Render buy list ----
function renderShopBuyList() {
    const list = document.getElementById('shop-buy-item-list');
    list.innerHTML = '';
    state.shopItems.forEach(item => {
        if (item['分類'] !== state.shopCategory) return;
        const row = document.createElement('div');
        row.className = 'shop-item-row';
        row.textContent = item['名前'];
        row.dataset.name = item['名前'];
        row.addEventListener('click', () => {
            // Deselect all
            list.querySelectorAll('.shop-item-row').forEach(r => r.classList.remove('selected'));
            row.classList.add('selected');
            selectShopBuyItem(item);
        });
        list.appendChild(row);
    });
}

function getTMMoveDetails(itemName) {
    if (!itemName) return null;
    let moveName = "";
    const match = itemName.match(/\(([^)]+)\)/);
    if (match) {
        moveName = match[1].trim();
    } else {
        moveName = itemName.replace("わざマシン", "").replace("わざましん", "");
        moveName = moveName.replace(/\s+/g, "").trim();
    }
    if (!moveName) return null;
    return state.movesList.find(m => m['わざ'] === moveName);
}

function selectShopBuyItem(item) {
    document.getElementById('shop-buy-placeholder').style.display = 'none';
    const detail = document.getElementById('shop-buy-detail');
    detail.classList.add('visible');

    document.getElementById('shop-buy-detail-name').textContent = item['名前'];
    document.getElementById('shop-buy-detail-category').textContent = item['分類'];
    
    let effectHtml = item['効果'].replace(/\n/g, '<br>');
    if (item['分類'] === 'わざマシン') {
        const moveDetails = getTMMoveDetails(item['名前']);
        if (moveDetails) {
            effectHtml += `<br><br><span style="color: var(--primary); font-weight: bold;">【わざ情報】<br>タイプ: ${moveDetails['タイプ']}<br>分類: ${moveDetails['分類']}<br>威力: ${moveDetails['威力']}</span>`;
        }
    }
    document.getElementById('shop-buy-detail-effect').innerHTML = effectHtml;
    document.getElementById('shop-buy-detail-price').textContent = item['値段'].toLocaleString();

    const btn = document.getElementById('shop-buy-action-btn');
    btn.dataset.itemName = item['名前'];
    btn.disabled = state.money < item['値段'];
}

// ---- Render sell list ----
function renderShopSellList() {
    const list = document.getElementById('shop-sell-item-list');
    list.innerHTML = '';

    const filteredItems = state.ownedItems.filter(itemName => {
        const itemData = state.shopItems.find(i => i['名前'] === itemName);
        return itemData && itemData['分類'] === state.shopCategory;
    });

    if (filteredItems.length === 0) {
        const msg = document.createElement('div');
        msg.className = 'bag-empty-msg';
        msg.textContent = '対象のアイテムを持っていません';
        list.appendChild(msg);
        return;
    }

    filteredItems.forEach(itemName => {
        const row = document.createElement('div');
        row.className = 'shop-item-row';
        row.textContent = itemName;
        row.dataset.name = itemName;
        row.addEventListener('click', () => {
            list.querySelectorAll('.shop-item-row').forEach(r => r.classList.remove('selected'));
            row.classList.add('selected');
            const itemData = state.shopItems.find(i => i['名前'] === itemName);
            if (itemData) selectShopSellItem(itemData);
        });
        list.appendChild(row);
    });
}

function selectShopSellItem(item) {
    document.getElementById('shop-sell-placeholder').style.display = 'none';
    const detail = document.getElementById('shop-sell-detail');
    detail.classList.add('visible');

    const sellPrice = Math.floor(item['値段'] / 2);
    document.getElementById('shop-sell-detail-name').textContent = item['名前'];
    document.getElementById('shop-sell-detail-category').textContent = item['分類'];
    
    let effectHtml = item['効果'].replace(/\n/g, '<br>');
    if (item['分類'] === 'わざマシン') {
        const moveDetails = getTMMoveDetails(item['名前']);
        if (moveDetails) {
            effectHtml += `<br><br><span style="color: var(--primary); font-weight: bold;">【わざ情報】<br>タイプ: ${moveDetails['タイプ']}<br>分類: ${moveDetails['分類']}<br>威力: ${moveDetails['威力']}</span>`;
        }
    }
    document.getElementById('shop-sell-detail-effect').innerHTML = effectHtml;
    document.getElementById('shop-sell-detail-price').textContent = sellPrice.toLocaleString();

    const btn = document.getElementById('shop-sell-action-btn');
    btn.dataset.itemName = item['名前'];
    btn.disabled = false;
}

// ---- Confirmation modal ----
const confirmOverlay = document.getElementById('shop-confirm-overlay');
const confirmMessage = document.getElementById('shop-confirm-message');
const confirmOkBtn = document.getElementById('shop-confirm-ok-btn');
const confirmCancelBtn = document.getElementById('shop-confirm-cancel-btn');

let _confirmCallback = null;

function showConfirm(msg, onOk) {
    confirmMessage.textContent = msg;
    _confirmCallback = onOk;
    confirmOverlay.classList.remove('hidden');
}

function hideConfirm() {
    confirmOverlay.classList.add('hidden');
    _confirmCallback = null;
}

confirmOkBtn.addEventListener('click', () => {
    const cb = _confirmCallback;
    hideConfirm();
    if (cb) cb();
});

confirmCancelBtn.addEventListener('click', hideConfirm);

// Close on overlay background click
confirmOverlay.addEventListener('click', (e) => {
    if (e.target === confirmOverlay) hideConfirm();
});

// ---- Buy action ----
document.getElementById('shop-buy-action-btn').addEventListener('click', () => {
    const btn = document.getElementById('shop-buy-action-btn');
    const itemName = btn.dataset.itemName;
    if (!itemName || btn.disabled) return;

    const item = state.shopItems.find(i => i['名前'] === itemName);
    const price = item ? item['値段'].toLocaleString() : '?';
    showConfirm(`「${itemName}」を\n${price}円で購入しますか？`, async () => {
        try {
            const res = await fetch('/api/buy', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_name: itemName })
            });
            const data = await res.json();

            if (res.ok && data.success) {
                state.money = data.money;
                state.ownedItems = data.owned_items;
                updateMoneyDisplays();
                renderBagTab();
                if (item) btn.disabled = state.money < item['値段'];
                showShopToast(data.message);
            } else {
                showShopToast(data.message || '購入に失敗しました', true);
            }
        } catch (err) {
            console.error(err);
            showShopToast('通信エラーが発生しました', true);
        }
    });
});

// ---- Sell action ----
document.getElementById('shop-sell-action-btn').addEventListener('click', () => {
    const btn = document.getElementById('shop-sell-action-btn');
    const itemName = btn.dataset.itemName;
    if (!itemName || btn.disabled) return;

    const item = state.shopItems.find(i => i['名前'] === itemName);
    const sellPrice = item ? Math.floor(item['値段'] / 2).toLocaleString() : '?';
    showConfirm(`「${itemName}」を\n${sellPrice}円で売却しますか？`, async () => {
        try {
            const res = await fetch('/api/sell', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_name: itemName })
            });
            const data = await res.json();

            if (res.ok && data.success) {
                state.money = data.money;
                state.ownedItems = data.owned_items;
                updateMoneyDisplays();
                renderBagTab();
                document.getElementById('shop-sell-placeholder').style.display = '';
                document.getElementById('shop-sell-detail').classList.remove('visible');
                renderShopSellList();
                showShopToast(data.message);

                if (state.ownedItems.length === 0) {
                    setTimeout(() => showShopChooseScreen(), 1200);
                }
            } else {
                showShopToast(data.message || '売却に失敗しました', true);
            }
        } catch (err) {
            console.error(err);
            showShopToast('通信エラーが発生しました', true);
        }
    });
});

// ---- Init shop tab ----
async function initShopTab() {
    try {
        const res = await fetch('/api/items');
        const data = await res.json();
        if (res.ok && data.success) {
            state.shopItems = data.items;
            state.money = data.money;
            state.ownedItems = data.owned_items;
            updateMoneyDisplays();
        }
    } catch (err) {
        console.error('Failed to load items:', err);
    }

    // Set up sub-tab clicks for buy browser
    document.getElementById('shop-buy-sub-tabs').querySelectorAll('.shop-sub-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            state.shopCategory = btn.dataset.category;
            updateShopSubTabUI('shop-buy-sub-tabs');
            renderShopBuyList();
            
            // Reset detail panel on category switch
            document.getElementById('shop-buy-placeholder').style.display = '';
            document.getElementById('shop-buy-detail').classList.remove('visible');
            document.getElementById('shop-buy-action-btn').disabled = true;
        });
    });

    // Set up sub-tab clicks for sell browser
    document.getElementById('shop-sell-sub-tabs').querySelectorAll('.shop-sub-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            state.shopCategory = btn.dataset.category;
            updateShopSubTabUI('shop-sell-sub-tabs');
            renderShopSellList();

            // Reset detail panel on category switch
            document.getElementById('shop-sell-placeholder').style.display = '';
            document.getElementById('shop-sell-detail').classList.remove('visible');
            document.getElementById('shop-sell-action-btn').disabled = true;
        });
    });
}

// ---- Shop tab event wiring ----
document.getElementById('shop-buy-box').addEventListener('click', showShopBuyBrowser);
document.getElementById('shop-sell-box').addEventListener('click', () => {
    if (state.ownedItems.length > 0) showShopSellBrowser();
});
document.getElementById('shop-buy-back-btn').addEventListener('click', showShopChooseScreen);
document.getElementById('shop-sell-back-btn').addEventListener('click', showShopChooseScreen);

// When switching to shop tab, refresh state
const shopTab = document.querySelector('[data-tab="shop"]');
shopTab.addEventListener('click', async () => {
    // Always fetch fresh data when opening shop
    try {
        const res = await fetch('/api/items');
        const data = await res.json();
        if (res.ok && data.success) {
            state.shopItems = data.items;
            state.money = data.money;
            state.ownedItems = data.owned_items;
            state.movesList = data.moves || [];
            updateMoneyDisplays();
        }
    } catch (e) {}
    showShopChooseScreen();
});

// When switching to bag tab, refresh
const bagTab = document.querySelector('[data-tab="bag"]');
bagTab.addEventListener('click', async () => {
    try {
        const res = await fetch('/api/items');
        const data = await res.json();
        if (res.ok && data.success) {
            state.shopItems = data.items;
            state.money = data.money;
            state.ownedItems = data.owned_items;
            state.movesList = data.moves || [];
            updateMoneyDisplays();
            renderBagTab();
        }
    } catch (e) {}
});

// ============================================================
// BAG TAB LOGIC
// ============================================================

let currentSelectedBagItem = null;

function renderBagTab() {
    const list = document.getElementById('bag-item-list');
    const emptyMsg = document.getElementById('bag-empty-msg');

    list.querySelectorAll('.bag-item-row').forEach(r => r.remove());

    document.getElementById('bag-detail-placeholder').style.display = '';
    document.getElementById('bag-detail-content').classList.remove('visible');
    
    const useBtn = document.getElementById('bag-use-btn');
    useBtn.disabled = true;
    currentSelectedBagItem = null;

    if (state.ownedItems.length === 0) {
        emptyMsg.style.display = '';
        return;
    }
    emptyMsg.style.display = 'none';

    state.ownedItems.forEach((itemName, index) => {
        const row = document.createElement('div');
        row.className = 'bag-item-row';
        row.textContent = itemName;
        row.dataset.index = index;
        row.addEventListener('click', () => {
            list.querySelectorAll('.bag-item-row').forEach(r => r.classList.remove('selected'));
            row.classList.add('selected');
            
            let itemData = state.shopItems.find(i => i['名前'] === itemName);
            if (!itemData && itemName === 'ちからのもと') {
                itemData = {
                    "名前": "ちからのもと",
                    "効果": "ポケモンにつかうと、いずれかのステータスを +3 上昇させる。",
                    "分類": "ちからのもと",
                    "値段": 4000 // Sell price will be 2000
                };
            }
            if (itemData) showBagDetail(itemData);
        });
        list.appendChild(row);
    });
}

function showBagDetail(item) {
    document.getElementById('bag-detail-placeholder').style.display = 'none';
    const content = document.getElementById('bag-detail-content');
    content.classList.add('visible');

    document.getElementById('bag-detail-name').textContent = item['名前'];
    document.getElementById('bag-detail-category').textContent = item['分類'];
    
    let effectHtml = item['効果'].replace(/\n/g, '<br>');
    if (item['分類'] === 'わざマシン') {
        const moveDetails = getTMMoveDetails(item['名前']);
        if (moveDetails) {
            effectHtml += `<br><br><span style="color: var(--primary); font-weight: bold;">【わざ情報】<br>タイプ: ${moveDetails['タイプ']}<br>分類: ${moveDetails['分類']}<br>威力: ${moveDetails['威力']}</span>`;
        }
    }
    document.getElementById('bag-detail-effect').innerHTML = effectHtml;
    const sellPrice = item['名前'] === 'ちからのもと' ? 2000 : Math.floor(item['値段'] / 2);
    document.getElementById('bag-detail-sell-price').textContent = sellPrice.toLocaleString();

    const useBtn = document.getElementById('bag-use-btn');
    useBtn.disabled = false;
    currentSelectedBagItem = item;

    if (item['分類'] === 'わざマシン' || item['分類'] === 'ちからのもと') {
        useBtn.textContent = 'つかう';
    } else {
        useBtn.textContent = 'そうび';
    }
}

// ---- Bag action modal workflow ----
const bagOverlay = document.getElementById('bag-action-overlay');
const bagDialogSelectPoke = document.getElementById('bag-dialog-select-poke');
const bagDialogConfirmEquip = document.getElementById('bag-dialog-confirm-equip');
const bagDialogSelectMove = document.getElementById('bag-dialog-select-move');
const bagDialogConfirmMove = document.getElementById('bag-dialog-confirm-move');
const bagDialogResult = document.getElementById('bag-dialog-result');
const bagDialogSelectStat = document.getElementById('bag-dialog-select-stat');

let bagWorkflowState = {
    item: null,
    selectedPokeIndex: -1,
    selectedMoveIndex: -1,
    pokemonList: []
};

// Open overlay and start flow
document.getElementById('bag-use-btn').addEventListener('click', async () => {
    if (!currentSelectedBagItem) return;
    
    try {
        const res = await fetch('/api/game_data');
        const data = await res.json();
        if (res.ok && data.success) {
            bagWorkflowState.pokemonList = data.my_pokemon;
        }
    } catch (e) {
        console.error(e);
    }

    if (bagWorkflowState.pokemonList.length === 0) {
        alert("手持ちのポケモンがいません。");
        return;
    }

    bagWorkflowState.item = currentSelectedBagItem;
    
    showBagDialog(bagDialogSelectPoke);
    
    const isTM = currentSelectedBagItem['分類'] === 'わざマシン';
    const isPower = currentSelectedBagItem['分類'] === 'ちからのもと';
    if (isPower) {
        document.getElementById('bag-select-title').textContent = "ちからのもとをどちらに使いますか？";
    } else {
        document.getElementById('bag-select-title').textContent = isTM ? "どちらのポケモンに使いますか？" : "どちらのポケモンに装備させますか？";
    }
    
    const opt1 = document.getElementById('bag-poke-opt-1');
    const opt2 = document.getElementById('bag-poke-opt-2');
    
    opt1.textContent = bagWorkflowState.pokemonList[0] ? bagWorkflowState.pokemonList[0].name : "-";
    opt1.style.display = bagWorkflowState.pokemonList[0] ? "" : "none";
    
    opt2.textContent = bagWorkflowState.pokemonList[1] ? bagWorkflowState.pokemonList[1].name : "-";
    opt2.style.display = bagWorkflowState.pokemonList[1] ? "" : "none";
    
    bagOverlay.classList.remove('hidden');
});

function showBagDialog(dialog) {
    [bagDialogSelectPoke, bagDialogConfirmEquip, bagDialogSelectMove, bagDialogConfirmMove, bagDialogResult, bagDialogSelectStat].forEach(d => {
        d.classList.add('hidden');
    });
    dialog.classList.remove('hidden');
}

function hideBagOverlay() {
    bagOverlay.classList.add('hidden');
}

document.getElementById('bag-select-cancel-btn').addEventListener('click', hideBagOverlay);

[0, 1].forEach(idx => {
    document.getElementById(`bag-poke-opt-${idx+1}`).addEventListener('click', () => {
        bagWorkflowState.selectedPokeIndex = idx;
        const poke = bagWorkflowState.pokemonList[idx];
        if (!poke) return;

        if (bagWorkflowState.item['分類'] === 'わざマシン') {
            showBagDialog(bagDialogSelectMove);
            for (let mIdx = 0; mIdx < 4; mIdx++) {
                const moveBtn = document.getElementById(`bag-move-${mIdx}`);
                const move = poke.moves[mIdx];
                if (move) {
                    moveBtn.textContent = move.name;
                    moveBtn.disabled = false;
                } else {
                    moveBtn.textContent = "-";
                    moveBtn.disabled = true;
                }
            }
        } else if (bagWorkflowState.item['分類'] === 'ちからのもと') {
            showBagDialog(bagDialogSelectStat);
        } else {
            showBagDialog(bagDialogConfirmEquip);
            const equipMsg = document.getElementById('bag-equip-msg');
            if (poke.item) {
                equipMsg.textContent = `${poke.name}は、「${poke.item}」を装備していますが、入れ替えますか？`;
            } else {
                equipMsg.textContent = `${poke.name}に装備させますか？`;
            }
        }
    });
});

document.getElementById('bag-equip-cancel-btn').addEventListener('click', () => {
    showBagDialog(bagDialogSelectPoke);
});

document.getElementById('bag-equip-ok-btn').addEventListener('click', async () => {
    const poke = bagWorkflowState.pokemonList[bagWorkflowState.selectedPokeIndex];
    try {
        const res = await fetch('/api/equip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                poke_index: bagWorkflowState.selectedPokeIndex,
                item_name: bagWorkflowState.item['名前']
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            state.ownedItems = data.owned_items;
            await loadGameData();
            renderBagTab();
            
            showBagDialog(bagDialogResult);
            document.getElementById('bag-result-msg').textContent = `${poke.name}は、「${bagWorkflowState.item['名前']}」を装備しました！`;
        } else {
            alert(data.message || "装備に失敗しました。");
            hideBagOverlay();
        }
    } catch (err) {
        console.error(err);
        alert("通信エラーが発生しました。");
        hideBagOverlay();
    }
});

document.getElementById('bag-move-cancel-btn').addEventListener('click', () => {
    showBagDialog(bagDialogSelectPoke);
});

for (let mIdx = 0; mIdx < 4; mIdx++) {
    document.getElementById(`bag-move-${mIdx}`).addEventListener('click', () => {
        bagWorkflowState.selectedMoveIndex = mIdx;
        const poke = bagWorkflowState.pokemonList[bagWorkflowState.selectedPokeIndex];
        const oldMoveName = poke.moves[mIdx] ? poke.moves[mIdx].name : "-";
        
        const tmName = bagWorkflowState.item['名前'];
        let moveName = "";
        const match = tmName.match(/\(([^)]+)\)/);
        if (match) {
            moveName = match[1].trim();
        } else {
            moveName = tmName.replace("わざマシン", "").replace("わざましん", "");
            moveName = moveName.replace(/\s+/g, "").trim();
            if (!moveName) moveName = tmName;
        }

        showBagDialog(bagDialogConfirmMove);
        document.getElementById('bag-move-msg').textContent = `「${oldMoveName}」を忘れて、\n「${moveName}」を覚えさせますか？`;
    });
}

document.getElementById('bag-learn-cancel-btn').addEventListener('click', () => {
    showBagDialog(bagDialogSelectMove);
});

document.getElementById('bag-learn-ok-btn').addEventListener('click', async () => {
    const poke = bagWorkflowState.pokemonList[bagWorkflowState.selectedPokeIndex];
    const tmName = bagWorkflowState.item['名前'];
    
    let moveName = "";
    const match = tmName.match(/\(([^)]+)\)/);
    if (match) {
        moveName = match[1].trim();
    } else {
        moveName = tmName.replace("わざマシン", "").replace("わざましん", "");
        moveName = moveName.replace(/\s+/g, "").trim();
        if (!moveName) moveName = tmName;
    }

    try {
        const res = await fetch('/api/use_tm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                poke_index: bagWorkflowState.selectedPokeIndex,
                tm_name: tmName,
                move_index: bagWorkflowState.selectedMoveIndex
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            state.ownedItems = data.owned_items;
            await loadGameData();
            renderBagTab();
            
            showBagDialog(bagDialogResult);
            document.getElementById('bag-result-msg').textContent = `${poke.name}は、「${moveName}」をおぼえた！`;
        } else {
            alert(data.message || "わざの習得に失敗しました。");
            hideBagOverlay();
        }
    } catch (err) {
        console.error(err);
        alert("通信エラーが発生しました。");
        hideBagOverlay();
    }
});

// Power source boost stat handler
document.getElementById('bag-stat-cancel-btn').addEventListener('click', () => {
    showBagDialog(bagDialogSelectPoke);
});

document.querySelectorAll('.stat-boost-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const statType = btn.dataset.stat;
        const poke = bagWorkflowState.pokemonList[bagWorkflowState.selectedPokeIndex];
        try {
            const res = await fetch('/api/use_power_source', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    poke_index: bagWorkflowState.selectedPokeIndex,
                    stat_type: statType
                })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                state.ownedItems = data.owned_items;
                await loadGameData();
                renderBagTab();

                showBagDialog(bagDialogResult);
                document.getElementById('bag-result-msg').textContent = data.message;
            } else {
                alert(data.message || "ステータス上昇に失敗しました。");
                hideBagOverlay();
            }
        } catch (err) {
            console.error(err);
            alert("通信エラーが発生しました。");
            hideBagOverlay();
        }
    });
});

document.getElementById('bag-result-close-btn').addEventListener('click', hideBagOverlay);


// Override shop sell rendering to support flat list
function renderShopSellList() {
    const list = document.getElementById('shop-sell-item-list');
    list.innerHTML = '';

    // Show category tabs hide
    document.getElementById('shop-sell-sub-tabs').style.display = 'none';

    if (state.ownedItems.length === 0) {
        const msg = document.createElement('div');
        msg.className = 'bag-empty-msg';
        msg.textContent = '対象のアイテムを持っていません';
        list.appendChild(msg);
        return;
    }

    state.ownedItems.forEach(itemName => {
        const row = document.createElement('div');
        row.className = 'shop-item-row';
        row.textContent = itemName;
        row.dataset.name = itemName;
        row.addEventListener('click', () => {
            list.querySelectorAll('.shop-item-row').forEach(r => r.classList.remove('selected'));
            row.classList.add('selected');
            
            let itemData = state.shopItems.find(i => i['名前'] === itemName);
            if (!itemData && itemName === 'ちからのもと') {
                itemData = {
                    "名前": "ちからのもと",
                    "効果": "ポケモンにつかうと、いずれかのステータスを +3 上昇させる。",
                    "分類": "ちからのもと",
                    "値段": 4000
                };
            }
            if (itemData) selectShopSellItem(itemData);
        });
        list.appendChild(row);
    });
}


// ============================================================
// STRENGTH TAB LOGIC
// ============================================================

function initStrengthTab() {
    document.getElementById('strength-swap-btn').addEventListener('click', async () => {
        try {
            const res = await fetch('/api/swap_pokemon', { method: 'POST' });
            const data = await res.json();
            if (res.ok && data.success) {
                await loadGameData();
                renderStrengthTab();
            } else {
                alert(data.message || '順番の入れ替えに失敗しました。');
            }
        } catch (err) {
            console.error(err);
            alert('通信エラーが発生しました。');
        }
    });

    [0, 1].forEach(idx => {
        document.getElementById(`strength-poke-${idx}`).addEventListener('click', () => {
            const poke = state.myPokemonChoices[idx];
            if (!poke) return;
            state.strengthSelectedPokeIdx = idx;
            showStrengthDetail(poke);
        });
    });

    document.getElementById('detail-back-btn').addEventListener('click', () => {
        document.getElementById('strength-detail').classList.add('hidden');
        document.getElementById('strength-overview').classList.remove('hidden');
    });

    document.getElementById('detail-moves-btn').addEventListener('click', () => {
        const poke = state.myPokemonChoices[state.strengthSelectedPokeIdx];
        if (!poke) return;
        
        for (let i = 0; i < 4; i++) {
            const moveCard = document.getElementById(`detail-move-${i}`);
            const move = poke.moves[i];
            if (move && move.name && move.name !== "-") {
                moveCard.querySelector('.detail-move-name').textContent = move.name;
                moveCard.querySelector('.detail-move-power').textContent = `威力 ${move.power}`;
                moveCard.querySelector('.detail-move-type').textContent = move.type;
                moveCard.style.visibility = 'visible';
            } else {
                moveCard.style.visibility = 'hidden';
            }
        }

        document.getElementById('strength-detail-status').classList.add('hidden');
        document.getElementById('strength-detail-moves').classList.remove('hidden');
    });

    document.getElementById('detail-status-btn').addEventListener('click', () => {
        document.getElementById('strength-detail-moves').classList.add('hidden');
        document.getElementById('strength-detail-status').classList.remove('hidden');
    });

    document.getElementById('detail-unequip-btn').addEventListener('click', async () => {
        const pokeIdx = state.strengthSelectedPokeIdx;
        const poke = state.myPokemonChoices[pokeIdx];
        if (!poke || !poke.item) return;

        if (confirm(`「${poke.item}」を外しますか？`)) {
            try {
                const res = await fetch('/api/equip', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        poke_index: pokeIdx,
                        item_name: null
                    })
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    await loadGameData();
                    const updatedPoke = state.myPokemonChoices[pokeIdx];
                    showStrengthDetail(updatedPoke);
                } else {
                    alert(data.message || 'もちものを外すのに失敗しました。');
                }
            } catch (err) {
                console.error(err);
                alert('通信エラーが発生しました。');
            }
        }
    });
}

function renderStrengthTab() {
    const pokes = state.myPokemonChoices;
    
    document.getElementById('strength-detail').classList.add('hidden');
    document.getElementById('strength-overview').classList.remove('hidden');

    for (let i = 0; i < 2; i++) {
        const card = document.getElementById(`strength-poke-${i}`);
        const nameEl = document.getElementById(`strength-poke-name-${i}`);
        const emojiEl = document.getElementById(`strength-poke-emoji-${i}`);
        
        const poke = pokes[i];
        if (poke) {
            card.style.visibility = 'visible';
            nameEl.textContent = poke.name;
            setPokemonSprite(emojiEl, poke.番号, poke.name);
            emojiEl.classList.add('pokemon-sprite-small');
        } else {
            card.style.visibility = 'hidden';
            nameEl.textContent = "-";
            emojiEl.textContent = "👾";
            emojiEl.style.backgroundImage = 'none';
            emojiEl.classList.remove('pokemon-sprite', 'pokemon-sprite-small');
        }
    }
}

function showStrengthDetail(poke) {
    document.getElementById('strength-overview').classList.add('hidden');
    document.getElementById('strength-detail').classList.remove('hidden');
    document.getElementById('strength-detail-status').classList.remove('hidden');
    document.getElementById('strength-detail-moves').classList.add('hidden');

    document.getElementById('detail-hp').textContent = poke.hp;
    document.getElementById('detail-attack').textContent = poke.attack;
    document.getElementById('detail-defense').textContent = poke.defense;
    document.getElementById('detail-sp-attack').textContent = poke.sp_attack;
    document.getElementById('detail-sp-defense').textContent = poke.sp_defense;

    document.getElementById('detail-name').textContent = poke.name;
    
    const typesStr = [poke.type1, poke.type2].filter(t => t).join(' / ');
    document.getElementById('detail-types').textContent = typesStr || "-";
    
    setPokemonSprite(document.getElementById('detail-sprite'), poke.番号, poke.name);
    
    const itemEl = document.getElementById('detail-item');
    const unequipBtn = document.getElementById('detail-unequip-btn');
    if (poke.item) {
        itemEl.textContent = poke.item;
        unequipBtn.classList.remove('hidden');
    } else {
        itemEl.textContent = "なし";
        unequipBtn.classList.add('hidden');
    }
}


// ============================================================
// BATTLE TAB REAL-TIME CLIENT
// ============================================================
let battlePollingInterval = null;
let currentBattleRole = null;

function showBattleSubview(subviewId) {
    const subviews = [
        'battle-mode-selection',
        'battle-waiting-subview',
        'battle-player-arena-subview',
        'battle-grader-subview'
    ];
    subviews.forEach(id => {
        document.getElementById(id).style.display = (id === subviewId) ? 'flex' : 'none';
    });
}

async function startBattlePolling() {
    if (battlePollingInterval) clearInterval(battlePollingInterval);
    
    async function poll() {
        try {
            const res = await fetch('/api/battle/status');
            const data = await res.json();
            if (data.success) {
                if (data.active) {
                    if (data.role) {
                        state.isJoiningOrWaiting = false; // Reset waiting flag as we are now in battle
                        currentBattleRole = data.role;
                        showBattleSubview('battle-player-arena-subview');
                        updateBattlePlayerArena(data);
                    } else {
                        // Not playing in active battle. Show mode screen (or prompt they are not in battle)
                        if (!data.waiting && !state.isJoiningOrWaiting) {
                            if (document.getElementById('battle-waiting-subview').style.display !== 'none') {
                                showBattleSubview('battle-mode-selection');
                            }
                        }
                    }
                } else {
                    currentBattleRole = null;
                    if (data.waiting || state.isJoiningOrWaiting) {
                        showBattleSubview('battle-waiting-subview');
                    } else {
                        // Check if we are currently in battle subview
                        if (document.getElementById('battle-player-arena-subview').style.display !== 'none') {
                            showBattleSubview('battle-mode-selection');
                            alert("バトルが終了しました。");
                        }
                    }
                }
            }
        } catch (e) {
            console.error("Battle polling error:", e);
        }
    }
    
    await poll();
    battlePollingInterval = setInterval(poll, 1500);
}

function updateBattlePlayerArena(data) {
    const myPoke = data.my_pokemon[data.my_active_idx];
    const oppPoke = data.opp_pokemon[data.opp_active_idx];

    if (!myPoke || !oppPoke) return;

    // My Poke Card details
    document.getElementById('p-my-name').textContent = myPoke.name;
    document.getElementById('p-my-level').textContent = `Lv.${myPoke.level || 50}`;
    const myHpPct = (myPoke.hp / myPoke.max_hp) * 100;
    document.getElementById('p-my-hp-fill').style.width = `${myHpPct}%`;
    document.getElementById('p-my-hp-val').textContent = `${myPoke.hp}/${myPoke.max_hp}`;
    document.getElementById('p-my-types').textContent = [myPoke.type1, myPoke.type2].filter(t => t).join('/');
    setPokemonSprite(document.getElementById('p-my-sprite'), myPoke.番号, myPoke.name);
    updateMatchupDisplay(myPoke, 'p-my-matchup-effective', 'p-my-matchup-ineffective');

    // Opp Poke Card details
    document.getElementById('p-opp-name').textContent = oppPoke.name;
    document.getElementById('p-opp-level').textContent = `Lv.${oppPoke.level || 50}`;
    const oppHpPct = (oppPoke.hp / oppPoke.max_hp) * 100;
    document.getElementById('p-opp-hp-fill').style.width = `${oppHpPct}%`;
    document.getElementById('p-opp-hp-val').textContent = `${oppPoke.hp}/${oppPoke.max_hp}`;
    document.getElementById('p-opp-types').textContent = [oppPoke.type1, oppPoke.type2].filter(t => t).join('/');
    setPokemonSprite(document.getElementById('p-opp-sprite'), oppPoke.番号, oppPoke.name);
    updateMatchupDisplay(oppPoke, 'p-opp-matchup-effective', 'p-opp-matchup-ineffective');

    // Update moves buttons
    for (let i = 0; i < 4; i++) {
        const btn = document.getElementById(`p-move-${i}`);
        const m = myPoke.moves[i];
        if (m && m.name && m.name !== "-") {
            btn.querySelector('.move-title').textContent = m.name;
            btn.querySelector('.move-type').textContent = m.type;
            btn.querySelector('.move-power').textContent = `威力 ${m.power}`;
            btn.style.display = '';
            
            // Grey out move button if move selected or target fainted, or if choice locked
            const isChoiceItem = (myPoke.item === 'こだわりハチマキ' || myPoke.item === 'こだわりメガネ');
            if (data.my_selected_move || myPoke.hp <= 0 || (isChoiceItem && myPoke.choice_lock && m.name !== myPoke.choice_lock)) {
                btn.disabled = true;
            } else {
                btn.disabled = false;
            }
        } else {
            btn.style.display = 'none';
        }
    }

    // Toggle swap button based on status
    const swapBtn = document.getElementById('p-swap-btn');
    if (data.my_swapped || data.swap_requested || myPoke.hp <= 0) {
        swapBtn.disabled = true;
    } else {
        swapBtn.disabled = false;
    }

    // Toggle back button
    const backBtn = document.getElementById('p-back-btn');
    if (data.my_selected_move) {
        backBtn.style.display = 'block';
    } else {
        backBtn.style.display = 'none';
    }
}

// Battle Queue buttons bind
document.getElementById('battle-join-queue-btn').addEventListener('click', async () => {
    state.isJoiningOrWaiting = true;
    showBattleSubview('battle-waiting-subview');
    try {
        const res = await fetch('/api/battle/join', { method: 'POST' });
        const data = await res.json();
        if (!data.success) {
            state.isJoiningOrWaiting = false;
            showBattleSubview('battle-mode-selection');
            alert(data.message);
        }
    } catch (e) {
        state.isJoiningOrWaiting = false;
        showBattleSubview('battle-mode-selection');
        alert("通信エラーが発生しました。");
    }
});

document.getElementById('battle-leave-queue-btn').addEventListener('click', async () => {
    state.isJoiningOrWaiting = false;
    showBattleSubview('battle-mode-selection');
    try {
        await fetch('/api/battle/leave', { method: 'POST' });
    } catch (e) {
        alert("通信エラーが発生しました。");
    }
});

// Grader Join
document.getElementById('battle-start-grading-btn').addEventListener('click', async () => {
    try {
        const res = await fetch('/api/battle/grader/join', { method: 'POST' });
        if (res.ok) {
            showBattleSubview('battle-grader-subview');
        }
    } catch (e) {}
});

// Grader Exit
document.getElementById('grader-exit-btn').addEventListener('click', async () => {
    try {
        await fetch('/api/battle/grader/leave', { method: 'POST' });
        showBattleSubview('battle-mode-selection');
    } catch (e) {}
});

// Grader submit points
document.querySelectorAll('.grader-point-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const pt = parseInt(btn.dataset.point, 10);
        
        // Grey out buttons until score confirmed
        document.querySelectorAll('.grader-point-btn').forEach(b => b.disabled = true);

        try {
            const res = await fetch('/api/battle/grader/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ score: pt })
            });
            const data = await res.json();
            if (data.success) {
                // Keep buttons disabled, start a fast polling check to re-enable when scores array resets
                const checker = setInterval(async () => {
                    const checkRes = await fetch('/api/admin/battle/status');
                    const checkData = await checkRes.json();
                    if (checkData.success && (!checkData.active_battle.active || checkData.active_battle.scores.length === 0)) {
                        document.querySelectorAll('.grader-point-btn').forEach(b => b.disabled = false);
                        clearInterval(checker);
                    }
                }, 1000);
            } else {
                alert(data.message);
                document.querySelectorAll('.grader-point-btn').forEach(b => b.disabled = false);
            }
        } catch (e) {
            document.querySelectorAll('.grader-point-btn').forEach(b => b.disabled = false);
        }
    });
});

// Moves select trigger
for (let i = 0; i < 4; i++) {
    document.getElementById(`p-move-${i}`).addEventListener('click', async () => {
        if (!state.myPokemonChoices || state.myPokemonChoices.length === 0) return;
        
        // Find selected move
        try {
            const statusRes = await fetch('/api/battle/status');
            const statusData = await statusRes.json();
            const myPoke = statusData.my_pokemon[statusData.my_active_idx];
            const m = myPoke.moves[i];
            
            const res = await fetch('/api/battle/select_move', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    move_name: m.name,
                    move_power: m.power,
                    move_type: m.type
                })
            });
            const data = await res.json();
            if (data.success) {
                // UI updates automatically on next poll
            } else {
                alert(data.message);
            }
        } catch (e) {}
    });
}

// Cancel Selected Move (Back Button)
document.getElementById('p-back-btn').addEventListener('click', async () => {
    try {
        const res = await fetch('/api/battle/cancel_move', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            // UI updates automatically on next poll
        }
    } catch (e) {}
});

// Swap Pokemon Request button
document.getElementById('p-swap-btn').addEventListener('click', async () => {
    try {
        const res = await fetch('/api/battle/request_swap', { method: 'POST' });
        const data = await res.json();
        alert(data.message);
    } catch (e) {}
});

// Trigger battle polling when battle tab is selected
const battleTabBtn = document.querySelector('[data-tab="battle"]');
battleTabBtn.addEventListener('click', () => {
    if (state.isJoiningOrWaiting) {
        showBattleSubview('battle-waiting-subview');
    } else {
        showBattleSubview('battle-mode-selection');
    }
    startBattlePolling();
});

// Clear polling on other tab clicks
document.querySelectorAll('.tab-item').forEach(tab => {
    if (tab.dataset.tab !== 'battle') {
        tab.addEventListener('click', () => {
            if (battlePollingInterval) {
                clearInterval(battlePollingInterval);
                battlePollingInterval = null;
            }
        });
    }
});

// Leave queues on browser close/reload
window.addEventListener('pagehide', () => {
    navigator.sendBeacon('/api/battle/leave');
    navigator.sendBeacon('/api/battle/grader/leave');
});

