import os
import logging
import yfinance as yf
import feedparser
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
CAPITAL_INITIAL = float(os.getenv("CAPITAL", 100))
PERTE_MAX = float(os.getenv("PERTE_MAX_TRADE", 60))
SIMULATION = True   # True = argent fictif | False = argent réel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TRADES_FILE = "trades_simulation.json" if SIMULATION else "trades_reel.json"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FICHIER DE SUIVI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    return {
        "capital": CAPITAL_INITIAL,
        "trades": [],
        "trade_ouvert": None,
        "mode": "SIMULATION 🧪" if SIMULATION else "RÉEL 💶",
        "date_debut": datetime.now().strftime("%Y-%m-%d")
    }

def save_trades(data):
    with open(TRADES_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLAVIER PRINCIPAL (boutons permanents en bas)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main_keyboard():
    keyboard = [
        [KeyboardButton("🔍 Scanner"), KeyboardButton("💼 Capital")],
        [KeyboardButton("📊 Récap du jour"), KeyboardButton("📋 Mes trades")],
        [KeyboardButton("📈 Bilan complet"), KeyboardButton("❓ Aide")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOURCES ET MOTS-CLÉS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RSS_FEEDS = {
    "Reuters Finance": "https://feeds.reuters.com/reuters/businessNews",
    "Reuters Health":  "https://feeds.reuters.com/reuters/healthNews",
    "Yahoo Finance":   "https://finance.yahoo.com/news/rssindex",
    "MarketWatch":     "https://feeds.content.dowjones.io/public/rss/mw_topstories",
}

KEYWORDS = {
    "santé/pharma": {
        "mots": ["virus", "pandemic", "vaccine", "outbreak", "WHO", "FDA approval", "disease", "epidemic", "hantavirus", "variant"],
        "actions": ["MRNA", "PFE", "BNTX", "JNJ", "GILD"],
    },
    "énergie": {
        "mots": ["oil", "crude", "OPEC", "energy crisis", "gas", "pipeline"],
        "actions": ["XOM", "CVX", "BP", "SLB", "COP"],
    },
    "défense": {
        "mots": ["war", "conflict", "military", "defense", "NATO", "missile"],
        "actions": ["LMT", "RTX", "NOC", "GD", "BA"],
    },
    "tech/IA": {
        "mots": ["AI", "artificial intelligence", "chip shortage", "semiconductor", "nvidia"],
        "actions": ["NVDA", "AMD", "MSFT", "GOOGL", "META"],
    },
    "crypto": {
        "mots": ["bitcoin", "crypto", "blockchain", "ethereum", "SEC crypto"],
        "actions": ["COIN", "MSTR", "RIOT", "MARA"],
    },
    "alimentation": {
        "mots": ["food crisis", "drought", "wheat", "famine", "agriculture"],
        "actions": ["ADM", "BG", "MOS", "NTR", "DE"],
    }
}

def banniere_mode():
    if SIMULATION:
        return "\n🧪 MODE SIMULATION — Argent fictif\n   Aucun vrai ordre ne sera passé\n"
    else:
        return "\n💶 MODE RÉEL — Ton vrai argent est en jeu\n"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ANALYSE D'UNE ACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def analyser_action(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist  = stock.history(period="30d")
        info  = stock.info
        if hist.empty or len(hist) < 3:
            return None
        prix_actuel   = round(hist["Close"].iloc[-1], 2)
        prix_hier     = round(hist["Close"].iloc[-2], 2)
        variation     = round(((prix_actuel - prix_hier) / prix_hier) * 100, 2)
        volume_actuel = hist["Volume"].iloc[-1]
        volume_moyen  = hist["Volume"].mean()
        ratio_volume  = round(volume_actuel / volume_moyen, 1) if volume_moyen > 0 else 1.0
        delta = hist["Close"].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = round(100 - (100 / (1 + rs.iloc[-1])), 1)
        stop_loss   = round(prix_actuel * 0.935, 2)
        take_profit = round(prix_actuel * 1.11, 2)
        data         = load_trades()
        capital      = data["capital"]
        montant      = round(min(capital * 0.45, PERTE_MAX * 5), 2)
        perte_max_t  = round(montant * 0.065, 2)
        gain_pot     = round(montant * 0.11, 2)
        ratio_rr     = round(gain_pot / perte_max_t, 2) if perte_max_t > 0 else 0
        return {
            "ticker": ticker, "nom": info.get("longName", ticker),
            "secteur": info.get("sector", "N/A"), "prix": prix_actuel,
            "variation": variation, "volume_ratio": ratio_volume, "rsi": rsi,
            "stop_loss": stop_loss, "take_profit": take_profit,
            "montant": montant, "perte_max": perte_max_t,
            "gain_pot": gain_pot, "ratio_rr": ratio_rr, "capital": capital,
        }
    except Exception as e:
        logger.error(f"Erreur analyse {ticker}: {e}")
        return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCANNER LES NEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def scanner_news():
    articles_trouves = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                texte = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                for secteur, data in KEYWORDS.items():
                    for mot in data["mots"]:
                        if mot.lower() in texte:
                            articles_trouves.append({
                                "source": source, "titre": entry.get("title", ""),
                                "secteur": secteur, "mot_cle": mot, "actions": data["actions"],
                            })
                            break
        except Exception as e:
            logger.error(f"Erreur RSS {source}: {e}")
    resultats = []
    if articles_trouves:
        signal = articles_trouves[0]
        for ticker in signal["actions"]:
            analyse = analyser_action(ticker)
            if analyse and analyse["ratio_rr"] >= 1.5 and analyse["rsi"] < 70:
                resultats.append({"signal": signal, "analyse": analyse})
                break
    return resultats

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FORMATER LE MESSAGE DE SIGNAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def formater_signal(signal, a):
    now     = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    rr_ok   = "✅" if a["ratio_rr"] >= 1.5 else "⚠️"
    vol_ok  = "🔥" if a["volume_ratio"] >= 2 else "📊"
    rsi_txt = "pas suracheté — bon point d'entrée 👍" if a["rsi"] < 60 else "proche zone de surachat ⚠️"
    sim_tag = "🧪 [SIMULATION]" if SIMULATION else "💶 [RÉEL]"
    return f"""━━━━━━━━━━━━━━━━━━━━━━━━
🚨 NOUVEAU SIGNAL {sim_tag}
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}
{banniere_mode()}
🌍 CE QUI SE PASSE DANS LE MONDE
{signal['titre']}
📰 Source : {signal['source']}
🔑 Mot-clé : #{signal['mot_cle']}
🏭 Secteur : {signal['secteur'].upper()}

💡 POURQUOI C'EST UNE OPPORTUNITÉ
Quand un événement majeur touche ce secteur,
les marchés réagissent rapidement. Le bot a
analysé les meilleures actions du secteur. 🎯

🏢 L'ACTION CIBLÉE
{a['nom']} — {a['ticker']} 🇺🇸
💰 Prix actuel : {a['prix']}$
📈 Variation du jour : {a['variation']}%

📊 POURQUOI CETTE ACTION
{vol_ok} Volume : x{a['volume_ratio']} vs moyenne 30j
📉 RSI : {a['rsi']} — {rsi_txt}

⚠️ LES RISQUES
❗ La news peut ne pas durer
❗ Le marché peut réagir différemment
❗ Toujours possible de perdre

💸 PROPOSITION DE TRADE
━━━━━━━━━━━━━━━━━━━━━━━━
📥 Achat à        : {a['prix']}$
🛑 Stop-loss      : {a['stop_loss']}$
🎯 Take-profit    : {a['take_profit']}$
💶 Montant        : {a['montant']}€
📉 Perte max      : -{a['perte_max']}€
📈 Gain potentiel : +{a['gain_pot']}€
⚖️ Ratio R/R      : {a['ratio_rr']} {rr_ok}
💼 Capital dispo  : {a['capital']}€
━━━━━━━━━━━━━━━━━━━━━━━━
👇 TON CHOIX"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RÉCAP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generer_recap():
    data      = load_trades()
    now       = datetime.now()
    auj       = now.strftime("%Y-%m-%d")
    trades_j  = [t for t in data["trades"] if t.get("date","").startswith(auj)]
    gagnants  = [t for t in trades_j if t.get("resultat", 0) > 0]
    perdants  = [t for t in trades_j if t.get("resultat", 0) < 0]
    pl_jour   = sum(t.get("resultat", 0) for t in trades_j)
    perf_glob = round(((data["capital"] - CAPITAL_INITIAL) / CAPITAL_INITIAL) * 100, 2)
    total     = len(data["trades"])
    total_g   = len([t for t in data["trades"] if t.get("resultat",0) > 0])
    winrate   = round((total_g / total * 100), 1) if total > 0 else 0
    pl_emoji  = "💚" if pl_jour >= 0 else "🔴"
    sim_tag   = "🧪 SIMULATION" if SIMULATION else "💶 RÉEL"
    msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━
📊 RÉCAP DU JOUR — {sim_tag}
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now.strftime("%A %d %B %Y — %Hh%M")}

📌 AUJOURD'HUI
🔢 Trades : {len(trades_j)}
✅ Gagnants : {len(gagnants)}
❌ Perdants : {len(perdants)}
{pl_emoji} P&L du jour : {'+' if pl_jour >= 0 else ''}{round(pl_jour,2)}€

📌 DEPUIS LE DÉBUT
💼 Capital de départ : {CAPITAL_INITIAL}€
💼 Capital actuel    : {round(data['capital'],2)}€
{'📈' if perf_glob >= 0 else '📉'} Performance : {'+' if perf_glob >= 0 else ''}{perf_glob}%
🎯 Win rate : {winrate}% ({total_g}/{total})

💬 ANALYSE\n"""
    if len(trades_j) == 0:
        msg += "Aucun signal fort aujourd'hui. Mieux vaut ne pas trader que mal trader. 🧘"
    elif pl_jour > 0:
        msg += f"Belle journée ! {len(gagnants)} trade(s) gagnant(s). 💪"
    else:
        msg += "Journée difficile. Les stop-loss ont protégé le capital. 🛡️"
    msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━"
    return msg

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HANDLERS DES BOUTONS DU MENU
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texte = update.message.text

    if texte == "🔍 Scanner":
        await scanner_action(update, context)
    elif texte == "💼 Capital":
        await capital_action(update, context)
    elif texte == "📊 Récap du jour":
        await update.message.reply_text(generer_recap(), reply_markup=main_keyboard())
    elif texte == "📋 Mes trades":
        await trades_action(update, context)
    elif texte == "📈 Bilan complet":
        await bilan_action(update, context)
    elif texte == "❓ Aide":
        await aide_action(update, context)

async def scanner_action(update, context):
    now = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n🔍 SCAN EN COURS...\n━━━━━━━━━━━━━━━━━━━━━━━━\n📅 {now}\n{banniere_mode()}\nAnalyse des news mondiales...\n⏳ 20-30 secondes\n━━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=main_keyboard()
    )
    await lancer_scan(context)

async def capital_action(update, context):
    data  = load_trades()
    perf  = round(((data["capital"] - CAPITAL_INITIAL) / CAPITAL_INITIAL) * 100, 2)
    now   = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    total = len(data["trades"])
    g     = len([t for t in data["trades"] if t.get("resultat",0) > 0])
    wr    = round(g/total*100,1) if total > 0 else 0
    msg   = f"""━━━━━━━━━━━━━━━━━━━━━━━━
💼 TON CAPITAL — {data['mode']}
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}

💰 Départ   : {CAPITAL_INITIAL}€
💼 Actuel   : {round(data['capital'],2)}€
{'📈' if perf >= 0 else '📉'} Perf    : {'+' if perf >= 0 else ''}{perf}%
🔢 Trades   : {total}
🎯 Win rate : {wr}%
━━━━━━━━━━━━━━━━━━━━━━━━"""
    await update.message.reply_text(msg, reply_markup=main_keyboard())

async def trades_action(update, context):
    data = load_trades()
    now  = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    if not data["trades"]:
        await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n📋 HISTORIQUE — {data['mode']}\n━━━━━━━━━━━━━━━━━━━━━━━━\n📅 {now}\n\nAucun trade encore. Le bot cherche des signaux. 🔍\n━━━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=main_keyboard()
        )
        return
    msg = f"━━━━━━━━━━━━━━━━━━━━━━━━\n📋 HISTORIQUE — {data['mode']}\n━━━━━━━━━━━━━━━━━━━━━━━━\n📅 {now}\n\n"
    for t in data["trades"][-10:]:
        r    = round(t.get("resultat",0),2)
        msg += f"{'✅' if r>0 else '❌'} {t.get('ticker')} {'+' if r>=0 else ''}{r}€ — {t.get('date','')[:10]}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, reply_markup=main_keyboard())

async def bilan_action(update, context):
    data   = load_trades()
    now    = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    trades = data["trades"]
    total  = len(trades)
    g      = [t for t in trades if t.get("resultat",0) > 0]
    p      = [t for t in trades if t.get("resultat",0) < 0]
    pl     = round(sum(t.get("resultat",0) for t in trades), 2)
    perf   = round(((data["capital"] - CAPITAL_INITIAL) / CAPITAL_INITIAL) * 100, 2)
    wr     = round(len(g)/total*100,1) if total > 0 else 0
    gm     = round(sum(t["resultat"] for t in g)/len(g),2) if g else 0
    pm     = round(sum(t["resultat"] for t in p)/len(p),2) if p else 0
    best   = max(trades, key=lambda t: t.get("resultat",0))["ticker"] if trades else "N/A"
    best_v = round(max((t.get("resultat",0) for t in trades), default=0),2)
    msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━
📈 BILAN COMPLET — {data['mode']}
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}
🗓️ Depuis : {data.get('date_debut','?')}

💼 CAPITAL
• Départ  : {CAPITAL_INITIAL}€
• Actuel  : {round(data['capital'],2)}€
• P&L net : {'+' if pl>=0 else ''}{pl}€
{'📈' if perf>=0 else '📉'} Perf    : {'+' if perf>=0 else ''}{perf}%

📊 STATS
• Total trades     : {total}
• ✅ Gagnants      : {len(g)} ({wr}%)
• ❌ Perdants      : {len(p)} ({round(100-wr,1)}%)
• Gain moyen       : +{gm}€
• Perte moyenne    : {pm}€
• 🏆 Meilleur trade : {best} +{best_v}€

💬 CONCLUSION\n"""
    if perf > 5:
        msg += "Excellente performance ! 🚀"
    elif perf > 0:
        msg += "Performance positive. Continue ! 💪"
    elif perf > -10:
        msg += "Légèrement négatif. Analyse les trades perdants. 🧐"
    else:
        msg += "À améliorer. Revois les critères de sélection. 🔧"
    msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, reply_markup=main_keyboard())

async def aide_action(update, context):
    now = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━
📖 AIDE — ROBOT DE SCHA
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}
{banniere_mode()}
🔍 Scanner      — Lancer un scan maintenant
💼 Capital      — Voir ton capital actuel
📊 Récap du jour — Résumé de la journée
📋 Mes trades   — 10 derniers trades
📈 Bilan complet — Statistiques du mois
❓ Aide          — Cette page

🔄 Scan auto toutes les 30 min
📊 Récap auto tous les soirs à 20h

🧪 Tu es en MODE SIMULATION
Aucun vrai argent n'est utilisé.
Dans 1 mois tu décides si tu passes
en mode réel. 💪
━━━━━━━━━━━━━━━━━━━━━━━━"""
    await update.message.reply_text(msg, reply_markup=main_keyboard())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now  = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    data = load_trades()
    msg  = f"""━━━━━━━━━━━━━━━━━━━━━━━━
🤖 ROBOT DE SCHA — ACTIF
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}
{banniere_mode()}
Bonjour ! Je surveille les marchés
mondiaux 24h/24 et t'envoie des signaux
quand je détecte une opportunité. 🌍

💼 Capital : {round(data['capital'],2)}€
🛑 Perte max/trade : {PERTE_MAX}€

👇 Utilise les boutons ci-dessous
━━━━━━━━━━━━━━━━━━━━━━━━"""
    await update.message.reply_text(msg, reply_markup=main_keyboard())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCAN AUTOMATIQUE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def lancer_scan(context: ContextTypes.DEFAULT_TYPE):
    data = load_trades()
    if data.get("trade_ouvert"):
        await context.bot.send_message(chat_id=CHAT_ID, text="⚠️ Trade déjà ouvert. Je surveille avant d'en proposer un nouveau.")
        return
    signaux = scanner_news()
    if not signaux:
        now = datetime.now().strftime("%A %d %B %Y — %Hh%M")
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"━━━━━━━━━━━━━━━━━━━━━━━━\n🔍 SCAN TERMINÉ\n━━━━━━━━━━━━━━━━━━━━━━━━\n📅 {now}\n{banniere_mode()}\nAucun signal fort détecté. 😴\nProchain scan dans 30 min. 🔄\n━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return
    for item in signaux:
        msg = formater_signal(item["signal"], item["analyse"])
        kb  = [
            [InlineKeyboardButton("✅ OUI, je prends", callback_data=f"oui_{item['analyse']['ticker']}"),
             InlineKeyboardButton("❌ NON, je passe",  callback_data="non")],
            [InlineKeyboardButton("📊 Plus d'infos",   callback_data=f"info_{item['analyse']['ticker']}")],
        ]
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, reply_markup=InlineKeyboardMarkup(kb))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GESTION DES BOUTONS OUI/NON/INFO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cb   = query.data
    now  = datetime.now().strftime("%A %d %B %Y — %Hh%M")
    data = load_trades()

    if cb.startswith("oui_"):
        ticker  = cb.replace("oui_", "")
        analyse = analyser_action(ticker)
        if not analyse:
            await query.edit_message_text("❌ Données indisponibles. Réessaie.")
            return
        trade = {
            "ticker": ticker, "prix_entree": analyse["prix"],
            "stop_loss": analyse["stop_loss"], "take_profit": analyse["take_profit"],
            "montant": analyse["montant"], "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "statut": "ouvert", "resultat": 0, "simulation": SIMULATION
        }
        data["trade_ouvert"] = trade
        save_trades(data)
        sim_note = "\n🧪 SIMULATION — Aucun vrai ordre passé !\n   Observe comment ça évolue. 👀" if SIMULATION else "\n⚠️ MODE RÉEL — Passe l'ordre sur ton courtier ! 📱"
        await query.edit_message_text(f"""━━━━━━━━━━━━━━━━━━━━━━━━
✅ TRADE ENREGISTRÉ
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}
{sim_note}

🏢 Action      : {ticker}
📥 Prix entrée : {analyse['prix']}$
🛑 Stop-loss   : {analyse['stop_loss']}$
🎯 Take-profit : {analyse['take_profit']}$
💶 Montant     : {analyse['montant']}€

Surveillance toutes les 5 min. 👀
━━━━━━━━━━━━━━━━━━━━━━━━""")

    elif cb == "non":
        await query.edit_message_text(f"━━━━━━━━━━━━━━━━━━━━━━━━\n❌ TRADE REFUSÉ\n━━━━━━━━━━━━━━━━━━━━━━━━\n📅 {now}\n\nBonne décision si tu n'étais pas\nconvaincu. Ne jamais trader sous\nla contrainte. 👌\n\nJe continue à surveiller. 🔄\n━━━━━━━━━━━━━━━━━━━━━━━━")

    elif cb.startswith("info_"):
        ticker  = cb.replace("info_", "")
        analyse = analyser_action(ticker)
        if not analyse:
            await query.edit_message_text("❌ Données indisponibles.")
            return
        rsi_expl = "survendu — bon achat 🟢" if analyse["rsi"] < 30 else ("neutre 🟡" if analyse["rsi"] < 70 else "suracheté ⚠️ 🔴")
        await query.edit_message_text(f"""━━━━━━━━━━━━━━━━━━━━━━━━
📊 ANALYSE DÉTAILLÉE
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}

🏢 {analyse['nom']} ({analyse['ticker']})
🏭 Secteur : {analyse['secteur']}

📈 DONNÉES TECHNIQUES
Prix actuel    : {analyse['prix']}$
Variation/jour : {analyse['variation']}%
Volume vs moy. : x{analyse['volume_ratio']}
RSI (14j)      : {analyse['rsi']} — {rsi_expl}

📖 C'EST QUOI LE RSI ?
• < 30 = trop vendue → opportunité 🟢
• 30-70 = zone normale 🟡
• > 70 = trop achetée → risque 🔴

📖 C'EST QUOI LE VOLUME ?
Si ça triple, les gros fonds bougent
déjà. Signal fort ! 💡

💰 CALCUL
Montant  : {analyse['montant']}€
Perte max: -{analyse['perte_max']}€
Gain pot.: +{analyse['gain_pot']}€
Ratio R/R: {analyse['ratio_rr']} {'✅' if analyse['ratio_rr'] >= 1.5 else '⚠️'}
━━━━━━━━━━━━━━━━━━━━━━━━""")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SURVEILLANCE DU TRADE OUVERT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def surveiller_trade(context: ContextTypes.DEFAULT_TYPE):
    data  = load_trades()
    trade = data.get("trade_ouvert")
    if not trade:
        return
    ticker = trade["ticker"]
    try:
        hist = yf.Ticker(ticker).history(period="1d")
        if hist.empty:
            return
        prix    = round(hist["Close"].iloc[-1], 2)
        now     = datetime.now().strftime("%A %d %B %Y — %Hh%M")
        sim_tag = "🧪 SIMULATION" if SIMULATION else "💶 RÉEL"

        if prix <= trade["stop_loss"]:
            perte = round((prix - trade["prix_entree"]) / trade["prix_entree"] * trade["montant"], 2)
            data["capital"] = round(data["capital"] + perte, 2)
            trade.update({"resultat": perte, "statut": "ferme", "prix_sortie": prix})
            data["trades"].append(trade)
            data["trade_ouvert"] = None
            save_trades(data)
            await context.bot.send_message(chat_id=CHAT_ID, text=f"""━━━━━━━━━━━━━━━━━━━━━━━━
🔴 STOP-LOSS DÉCLENCHÉ — {sim_tag}
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}

📥 Acheté à    : {trade['prix_entree']}$
📤 Vendu à     : {prix}$
🔴 Perte nette : {round(perte,2)}€
🏦 Capital     : {round(data['capital'],2)}€

🧠 POURQUOI ON A PERDU
Le prix est descendu jusqu'au stop-loss
à {trade['stop_loss']}$. Il a protégé ton
capital d'une perte plus grande. 🛡️

Même les meilleurs traders perdent.
Ce qui compte c'est la régularité. 💪
{'🧪 Simulation — aucun vrai argent perdu !' if SIMULATION else '👉 Ferme la position sur ton courtier !'}
━━━━━━━━━━━━━━━━━━━━━━━━""")

        elif prix >= trade["take_profit"]:
            gain = round((prix - trade["prix_entree"]) / trade["prix_entree"] * trade["montant"], 2)
            data["capital"] = round(data["capital"] + gain, 2)
            trade.update({"resultat": gain, "statut": "ferme", "prix_sortie": prix})
            data["trades"].append(trade)
            data["trade_ouvert"] = None
            save_trades(data)
            await context.bot.send_message(chat_id=CHAT_ID, text=f"""━━━━━━━━━━━━━━━━━━━━━━━━
🏆 TRADE GAGNÉ ! — {sim_tag}
━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now}

🎉 Objectif atteint !

📥 Acheté à      : {trade['prix_entree']}$
📤 Vendu à       : {prix}$
💚 Gain net      : +{round(gain,2)}€
🏦 Capital total : {round(data['capital'],2)}€

🧠 POURQUOI ON A GAGNÉ
Le prix a atteint notre objectif de
{trade['take_profit']}$ comme anticipé !
La stratégie event-driven a fonctionné ✅

{'🧪 En simulation — mais en vrai tu aurais gagné !' if SIMULATION else '👉 Ferme la position sur ton courtier !'}
━━━━━━━━━━━━━━━━━━━━━━━━""")
    except Exception as e:
        logger.error(f"Erreur surveillance: {e}")

async def recap_auto(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=CHAT_ID, text=generer_recap())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LANCEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    app = Application.builder().token(TOKEN).build()

    # Commande start uniquement pour démarrer
    app.add_handler(CommandHandler("start", start))

    # Tous les boutons du menu principal
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex("^(🔍 Scanner|💼 Capital|📊 Récap du jour|📋 Mes trades|📈 Bilan complet|❓ Aide)$"),
        handle_menu
    ))

    # Boutons inline OUI/NON/INFO des signaux
    app.add_handler(CallbackQueryHandler(button_handler))

    jq = app.job_queue
    jq.run_repeating(lancer_scan,      interval=1800, first=60)
    jq.run_repeating(surveiller_trade, interval=300,  first=30)
    jq.run_daily(recap_auto, time=datetime.strptime("20:00", "%H:%M").time())

    mode = "🧪 SIMULATION" if SIMULATION else "💶 RÉEL"
    print(f"🤖 Robot de Scha démarré en mode {mode}")
    print("Envoie /start sur Telegram pour faire apparaître les boutons !")
    app.run_polling()

if __name__ == "__main__":
    main()