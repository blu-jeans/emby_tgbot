import random
import string
import requests
import json
import logging
from telegram import Update, Chat
from telegram.ext import ContextTypes

from app.config import config
from app.database import check_user_exists, add_emby_user

logger = logging.getLogger(__name__)

DEFAULT_POLICY = {
    "IsAdministrator": False,
    "IsHidden": True,
    "IsHiddenRemotely": True,
    "IsHiddenFromUnusedDevices": True,
    "IsDisabled": False,
    "EnableRemoteControlOfOtherUsers": False,
    "EnableSharedDeviceControl": False,
    "EnableRemoteAccess": True,
    "EnableLiveTvManagement": True,
    "EnableLiveTvAccess": True,
    "EnableMediaPlayback": True,
    "EnableAudioPlaybackTranscoding": False,
    "EnableVideoPlaybackTranscoding": False,
    "EnablePlaybackRemuxing": False,
    "EnableAllDevices": True,
    "EnableContentDeletion": False,
    "EnableContentDownloading": False,
    "EnableSubtitleDownloading": False,
    "EnableSyncTranscoding": False,
    "EnableMediaConversion": False,
    "EnabledDevices": [],
    "EnablePublicSharing": False,
    "BlockUnratedItems": [],
    "EnableUserPreferenceAccess": True,
    "EnableUserPreferenceOverride": False,
    "EnableSync": False,
    "AllowCameraUpload": False,
    "EnablePhotoIdentification": False,
    "EnablePlugins": True,
    "EnableThemeSongs": True,
    "EnableThemeVideos": True,
    "EnableLyrics": True,
    "EnableInternetProviders": True,
    "EnableAnyRemoteAccess": True,
    "EnableRemoteControlOfDevice": True
}

def generate_random_password(length=12):
    """生成包含字母、数字和符号的随机密码"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for _ in range(length))

def get_default_user_settings():
    """获取模板用户的配置信息"""
    if not config.template_user_id:
        return {"Policy": {}, "Configuration": {}}
    url = f"{config.emby_server_url}/Users/{config.template_user_id}"
    headers = {
        'X-Emby-Token': config.emby_api_key
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Error fetching default user settings ({response.status_code}). Fallback to default.")
            return {"Policy": {}, "Configuration": {}}
    except Exception as e:
        logger.warning(f"Failed to fetch template user settings: {e}. Fallback to default.")
        return {"Policy": {}, "Configuration": {}}


def get_merged_policy():
    """获取合并了自定义配置后的 Policy 字典"""
    policy_payload = DEFAULT_POLICY.copy()
    custom_policy_str = config.policy_json
    if custom_policy_str and custom_policy_str.strip() != '{}':
        try:
            custom_policy = json.loads(custom_policy_str)
            if isinstance(custom_policy, dict):
                policy_payload.update(custom_policy)
        except Exception as e:
            logger.error(f"Error parsing custom policy JSON: {e}")
    return policy_payload

def update_user_policy(user_id):
    """更新 Emby 用户的权限策略"""
    url = f"{config.emby_server_url}/Users/{user_id}/Policy"
    headers = {
        'Content-Type': 'application/json',
        'X-Emby-Token': config.emby_api_key
    }
    policy_payload = get_merged_policy()
    response = requests.post(url, headers=headers, json=policy_payload, timeout=10)
    if response.status_code != 204:
        raise Exception(f'Error updating user policy: {response.status_code} {response.text}')

def set_user_password(user_id, password):
    """设置指定 Emby 用户的密码"""
    url = f"{config.emby_server_url}/Users/{user_id}/Password"
    headers = {
        'Content-Type': 'application/json',
        'X-Emby-Token': config.emby_api_key
    }
    password_payload = {
        "CurrentPw": "",
        "NewPw": password
    }
    response = requests.post(url, headers=headers, json=password_payload, timeout=10)
    if response.status_code != 204:
        raise Exception(f'Error setting user password: {response.status_code} {response.text}')

async def is_user_in_group(context: ContextTypes.DEFAULT_TYPE, user_id):
    """检查 Telegram 用户是否在任意一个白名单群组中"""
    allowed_chats = config.allowed_chat_ids
    if not allowed_chats:
        logger.error("allowed_chat_ids is not configured!")
        return False
        
    for chat_id in allowed_chats:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ['member', 'administrator', 'creator']:
                return True
        except Exception as e:
            logger.warning(f"Error checking status for chat {chat_id} (Ensure the Bot is added to the group): {e}")
            continue
    return False

async def get_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在群组内回复当前群组的 Chat ID"""
    chat = update.effective_chat
    if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        await update.message.reply_text(
            f"📍 **当前群组信息：**\n\n"
            f"🏷️ **群组名称**: `{chat.title}`\n"
            f"🆔 **群组 ID**: `{chat.id}`\n\n"
            f"💡 *您可将此 ID 复制并添加到管理后台的白名单列表中。*"
        , parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ 此命令仅能在群组或超群中使用。")

async def create_emby_user_api(username, password):
    """调用 Emby 接口创建用户"""
    url = f"{config.emby_server_url}/Users/New"
    headers = {
        'Content-Type': 'application/json',
        'X-Emby-Token': config.emby_api_key
    }
    
    # 获取默认合并的策略
    policy = get_merged_policy()
    payload = {
        "Name": username,
        "Policy": policy,
        "IsHidden": True
    }
    
    # 如果设置了 template_user_id，尝试复制它的视图和配置属性
    if config.template_user_id:
        try:
            default_user_settings = get_default_user_settings()
            payload["Configuration"] = default_user_settings.get('Configuration', {})
            ref_policy = default_user_settings.get('Policy', {})
            if ref_policy:
                merged_policy = ref_policy.copy()
                merged_policy.update(policy)
                payload["Policy"] = merged_policy
        except Exception as e:
            logger.warning(f"Failed to clone template user settings: {e}. Falling back to default.")

    response = requests.post(url, headers=headers, json=payload, timeout=10)
    if response.status_code == 200:
        user_data = response.json()
        user_id = user_data['Id']
        # 确保显式调用 policy 更新以合并所有可能漏掉的字段
        update_user_policy(user_id)
        # 设置用户密码
        set_user_password(user_id, password)
        return user_data
    else:
        raise Exception(f'Error creating user: {response.status_code} {response.text}')

async def createaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /createaccount 命令入口"""
    chat_id = update.effective_user.id

    # 1. 检查后台配置是否完整 (允许 template_user_id 留空)
    if not (config.emby_server_url and config.emby_api_key and config.allowed_chat_ids):
        await update.message.reply_text("❌ 系统配置未完成，无法注册账号。请联系管理员登录后台配置 Emby 属性。")
        return

    # 2. 限制在私聊中使用
    if update.effective_chat.type != Chat.PRIVATE:
        await update.message.reply_text("🔒 安全提示：请在私聊（Direct Message）中向机器人发送此命令以创建账号。")
        return

    # 3. 校验用户是否在白名单群组中
    if not await is_user_in_group(context, chat_id):
        await update.message.reply_text("⚠️ 鉴权失败：您必须是本群组成员才具备注册 Emby 账号的资格。")
        return

    # 4. 校验是否已开通过账户（一户一码）
    if check_user_exists(chat_id):
        await update.message.reply_text("🚫 重复注册：您已经创建过 Emby 账号，每个 Telegram 账户限注册一个，不可重复创建。")
        return

    # 5. 校验并提取用户名
    cmd_args = update.message.text.split()
    if len(cmd_args) < 2:
        await update.message.reply_text("💡 使用帮助：请在命令后附加您希望创建的用户名。\n格式：`/createaccount <用户名>`\n（用户名建议仅使用字母和数字）")
        return

    username = cmd_args[1].strip()
    
    # 简单过滤用户名防注入或非法字符
    if not username.isalnum():
        await update.message.reply_text("❌ 格式错误：用户名只能包含字母和数字。")
        return

    password = generate_random_password()
    
    # 6. 发起创建并处理结果
    status_message = await update.message.reply_text("⏳ 正在为您开通 Emby 账户，请稍候...")
    
    try:
        await create_emby_user_api(username, password)
        
        # 存入数据库
        add_emby_user(chat_id, username, password)

        response_message = (
            f"🎉 **Emby 账号开通成功！**\n\n"
            f"👤 **用户名**: `{username}`\n"
            f"🔑 **密　码**: `{password}`\n"
            f"🌐 **服务器地址**: {config.emby_proxy_url or config.emby_server_url}\n\n"
            f"⚠️ *请妥善保管您的密码，不要泄露给他人。*"
        )
        await status_message.edit_text(response_message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to create account for user {chat_id}: {e}")
        await status_message.edit_text(f"❌ 注册失败：创建账户时服务器发生错误。\n错误信息：{str(e)}")
