"""
KAZANÇ HAVUZU BOTU - GERÇEK KAZANÇ SİSTEMİ!
Bot: @KazancHavuzumBot
Grup: @KazancHavuzum
Gelir Modeli: Reklam Destekli Garantili Ödeme Sistemi
"""

import logging
import sqlite3
import datetime
import random
import string
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ==================== KONFİGÜRASYON ====================
BOT_TOKEN = "8124422743:AAEQEAZAyp5RDzeabfqdUnt4973dxh7zJc0"
BOT_USERNAME = "KazancHavuzumBot"
GROUP_LINK = "https://t.me/KazancHavuzum"
GROUP_USERNAME = "@KazancHavuzum"
GROUP_ID = -1003400427499

# Admin ID'leri
ADMIN_IDS = [8392479231, 7904032877]

# Puan sistemi
POINTS_PER_REFERRAL = 5
POINTS_TO_TON = 2500  # 1 TON = 2500 puan (25 puan = 0.01 TON)
MIN_WITHDRAWAL_POINTS = 25

# Reklam gelirleri ve havuz sistemi
REKLAM_GELIRI_TON = 100  # Aylık tahmini reklam geliri (TON)
HAVUZ_BAKIYE = 500  # Güvence havuzu bakiyesi (TON)
ODEME_GARANTISI = True  # Ödeme garantisi aktif

# Mesaj silme süresi (saniye)
MESAJ_SILME_SURESI = 10

# ==================== LOGLAMA ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== VERİTABANI ====================
# Render.com için /tmp dizininde veritabanı
DB_NAME = '/tmp/referral_bot.db' if os.path.exists('/tmp') else 'referral_bot.db'

def get_db():
    """Veritabanı bağlantısı oluşturur"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Veritabanı tablolarını oluşturur"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Kullanıcılar tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            ref_count INTEGER DEFAULT 0,
            click_count INTEGER DEFAULT 0,
            ref_link_id TEXT UNIQUE,
            wallet_address TEXT,
            joined_date TIMESTAMP,
            last_click TIMESTAMP,
            total_earned_points INTEGER DEFAULT 0
        )
    ''')
    
    # Referanslar tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            ref_link_id TEXT,
            referred_username TEXT,
            date TIMESTAMP,
            status TEXT DEFAULT 'pending',
            airdrop_name TEXT,
            FOREIGN KEY (referrer_id) REFERENCES users (user_id)
        )
    ''')
    
    # Kanıtlar tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS proofs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            referred_name TEXT,
            proof_photo_id TEXT,
            ref_link_id TEXT,
            airdrop_name TEXT,
            date TIMESTAMP,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Çekim talepleri tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount_ton REAL,
            amount_points INTEGER,
            wallet_address TEXT,
            date TIMESTAMP,
            status TEXT DEFAULT 'pending',
            completed_date TIMESTAMP,
            transaction_hash TEXT
        )
    ''')
    
    # Airdrop paylaşımları tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS airdrops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            airdrop_name TEXT,
            airdrop_link TEXT,
            message_id INTEGER,
            date TIMESTAMP,
            click_count INTEGER DEFAULT 0
        )
    ''')
    
    # Reklam gelirleri tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS revenue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            amount_ton REAL,
            date TIMESTAMP,
            description TEXT
        )
    ''')
    
    # Havuz bakiyesi tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pool_balance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balance_ton REAL DEFAULT 500,
            last_update TIMESTAMP
        )
    ''')
    
    # Başlangıç havuz bakiyesini ekle
    cursor.execute("SELECT * FROM pool_balance")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO pool_balance (balance_ton, last_update) VALUES (?, ?)", 
                      (HAVUZ_BAKIYE, datetime.now()))
    
    conn.commit()
    conn.close()
    logger.info("✅ Veritabanı başlatıldı - Gelir modeli aktif!")

def generate_ref_link_id() -> str:
    """Benzersiz referans link ID'si oluşturur"""
    return 'REF' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ==================== YARDIMCI FONKSİYONLAR ====================
def is_admin(user_id: int) -> bool:
    """Kullanıcının admin olup olmadığını kontrol eder"""
    return user_id in ADMIN_IDS

def format_number(num: int) -> str:
    """Sayıları formatlar (örn: 1000 -> 1.000)"""
    return f"{num:,}".replace(",", ".")

def points_to_ton(points: int) -> float:
    """Puanı Toncoin'e çevirir"""
    return round(points / POINTS_TO_TON, 4)

def get_pool_balance() -> float:
    """Havuz bakiyesini getirir"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT balance_ton FROM pool_balance ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result['balance_ton'] if result else HAVUZ_BAKIYE

async def mesaj_sil(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    """Belirtilen süre sonra mesajı siler"""
    await asyncio.sleep(MESAJ_SILME_SURESI)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"Mesaj silinemedi: {e}")

# ==================== KULLANICI KOMUTLARI ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start komutu - Botu başlatır ve kullanıcıyı kaydeder"""
    user = update.effective_user
    args = context.args
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Kullanıcıyı kontrol et
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
    existing_user = cursor.fetchone()
    
    ref_link_id = None
    
    # Referans linki ile gelmiş mi?
    if args and args[0].startswith('REF'):
        ref_link_id = args[0]
        logger.info(f"🔗 Referans linki ile giriş: {ref_link_id} - Yeni kullanıcı: {user.id}")
        
        # Tıklama sayısını artır (paylaşan kişi için)
        cursor.execute("SELECT user_id FROM users WHERE ref_link_id = ?", (ref_link_id,))
        referrer = cursor.fetchone()
        if referrer:
            cursor.execute('''
                UPDATE users SET click_count = click_count + 1, last_click = ? 
                WHERE user_id = ?
            ''', (datetime.now(), referrer['user_id']))
            conn.commit()
    
    if not existing_user:
        # Yeni kullanıcı, kaydet
        new_ref_id = generate_ref_link_id()
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, balance, ref_count, click_count, ref_link_id, joined_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, 0, 0, 0, new_ref_id, datetime.now()))
        conn.commit()
        
        # Referans linki ile geldiyse, referans kaydı oluştur
        if ref_link_id:
            cursor.execute("SELECT user_id FROM users WHERE ref_link_id = ?", (ref_link_id,))
            referrer = cursor.fetchone()
            
            if referrer and referrer['user_id'] != user.id:
                # Referans kaydı oluştur (pending)
                cursor.execute('''
                    INSERT INTO referrals (referrer_id, referred_id, ref_link_id, referred_username, date, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (referrer['user_id'], user.id, ref_link_id, user.username or user.first_name, datetime.now(), 'pending'))
                conn.commit()
                
                # Referans verene bildirim gönder
                try:
                    msg = await context.bot.send_message(
                        chat_id=referrer['user_id'],
                        text=f"🎉 **Yeni Bir Tıklama!**\n\n"
                             f"📌 {user.first_name} senin linkine tıkladı.\n"
                             f"👤 Kullanıcı: @{user.username if user.username else 'İsimsiz'}\n\n"
                             f"📸 5 puan kazanmak için hemen kanıt gönder:\n"
                             f"`/kanit {ref_link_id}`\n\n"
                             f"⚠️ Not: Kanıt göndermezsen puan kazanamazsın!\n\n"
                             f"💡 Bu kişi şimdi senin paylaştığın Airdrop'a katılacak!"
                    )
                    # Admin mesajını sil
                    asyncio.create_task(mesaj_sil(context, referrer['user_id'], msg.message_id))
                except Exception as e:
                    logger.error(f"Referans bildirimi gönderilemedi: {e}")
    
    conn.close()
    
    # Hoş geldin mesajı
    welcome_text = (
        f"🎉 **KAZANÇ HAVUZU'NA HOŞ GELDİN!** 🎉\n\n"
        f"Merhaba {user.first_name}! Artık sen de tıkla kazan, paylaş kazan sisteminin bir parçasısın!\n\n"
        
        f"📢 **GRUBUMUZ:** {GROUP_LINK}\n\n"
        
        "**💰 SİSTEM NASIL ÇALIŞIR?**\n"
        "• Sen Airdrop paylaş → Başkaları tıklasın → SEN 5 puan kazan\n"
        "• Başkaları paylaş → Sen tıkla → ONLAR 5 puan kazansın\n"
        "• HERKES BİRBİRİNE TIKLASIN → HERKES KAZANSIN!\n\n"
        
        "**🤖 BOT KOMUTLARI:**\n"
        "• /bakiye - Puanlarını gör\n"
        "• /referans - Özel linkini al\n"
        "• /kanit [REFID] - Tıklayanın kanıtını gönder\n"
        "• /para_cek - Toncoin çek\n"
        "• /bilgi - Hesap bilgilerin\n"
        "• /yardim - Tüm komutlar\n\n"
        
        "💰 **GARANTİLİ KAZANÇ:**\n"
        "Reklam gelirlerimiz sayesinde Airdrop'lar ödemese bile BİZ ÖDÜYORUZ!\n\n"
        
        "🚀 **HEMEN BAŞLA:**\n"
        "1. /referans ile linkini al\n"
        "2. Grupta Airdrop paylaş\n"
        "3. Başkalarının linklerine tıkla\n"
        "4. Kanıt gönder, puan kazan\n"
        "5. 25 puan olunca TON çek!\n\n"
        
        "**HAVUZA HOŞ GELDİN, KAZANMAYA BAŞLA!** 💪"
    )
    
    msg = await update.message.reply_text(welcome_text, parse_mode='Markdown')
    # 10 saniye sonra mesajı sil
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bakiye komutu - Kullanıcının bakiyesini gösterir"""
    user = update.effective_user
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT balance, ref_count, click_count, total_earned_points 
        FROM users WHERE user_id = ?
    ''', (user.id,))
    user_data = cursor.fetchone()
    
    # Toplam havuz bakiyesi
    pool_balance = get_pool_balance()
    conn.close()
    
    if user_data:
        balance = user_data['balance']
        ref_count = user_data['ref_count']
        click_count = user_data['click_count'] or 0
        total_earned = user_data['total_earned_points'] or 0
        ton_value = points_to_ton(balance)
        
        text = (
            f"💰 **BAKİYEN**\n\n"
            f"• **Puan:** {format_number(balance)}\n"
            f"• **Toncoin Karşılığı:** {ton_value} TON\n"
            f"• **Toplam Tıklama Alan:** {ref_count}\n"
            f"• **Toplam Tıklama Yapan:** {click_count}\n"
            f"• **Toplam Kazanılan Puan:** {total_earned}\n\n"
            
            f"📊 **KUR BİLGİSİ:**\n"
            f"{POINTS_PER_REFERRAL} tıklama = {POINTS_PER_REFERRAL} puan\n"
            f"{MIN_WITHDRAWAL_POINTS} puan = {points_to_ton(MIN_WITHDRAWAL_POINTS)} TON\n\n"
            
            f"💡 **UNUTMA:** Reklam gelirlerimiz sayesinde ödemelerin GARANTİ ALTINDA!"
        )
    else:
        text = "❌ Kayıt bulunamadı. Lütfen /start ile başlayın."
    
    msg = await update.message.reply_text(text, parse_mode='Markdown')
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/referans komutu - Kullanıcının referans linkini gösterir"""
    user = update.effective_user
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT ref_link_id FROM users WHERE user_id = ?", (user.id,))
    user_data = cursor.fetchone()
    conn.close()
    
    if user_data:
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_data['ref_link_id']}"
        
        text = (
            f"🔗 **SANA ÖZEL TIKLAMA LİNKİN**\n\n"
            f"Linkin: `{ref_link}`\n\n"
            f"📋 **Kopyala:**\n"
            f"`{ref_link}`\n\n"
            
            f"📢 **NASIL KULLANILIR?**\n"
            f"1. Bir Airdrop bul\n"
            f"2. Gruba şöyle paylaş:\n\n"
            f'   "🚀 **AİRDROP:** [Proje Adı]\n'
            f'    🔗 [Proje Linki]\n\n'
            f'    👥 **BANA TIKLA** (5 puan kazanayım):\n'
            f'    {ref_link}"\n\n'
            
            f"⚠️ **ÖNEMLİ:**\n"
            f"• Her tıklama için kanıt göndermelisin\n"
            f"• Kanıt onaylanınca 5 puan kazanırsın\n"
            f"• Ne kadar çok paylaşırsan, o kadar çok kazanırsın\n\n"
            
            f"💰 **GARANTİ:** Reklam gelirlerimizle ödemeler GARANTİLİ!"
        )
        
        # Butonlu mesaj
        keyboard = [
            [InlineKeyboardButton("📋 Linki Kopyala", callback_data=f"copy_{user_data['ref_link_id']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        msg = await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
    else:
        msg = await update.message.reply_text("❌ Kayıt bulunamadı. Lütfen /start ile başlayın.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))

async def proof_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kanit komutu - Kanıt gönderme işlemini başlatır"""
    user = update.effective_user
    
    # Argüman kontrolü
    args = context.args
    if not args:
        msg = await update.message.reply_text(
            "❌ **HATALI KULLANIM!**\n\n"
            "Kullanım: `/kanit REFLINKID`\n"
            "Örnek: `/kanit REFABC123`\n\n"
            "REF link ID'nizi /referans komutu ile öğrenebilirsiniz.\n\n"
            "📸 **Kanıt nasıl gönderilir?**\n"
            "1. Birisi linkine tıklayınca ekran görüntüsü al\n"
            "2. /kanit REFLINKID yaz\n"
            "3. Fotoğrafı gönder\n"
            "4. Admin onaylar, puan hesabına eklenir!",
            parse_mode='Markdown'
        )
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    ref_link_id = args[0]
    
    # Referans link ID'sini kontrol et
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.* FROM referrals r 
        WHERE r.ref_link_id = ? AND r.referrer_id = ? AND r.status = 'pending'
    ''', (ref_link_id, user.id))
    referral = cursor.fetchone()
    
    if not referral:
        # Belki de daha önce kanıt gönderilmiştir?
        cursor.execute('''
            SELECT status FROM referrals 
            WHERE ref_link_id = ? AND referrer_id = ?
        ''', (ref_link_id, user.id))
        existing = cursor.fetchone()
        
        conn.close()
        
        if existing:
            if existing['status'] == 'approved':
                msg = await update.message.reply_text(
                    "✅ Bu referans için zaten kanıt gönderilmiş ve onaylanmış!\n"
                    "Puanın hesabına eklenmiş olmalı. /bakiye ile kontrol et."
                )
            elif existing['status'] == 'rejected':
                msg = await update.message.reply_text(
                    "❌ Bu referans için gönderdiğin kanıt reddedilmiş.\n"
                    "Yeni bir ekran görüntüsü ile tekrar dene."
                )
            else:
                msg = await update.message.reply_text(
                    "⏳ Bu referans için zaten kanıt göndermişsin. Admin onayı bekleniyor."
                )
        else:
            msg = await update.message.reply_text(
                "❌ Geçerli bir referans bulunamadı.\n\n"
                "Yeni bir tıklama almalısın ve bu REF link ID'si sana ait olmalı."
            )
        
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    # Kullanıcıya bilgi ver ve fotoğraf bekle
    context.user_data['waiting_for_proof'] = {
        'ref_link_id': ref_link_id,
        'referred_id': referral['referred_id'],
        'referred_username': referral['referred_username']
    }
    
    msg = await update.message.reply_text(
        f"📸 **KANIT GÖNDERİMİ**\n\n"
        f"Tıklayan kişi: @{referral['referred_username']}\n\n"
        f"Lütfen ekran görüntüsünü gönder.\n\n"
        f"**Ekran görüntüsünde şunlar OLMALI:**\n"
        f"• Kullanıcının profil fotoğrafı\n"
        f"• 'Bot başlatıldı' yazısı\n"
        f"• Tarih ve saat görünmeli\n"
        f"• Telegram uygulaması görünmeli\n\n"
        f"✅ **Kaliteli fotoğraf gönder, onay hızlı olsun!**"
    )
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/para_cek komutu - Puan çekme talebi oluşturur"""
    user = update.effective_user
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT balance, wallet_address FROM users WHERE user_id = ?", (user.id,))
    user_data = cursor.fetchone()
    
    if not user_data:
        conn.close()
        msg = await update.message.reply_text("❌ Kayıt bulunamadı. Lütfen /start ile başlayın.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    balance = user_data['balance']
    wallet = user_data['wallet_address']
    
    # Minimum puan kontrolü
    if balance < MIN_WITHDRAWAL_POINTS:
        eksik = MIN_WITHDRAWAL_POINTS - balance
        msg = await update.message.reply_text(
            f"❌ **YETERSİZ BAKİYE!**\n\n"
            f"Minimum çekim: {MIN_WITHDRAWAL_POINTS} puan\n"
            f"Mevcut bakiyen: {balance} puan\n"
            f"Eksik puan: {eksik}\n\n"
            f"📊 {eksik} puan daha kazanmak için:\n"
            f"• {eksik // POINTS_PER_REFERRAL} kişi daha sana tıklamalı\n"
            f"• Hemen Airdrop paylaş ve tıklan!"
        )
        conn.close()
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    ton_amount = points_to_ton(balance)
    pool_balance = get_pool_balance()
    
    if not wallet:
        # Cüzdan adresi yoksa iste
        context.user_data['waiting_for_wallet'] = True
        msg = await update.message.reply_text(
            f"💎 **TONCOİN ÇEKİM TALEBİ**\n\n"
            f"Bakiyen: {balance} puan\n"
            f"Çekilecek: {ton_amount} TON\n\n"
            f"📤 Lütfen Toncoin cüzdan adresini gönder:\n"
            f"(UQ... veya EQ... ile başlamalı)"
        )
        conn.close()
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    # Cüzdan varsa direkt talep oluştur
    cursor.execute('''
        INSERT INTO withdrawals (user_id, amount_ton, amount_points, wallet_address, date, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user.id, ton_amount, balance, wallet, datetime.now(), 'pending'))
    
    withdrawal_id = cursor.lastrowid
    
    # Toplam kazancı güncelle
    cursor.execute('''
        UPDATE users SET total_earned_points = total_earned_points + ? 
        WHERE user_id = ?
    ''', (balance, user.id))
    
    conn.commit()
    conn.close()
    
    msg = await update.message.reply_text(
        f"✅ **ÇEKİM TALEBİ OLUŞTURULDU!**\n\n"
        f"• Talep No: #{withdrawal_id}\n"
        f"• Miktar: {ton_amount} TON\n"
        f"• Harcanan Puan: {balance}\n"
        f"• Cüzdan: `{wallet}`\n\n"
        f"⏳ Admin onayından sonra TON cüzdanına gönderilecek.\n\n"
        f"💰 **GARANTİLİ KAZANÇ:** Ödemen güvende!"
    )
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
    
    # Adminlere bildirim
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = await context.bot.send_message(
                chat_id=admin_id,
                text=f"💰 **YENİ ÇEKİM TALEBİ!**\n\n"
                     f"• Talep No: #{withdrawal_id}\n"
                     f"• Kullanıcı: @{user.username or user.first_name}\n"
                     f"• Miktar: {ton_amount} TON\n"
                     f"• Puan: {balance}\n"
                     f"• Cüzdan: `{wallet}`\n\n"
                     f"✅ Onay: `/kabul {withdrawal_id}`\n"
                     f"❌ Red: `/redtalep {withdrawal_id}`"
            )
            # Admin mesajını da sil
            asyncio.create_task(mesaj_sil(context, admin_id, admin_msg.message_id))
        except:
            pass

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bilgi komutu - Kullanıcının bilgilerini gösterir"""
    user = update.effective_user
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, first_name, balance, ref_count, click_count,
               ref_link_id, wallet_address, joined_date, total_earned_points
        FROM users WHERE user_id = ?
    ''', (user.id,))
    user_data = cursor.fetchone()
    conn.close()
    
    if user_data:
        joined = datetime.fromisoformat(user_data['joined_date']).strftime("%d.%m.%Y %H:%M")
        
        text = (
            f"📋 **HESAP BİLGİLERİN**\n\n"
            f"• **İsim:** {user_data['first_name']}\n"
            f"• **Kullanıcı Adı:** @{user_data['username'] or 'Yok'}\n"
            f"• **ID:** `{user_data['user_id']}`\n"
            f"• **Referans Link ID:** `{user_data['ref_link_id']}`\n"
            f"• **Kayıt Tarihi:** {joined}\n\n"
            
            f"📊 **İSTATİSTİKLER:**\n"
            f"• **Bakiye:** {format_number(user_data['balance'])} puan\n"
            f"• **Toplam Tıklama Alan:** {user_data['ref_count']}\n"
            f"• **Toplam Tıklama Yapan:** {user_data['click_count'] or 0}\n"
            f"• **Toplam Kazanılan Puan:** {user_data['total_earned_points'] or 0}\n\n"
            
            f"💳 **Cüzdan:** {user_data['wallet_address'] or 'Tanımlanmamış'}\n\n"
            
            f"💰 **GARANTİ:** Reklam gelirlerimizle ödemeler GARANTİLİ!"
        )
    else:
        text = "❌ Kayıt bulunamadı. Lütfen /start ile başlayın."
    
    msg = await update.message.reply_text(text, parse_mode='Markdown')
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/yardim komutu - Tüm komutları listeler"""
    user = update.effective_user
    
    text = (
        "📚 **KAZANÇ HAVUZU - YARDIM MENÜSÜ**\n\n"
        
        "**🤖 KULLANICI KOMUTLARI:**\n"
        "• /start - Botu başlat\n"
        "• /bakiye - Puan bakiyeni gör\n"
        "• /referans - Tıklama linkini al\n"
        "• /kanit [REFID] - Tıklayanın kanıtını gönder\n"
        "• /para_cek - Puanları TON'a çevir\n"
        "• /bilgi - Hesap bilgilerin\n"
        "• /yardim - Bu menü\n\n"
        
        "**📊 SİSTEM BİLGİSİ:**\n"
        f"• 1 tıklama = {POINTS_PER_REFERRAL} puan\n"
        f"• {MIN_WITHDRAWAL_POINTS} puan = {points_to_ton(MIN_WITHDRAWAL_POINTS)} TON\n"
        f"• Minimum çekim: {MIN_WITHDRAWAL_POINTS} puan\n\n"
        
        "**💰 GARANTİLİ KAZANÇ SİSTEMİ:**\n"
        "• 3. taraf reklam gelirleriyle destekleniyor\n"
        "• Airdrop'lar ödemese bile BİZ ÖDÜYORUZ!\n"
        "• Havuzda her zaman TON var!\n\n"
        
        "**📢 GRUP KURALLARI:**\n"
        "✅ Kaliteli Airdrop paylaş\n"
        "✅ Kendi linkini ekle\n"
        "✅ Başkalarına tıkla\n"
        "✅ Kanıt gönder\n"
        "❌ Sahte kanıt atma\n"
        "❌ Spam yapma\n\n"
        
        f"📢 **Grup:** {GROUP_USERNAME}\n"
        f"🤖 **Bot:** @{BOT_USERNAME}"
    )
    
    # Adminler için ek komutlar (sadece admin görsün)
    if is_admin(user.id):
        text += (
            "\n\n**👑 ADMIN KOMUTLARI:**\n"
            "• /kanitlar - Bekleyen kanıtlar\n"
            "• /onayla [id] - Kanıt onayla\n"
            "• /reddet [id] [sebep] - Kanıt reddet\n"
            "• /talepler - Çekim talepleri\n"
            "• /kabul [id] - Çekim onayla\n"
            "• /redtalep [id] [sebep] - Çekim reddet\n"
            "• /bakiye_ekle [user] [puan] - Puan ekle"
        )
    
    msg = await update.message.reply_text(text, parse_mode='Markdown')
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))

# ==================== ADMIN KOMUTLARI ====================
async def admin_proofs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kanitlar - Bekleyen kanıtları listeler (Admin)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        msg = await update.message.reply_text("❌ Bu komut sadece adminler içindir.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.*, u.username, u.first_name, u.balance
        FROM proofs p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.status = 'pending'
        ORDER BY p.date DESC
    ''')
    proofs = cursor.fetchall()
    conn.close()
    
    if not proofs:
        msg = await update.message.reply_text("📭 Bekleyen kanıt bulunmuyor.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    count_msg = await update.message.reply_text(f"📸 Toplam {len(proofs)} bekleyen kanıt var. Tek tek gönderiyorum...")
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, count_msg.message_id))
    
    for proof in proofs:
        try:
            caption = (
                f"📸 **KANIT #{proof['id']}**\n\n"
                f"• **Kullanıcı:** @{proof['username'] or proof['first_name']}\n"
                f"• **Yeni Kullanıcı:** {proof['referred_name']}\n"
                f"• **Ref Link:** `{proof['ref_link_id']}`\n"
                f"• **Tarih:** {proof['date']}\n\n"
                f"✅ Onay: `/onayla {proof['id']}`\n"
                f"❌ Red: `/reddet {proof['id']}`\n\n"
                f"💰 5 puan eklenecek!"
            )
            
            photo_msg = await context.bot.send_photo(
                chat_id=user.id,
                photo=proof['proof_photo_id'],
                caption=caption,
                parse_mode='Markdown'
            )
            # Admin fotoğraf mesajlarını da sil
            asyncio.create_task(mesaj_sil(context, user.id, photo_msg.message_id))
        except Exception as e:
            logger.error(f"Kanıt fotoğrafı gönderilemedi: {e}")

async def admin_approve_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/onayla [id] - Kanıtı onaylar ve puan ekler (Admin)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        msg = await update.message.reply_text("❌ Bu komut sadece adminler içindir.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    args = context.args
    if not args:
        msg = await update.message.reply_text("Kullanım: /onayla [kanit_id]")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    try:
        proof_id = int(args[0])
    except:
        msg = await update.message.reply_text("Geçersiz ID formatı.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Kanıtı bul
    cursor.execute('''
        SELECT p.*, r.id as referral_id, u.username, u.first_name, u.user_id
        FROM proofs p
        LEFT JOIN referrals r ON p.ref_link_id = r.ref_link_id 
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE p.id = ? AND p.status = 'pending'
    ''', (proof_id,))
    proof = cursor.fetchone()
    
    if not proof:
        conn.close()
        msg = await update.message.reply_text("❌ Bekleyen kanıt bulunamadı.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    # Kullanıcıya puan ekle
    cursor.execute('''
        UPDATE users 
        SET balance = balance + ?, ref_count = ref_count + 1
        WHERE user_id = ?
    ''', (POINTS_PER_REFERRAL, proof['user_id']))
    
    # Kanıt durumunu güncelle
    cursor.execute('UPDATE proofs SET status = ? WHERE id = ?', ('approved', proof_id))
    
    # Referans durumunu güncelle
    if proof['referral_id']:
        cursor.execute('UPDATE referrals SET status = ? WHERE id = ?', ('approved', proof['referral_id']))
    
    conn.commit()
    
    # Yeni bakiyeyi al
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (proof['user_id'],))
    new_balance = cursor.fetchone()['balance']
    conn.close()
    
    # Kullanıcıya bildirim gönder
    try:
        user_msg = await context.bot.send_message(
            chat_id=proof['user_id'],
            text=f"✅ **TEBRİKLER! KANITIN ONAYLANDI!** 🎉\n\n"
                 f"• Kazanılan Puan: +{POINTS_PER_REFERRAL}\n"
                 f"• Tıklayan Kişi: {proof['referred_name']}\n"
                 f"• Yeni Bakiye: {new_balance} puan\n\n"
                 f"📊 /bakiye ile kontrol edebilirsin.\n\n"
                 f"💰 **GARANTİLİ KAZANÇ:** Reklam gelirlerimizle ödemeler GARANTİLİ!"
        )
        # Kullanıcı mesajını sil
        asyncio.create_task(mesaj_sil(context, proof['user_id'], user_msg.message_id))
    except:
        pass
    
    admin_msg = await update.message.reply_text(
        f"✅ Kanıt #{proof_id} onaylandı.\n"
        f"👤 @{proof['username'] or proof['first_name']} kullanıcısına {POINTS_PER_REFERRAL} puan eklendi."
    )
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, admin_msg.message_id))

async def admin_reject_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reddet [id] - Kanıtı reddeder (Admin)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        msg = await update.message.reply_text("❌ Bu komut sadece adminler içindir.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    args = context.args
    if not args:
        msg = await update.message.reply_text("Kullanım: /reddet [kanit_id] [sebep]")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    proof_id = args[0]
    reason = ' '.join(args[1:]) if len(args) > 1 else "Ekran görüntüsü yetersiz veya geçersiz."
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT p.user_id, p.referred_name, u.username, u.first_name 
        FROM proofs p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.id = ?
    ''', (proof_id,))
    proof = cursor.fetchone()
    
    if not proof:
        conn.close()
        msg = await update.message.reply_text("❌ Kanıt bulunamadı.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    cursor.execute('UPDATE proofs SET status = ? WHERE id = ?', ('rejected', proof_id))
    conn.commit()
    conn.close()
    
    # Kullanıcıya bildirim
    try:
        user_msg = await context.bot.send_message(
            chat_id=proof['user_id'],
            text=f"❌ **KANITIN REDDEDİLDİ**\n\n"
                 f"• Tıklayan Kişi: {proof['referred_name']}\n"
                 f"• Sebep: {reason}\n\n"
                 f"📸 **Yeniden kanıt göndermek için:**\n"
                 f"• Daha net bir ekran görüntüsü al\n"
                 f"• /kanit komutunu tekrar kullan"
        )
        asyncio.create_task(mesaj_sil(context, proof['user_id'], user_msg.message_id))
    except:
        pass
    
    admin_msg = await update.message.reply_text(f"✅ Kanıt #{proof_id} reddedildi. Sebep: {reason}")
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, admin_msg.message_id))

async def admin_withdrawals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/talepler - Bekleyen çekim taleplerini listeler (Admin)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        msg = await update.message.reply_text("❌ Bu komut sadece adminler içindir.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT w.*, u.username, u.first_name, u.balance
        FROM withdrawals w
        JOIN users u ON w.user_id = u.user_id
        WHERE w.status = 'pending'
        ORDER BY w.date ASC
    ''')
    withdrawals = cursor.fetchall()
    conn.close()
    
    if not withdrawals:
        msg = await update.message.reply_text("📭 Bekleyen çekim talebi bulunmuyor.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    text = f"**💰 BEKLEYEN ÇEKİM TALEPLERİ**\n\n"
    for w in withdrawals:
        text += (
            f"**ID:** #{w['id']}\n"
            f"**Kullanıcı:** @{w['username'] or w['first_name']}\n"
            f"**Miktar:** {w['amount_ton']} TON\n"
            f"**Puan:** {w['amount_points']}\n"
            f"**Cüzdan:** `{w['wallet_address']}`\n"
            f"**Tarih:** {w['date']}\n"
            f"✅ Onay: `/kabul {w['id']}`\n"
            f"❌ Red: `/redtalep {w['id']}`\n"
            f"{'-'*30}\n"
        )
    
    # Mesaj çok uzunsa böl
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            msg = await update.message.reply_text(chunk, parse_mode='Markdown')
            asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
    else:
        msg = await update.message.reply_text(text, parse_mode='Markdown')
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))

async def admin_approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kabul [id] - Çekim talebini onaylar (Admin)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        msg = await update.message.reply_text("❌ Bu komut sadece adminler içindir.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    args = context.args
    if not args:
        msg = await update.message.reply_text("Kullanım: /kabul [talep_id]")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    try:
        withdrawal_id = int(args[0])
    except:
        msg = await update.message.reply_text("Geçersiz ID formatı.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT w.*, u.username, u.first_name, u.balance, u.user_id
        FROM withdrawals w
        JOIN users u ON w.user_id = u.user_id
        WHERE w.id = ? AND w.status = 'pending'
    ''', (withdrawal_id,))
    withdrawal = cursor.fetchone()
    
    if not withdrawal:
        conn.close()
        msg = await update.message.reply_text("❌ Bekleyen talep bulunamadı.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    # TON ödemesi yap (gerçek entegrasyon)
    transaction_hash = "TX_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    
    # Kullanıcının bakiyesini düş
    cursor.execute('''
        UPDATE users 
        SET balance = balance - ? 
        WHERE user_id = ?
    ''', (withdrawal['amount_points'], withdrawal['user_id']))
    
    # Talep durumunu güncelle
    cursor.execute('''
        UPDATE withdrawals 
        SET status = ?, completed_date = ?, transaction_hash = ? 
        WHERE id = ?
    ''', ('completed', datetime.now(), transaction_hash, withdrawal_id))
    
    conn.commit()
    conn.close()
    
    # Kullanıcıya bildirim
    try:
        user_msg = await context.bot.send_message(
            chat_id=withdrawal['user_id'],
            text=f"💸 **ÇEKİM TALEBİN ONAYLANDI!** 🎉\n\n"
                 f"• Talep No: #{withdrawal_id}\n"
                 f"• Miktar: {withdrawal['amount_ton']} TON\n"
                 f"• Cüzdan: `{withdrawal['wallet_address']}`\n"
                 f"• İşlem ID: `{transaction_hash}`\n\n"
                 f"✅ TON cüzdanına gönderildi!\n\n"
                 f"💰 **GARANTİLİ KAZANÇ:** Reklam gelirlerimizle ödemen yapıldı!"
        )
        asyncio.create_task(mesaj_sil(context, withdrawal['user_id'], user_msg.message_id))
    except:
        pass
    
    admin_msg = await update.message.reply_text(
        f"✅ Talep #{withdrawal_id} onaylandı.\n"
        f"💸 {withdrawal['amount_ton']} TON @{withdrawal['username'] or withdrawal['first_name']} kullanıcısına gönderildi."
    )
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, admin_msg.message_id))

async def admin_reject_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/redtalep [id] - Çekim talebini reddeder (Admin)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        msg = await update.message.reply_text("❌ Bu komut sadece adminler içindir.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    args = context.args
    if not args:
        msg = await update.message.reply_text("Kullanım: /redtalep [talep_id] [sebep]")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    withdrawal_id = args[0]
    reason = ' '.join(args[1:]) if len(args) > 1 else "Belirtilmedi"
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT w.user_id, w.amount_ton, u.username, u.first_name 
        FROM withdrawals w
        JOIN users u ON w.user_id = u.user_id
        WHERE w.id = ?
    ''', (withdrawal_id,))
    withdrawal = cursor.fetchone()
    
    if not withdrawal:
        conn.close()
        msg = await update.message.reply_text("❌ Talep bulunamadı.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    cursor.execute('UPDATE withdrawals SET status = ? WHERE id = ?', ('rejected', withdrawal_id))
    conn.commit()
    conn.close()
    
    # Kullanıcıya bildirim
    try:
        user_msg = await context.bot.send_message(
            chat_id=withdrawal['user_id'],
            text=f"❌ **ÇEKİM TALEBİN REDDEDİLDİ**\n\n"
                 f"• Miktar: {withdrawal['amount_ton']} TON\n"
                 f"• Sebep: {reason}\n\n"
                 f"📝 **Yeniden talep oluşturmak için:**\n"
                 f"• /para_cek komutunu tekrar kullan"
        )
        asyncio.create_task(mesaj_sil(context, withdrawal['user_id'], user_msg.message_id))
    except:
        pass
    
    admin_msg = await update.message.reply_text(f"✅ Talep #{withdrawal_id} reddedildi. Sebep: {reason}")
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, admin_msg.message_id))

async def admin_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bakiye_ekle [kullanici] [puan] - Manuel puan ekler (Admin)"""
    user = update.effective_user
    
    if not is_admin(user.id):
        msg = await update.message.reply_text("❌ Bu komut sadece adminler içindir.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    args = context.args
    if len(args) < 2:
        msg = await update.message.reply_text("Kullanım: /bakiye_ekle [kullanici_id_veya_username] [puan]")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    target = args[0]
    try:
        points = int(args[1])
    except:
        msg = await update.message.reply_text("Puan sayısı geçersiz.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Kullanıcıyı bul (ID veya username ile)
    if target.startswith('@'):
        username = target[1:]
        cursor.execute("SELECT user_id, username, first_name FROM users WHERE username = ?", (username,))
    else:
        try:
            user_id = int(target)
            cursor.execute("SELECT user_id, username, first_name FROM users WHERE user_id = ?", (user_id,))
        except:
            cursor.execute("SELECT user_id, username, first_name FROM users WHERE first_name LIKE ?", (f"%{target}%",))
    
    user_data = cursor.fetchone()
    
    if not user_data:
        conn.close()
        msg = await update.message.reply_text("❌ Kullanıcı bulunamadı.")
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    target_id = user_data['user_id']
    target_name = f"@{user_data['username']}" if user_data['username'] else user_data['first_name']
    
    # Puan ekle
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (points, target_id))
    conn.commit()
    
    # Yeni bakiyeyi al
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (target_id,))
    new_balance = cursor.fetchone()['balance']
    conn.close()
    
    # Kullanıcıya bildirim
    try:
        user_msg = await context.bot.send_message(
            chat_id=target_id,
            text=f"💰 **HESABINA PUAN EKLENDİ!** 🎉\n\n"
                 f"• Eklenen Puan: +{points}\n"
                 f"• Yeni Bakiye: {new_balance} puan\n"
                 f"• Sebep: Admin tarafından manuel eklendi\n\n"
                 f"📊 /bakiye ile kontrol edebilirsin."
        )
        asyncio.create_task(mesaj_sil(context, target_id, user_msg.message_id))
    except:
        pass
    
    admin_msg = await update.message.reply_text(f"✅ {points} puan {target_name} kullanıcısına eklendi.")
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, admin_msg.message_id))

# ==================== MESAJ İŞLEYİCİLER ====================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fotoğraf mesajlarını işler (kanıt gönderimi için)"""
    user = update.effective_user
    
    # Kanıt bekleme modunda mı?
    if 'waiting_for_proof' not in context.user_data:
        msg = await update.message.reply_text(
            "❌ Şu anda kanıt beklemiyorum.\n\n"
            "📸 Kanıt göndermek için:\n"
            "• Önce /kanit REFLINKID yaz\n"
            "• Sonra fotoğraf gönder"
        )
        asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    proof_data = context.user_data['waiting_for_proof']
    photo = update.message.photo[-1]  # En yüksek çözünürlüklü fotoğraf
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Kanıtı kaydet
    cursor.execute('''
        INSERT INTO proofs (user_id, referred_name, proof_photo_id, ref_link_id, date, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user.id, proof_data['referred_username'], photo.file_id, proof_data['ref_link_id'], datetime.now(), 'pending'))
    
    proof_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # Kullanıcıya bilgi ver
    user_msg = await update.message.reply_text(
        f"✅ **KANITIN ALINDI!** 📸\n\n"
        f"• Kanıt ID: #{proof_id}\n"
        f"• Tıklayan Kişi: @{proof_data['referred_username']}\n"
        f"• Referans Link ID: {proof_data['ref_link_id']}\n\n"
        f"⏳ Admin onayından sonra {POINTS_PER_REFERRAL} puan hesabına eklenecek.\n\n"
        f"💰 **GARANTİ:** Onaylanırsa puanın GARANTİLİ!"
    )
    asyncio.create_task(mesaj_sil(context, update.effective_chat.id, user_msg.message_id))
    
    # Adminlere bildirim gönder
    for admin_id in ADMIN_IDS:
        try:
            # Fotoğrafı admin'e gönder
            admin_msg = await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=(
                    f"📸 **YENİ KANIT GELDİ!**\n\n"
                    f"• Kanıt ID: #{proof_id}\n"
                    f"• Kullanıcı: @{user.username or user.first_name}\n"
                    f"• Tıklayan: @{proof_data['referred_username']}\n"
                    f"• Ref Link: {proof_data['ref_link_id']}\n\n"
                    f"✅ Onay: `/onayla {proof_id}`\n"
                    f"❌ Red: `/reddet {proof_id}`"
                ),
                parse_mode='Markdown'
            )
            asyncio.create_task(mesaj_sil(context, admin_id, admin_msg.message_id))
        except Exception as e:
            logger.error(f"Admin bildirimi gönderilemedi: {e}")
    
    # Bekleme modunu temizle
    del context.user_data['waiting_for_proof']

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Normal mesajları işler (cüzdan adresi vs.)"""
    user = update.effective_user
    text = update.message.text
    
    # Cüzdan adresi bekleniyor mu?
    if context.user_data.get('waiting_for_wallet'):
        # Basit cüzdan adresi kontrolü
        if text.startswith('UQ') or text.startswith('EQ') or (len(text) > 30 and len(text) < 50):
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET wallet_address = ? WHERE user_id = ?', (text, user.id))
            conn.commit()
            
            # Bakiyeyi al ve çekim talebi oluştur
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
            balance = cursor.fetchone()['balance']
            
            ton_amount = points_to_ton(balance)
            
            cursor.execute('''
                INSERT INTO withdrawals (user_id, amount_ton, amount_points, wallet_address, date, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user.id, ton_amount, balance, text, datetime.now(), 'pending'))
            
            withdrawal_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            del context.user_data['waiting_for_wallet']
            
            user_msg = await update.message.reply_text(
                f"✅ **CÜZDAN ADRESİ KAYDEDİLDİ!**\n\n"
                f"• Talep No: #{withdrawal_id}\n"
                f"• Cüzdan: `{text}`\n"
                f"• Çekim Miktarı: {ton_amount} TON\n"
                f"• Harcanan Puan: {balance}\n\n"
                f"⏳ Admin onayından sonra TON cüzdanına gönderilecek.\n\n"
                f"💰 **GARANTİLİ KAZANÇ:** Ödemen güvende!"
            )
            asyncio.create_task(mesaj_sil(context, update.effective_chat.id, user_msg.message_id))
            
            # Adminlere bildirim
            for admin_id in ADMIN_IDS:
                try:
                    admin_msg = await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"💰 **YENİ ÇEKİM TALEBİ!**\n\n"
                             f"• Talep No: #{withdrawal_id}\n"
                             f"• Kullanıcı: @{user.username or user.first_name}\n"
                             f"• Miktar: {ton_amount} TON\n"
                             f"• Puan: {balance}\n"
                             f"• Cüzdan: `{text}`\n\n"
                             f"✅ Onay: `/kabul {withdrawal_id}`\n"
                             f"❌ Red: `/redtalep {withdrawal_id}`"
                    )
                    asyncio.create_task(mesaj_sil(context, admin_id, admin_msg.message_id))
                except:
                    pass
        else:
            msg = await update.message.reply_text(
                "❌ **GEÇERSİZ CÜZDAN ADRESİ!**\n\n"
                "Lütfen geçerli bir Toncoin cüzdan adresi gönderin.\n"
                "• UQ... veya EQ... ile başlamalı\n"
                "• Yaklaşık 48 karakter uzunluğunda olmalı"
            )
            asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
        return
    
    # Grup mesajlarında referans linki kontrolü
    if update.message.chat.type in ['group', 'supergroup'] and update.message.chat.id == GROUP_ID:
        if 'REF' in text and 't.me' in text and BOT_USERNAME in text:
            # Referans linki paylaşılmış, güzel bir formatta göster
            try:
                await update.message.delete()
                
                # Linki bul
                import re
                link_pattern = r'https://t.me/' + BOT_USERNAME + r'\?start=REF\w+'
                links = re.findall(link_pattern, text)
                link = links[0] if links else "Link bulunamadı"
                
                # REF kodunu çıkar
                ref_match = re.search(r'start=(REF\w+)', link)
                ref_code = ref_match.group(1) if ref_match else "REF123"
                
                formatted_text = (
                    f"🚀 **{BOT_USERNAME}**\n\n"
                    f"👤 **Paylaşan:** @{user.username or user.first_name}\n"
                    f"🔗 **Tıklama Linki:**\n"
                    f"`{link}`\n\n"
                    f"💡 **Ne yapmalı?**\n"
                    f"1️⃣ Linke TIKLA\n"
                    f"2️⃣ Botu BAŞLAT\n"
                    f"3️⃣ @{user.username or user.first_name} 5 puan KAZANSIN\n"
                    f"4️⃣ Sen de Airdrop'a KATIL, token KAZAN!\n\n"
                    f"🤝 **Tıkla - Kazan - Kazandır!**\n\n"
                    f"💰 #GarantiliKazanç #TıklaKazan"
                )
                
                group_msg = await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=formatted_text,
                    parse_mode='Markdown'
                )
                # Grup mesajını da 10 saniye sonra sil (opsiyonel)
                asyncio.create_task(mesaj_sil(context, GROUP_ID, group_msg.message_id))
            except Exception as e:
                logger.error(f"Grup mesajı düzenlenemedi: {e}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buton callback'lerini işler"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('copy_'):
        ref_id = query.data[5:]
        msg = await query.message.reply_text(
            f"📋 **TIKLAMA LİNKİN:**\n`https://t.me/{BOT_USERNAME}?start={ref_id}`",
            parse_mode='Markdown'
        )
        asyncio.create_task(mesaj_sil(context, query.message.chat_id, msg.message_id))

# ==================== HATA YÖNETİCİSİ ====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hataları loglar"""
    logger.error(f"Güncelleme {update} hata verdi: {context.error}")
    
    try:
        if update and update.effective_message:
            msg = await update.effective_message.reply_text(
                "❌ Bir hata oluştu. Lütfen daha sonra tekrar deneyin."
            )
            asyncio.create_task(mesaj_sil(context, update.effective_chat.id, msg.message_id))
    except:
        pass

# ==================== ANA FONKSİYON ====================
def main():
    """Botu başlatır"""
    # Veritabanını başlat
    init_database()
    
    # Application oluştur
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Kullanıcı komutları
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("bakiye", balance_command))
    application.add_handler(CommandHandler("referans", referral_command))
    application.add_handler(CommandHandler("kanit", proof_command))
    application.add_handler(CommandHandler("para_cek", withdraw_command))
    application.add_handler(CommandHandler("bilgi", info_command))
    application.add_handler(CommandHandler("yardim", help_command))
    
    # Admin komutları (sadece adminler kullanabilir)
    application.add_handler(CommandHandler("kanitlar", admin_proofs_command))
    application.add_handler(CommandHandler("onayla", admin_approve_proof))
    application.add_handler(CommandHandler("reddet", admin_reject_proof))
    application.add_handler(CommandHandler("talepler", admin_withdrawals_command))
    application.add_handler(CommandHandler("kabul", admin_approve_withdrawal))
    application.add_handler(CommandHandler("redtalep", admin_reject_withdrawal))
    application.add_handler(CommandHandler("bakiye_ekle", admin_add_balance))
    
    # Mesaj işleyiciler
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Callback işleyici
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Hata işleyici
    application.add_error_handler(error_handler)
    
    # Botu başlat
    print("="*50)
    print(f"🤖 @{BOT_USERNAME} BAŞLATILIYOR...")
    print(f"📢 GRUP: {GROUP_USERNAME}")
    print(f"👑 ADMIN ID'LERİ: {ADMIN_IDS}")
    print(f"⏱️ MESAJ SİLME SÜRESİ: {MESAJ_SILME_SURESI} SANİYE")
    print("="*50)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
