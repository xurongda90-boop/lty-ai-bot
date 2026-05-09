import os
import json
import time
import logging
import requests
from flask import Flask, request, jsonify

# ========== 配置 ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8682566938:AAHxa7B23p6SPmTJKJ3AX6wNMuvZU3Jp29o")
COZE_API_TOKEN = os.environ.get("COZE_API_TOKEN", "pat_rg7DcUsUD6XHYVsw7VKYc0Z8WvJPgMo6qnCUHoEW5VJ3qUGm29nQ6PgYGTuC8dgm")
COZE_WORKFLOW_ID = os.environ.get("COZE_WORKFLOW_ID", "7637848097054425141")
COZE_SPACE_ID = os.environ.get("COZE_SPACE_ID", "7637048266257596432")
TELEGRAM_GROUP_CHAT_ID = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "-5290129358")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
COZE_API = "https://api.coze.com/v1/workflow/run"

# ========== 日志 ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def send_telegram_message(chat_id, text, reply_to_message_id=None):
    """发送 Telegram 消息"""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    
    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=30)
        return resp.json()
    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        return None

def call_coze_workflow(user_message, user_id="anonymous"):
    """调用 Coze 工作流"""
    headers = {
        "Authorization": f"Bearer {COZE_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "workflow_id": COZE_WORKFLOW_ID,
        "space_id": COZE_SPACE_ID,
        "parameters": {
            "user_request": user_message,
            "user_id": str(user_id)
        }
    }
    
    try:
        logger.info(f"调用工作流，消息：{user_message[:50]}...")
        resp = requests.post(COZE_API, headers=headers, json=payload, timeout=60)
        result = resp.json()
        logger.info(f"工作流返回：{json.dumps(result, ensure_ascii=False)[:200]}")
        
        if result.get("code") == 0:
            data = result.get("data", "{}")
            if isinstance(data, str):
                data = json.loads(data)
            # 尝试获取 response 字段
            response = data.get("response") or data.get("output") or data.get("result")
            if not response:
                # 如果没有标准字段，返回整个 data
                response = str(data)
            return response
        else:
            error_msg = result.get("msg", "工作流调用失败")
            logger.error(f"工作流错误：{error_msg}")
            return f"抱歉，处理您的请求时出现问题：{error_msg}"
    except Exception as e:
        logger.error(f"调用工作流异常：{e}")
        return "抱歉，系统暂时无法处理您的请求，请稍后再试。"

@app.route("/webhook", methods=["POST"])
def webhook():
    """接收 Telegram Webhook 消息"""
    try:
        update = request.get_json()
        logger.info(f"收到更新：{json.dumps(update, ensure_ascii=False)[:200]}")
        
        message = update.get("message") or update.get("edited_message")
        if not message:
            return jsonify({"ok": True})
        
        chat_id = message["chat"]["id"]
        chat_type = message["chat"]["type"]
        message_id = message["message_id"]
        text = message.get("text", "")
        user_id = message["from"]["id"]
        
        # 忽略空消息
        if not text:
            return jsonify({"ok": True})
        
        bot_username = "LTYAIDepartment_bot"
        
        # 群组消息：只处理 @机器人 的消息
        if chat_type in ["group", "supergroup"]:
            mention = f"@{bot_username}"
            if mention.lower() not in text.lower():
                return jsonify({"ok": True})
            # 去掉 @机器人 前缀
            user_message = text.replace(mention, "").replace(mention.lower(), "").strip()
            if not user_message:
                user_message = "你好"
        else:
            # 私聊：直接处理所有消息
            user_message = text
        
        logger.info(f"处理消息：{user_message} (来自用户 {user_id}，群组 {chat_id})")
        
        # 发送"正在处理"提示
        send_telegram_message(chat_id, "⏳ 正在处理您的请求，请稍候...", reply_to_message_id=message_id)
        
        # 调用 Coze 工作流
        response = call_coze_workflow(user_message, user_id)
        
        # 发送回复
        send_telegram_message(chat_id, response, reply_to_message_id=message_id)
        
        return jsonify({"ok": True})
    
    except Exception as e:
        logger.error(f"处理 Webhook 异常：{e}")
        return jsonify({"ok": True})

@app.route("/", methods=["GET"])
def index():
    return "LTY AI Department Bot is running! 🤖"

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot": "LTY AI Department Bot"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
