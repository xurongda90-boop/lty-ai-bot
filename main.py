import os
import json
import time
import logging
import requests
from flask import Flask, request, jsonify

# ========== 配置 ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8682566938:AAHxa7B23p6SPmTJKJ3AX6wNMuvZU3Jp29o")
COZE_API_TOKEN = os.environ.get("COZE_API_TOKEN", "pat_NP962AYJl16Xt4agI3xKjc4wuHbtKIcNFBuxTdAtVOhjVPaUMhWuQdSTrTRQSYqx")
COZE_WORKFLOW_ID = os.environ.get("COZE_WORKFLOW_ID", "7637454716594667573")
COZE_SPACE_ID = os.environ.get("COZE_SPACE_ID", "7637089728185630773")
TELEGRAM_GROUP_CHAT_ID = os.environ.get("TELEGRAM_GROUP_CHAT_ID", "-5290129358")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
COZE_API = "https://api.coze.com/v1/workflow/run"
LTY_TOKEN_API = "https://lty-nu.vercel.app/api/v1/token-usage"

# ========== 员工 API Key 映射 ==========
DEPARTMENT_KEY_MAP = {
    "风控": "lty_YTYjozl01Ff9W4v4U0RNUNljybvgB8Hm",
    "客服": "lty_1NDXjAlyHPdFshjqnT16gqtqKteYBW3C",
    "策略": "lty_QeyZWoJyyOvhXKA1LgY0a4_dxJ6iBM--",
    "合规": "lty_f6vyIMBjiLPDyvN8ylkJPXkFV69UuvDW",
    "运营": "lty_52rPIJ8i3AcHXkzWwJu_a51WloejrvOJ",
    "产品": "lty_3vNYbyQ5V5D-jfhqpgLbavGeMWyVAFfg",
}

# ========== 部门中文名映射 ==========
DEPARTMENT_NAME_MAP = {
    "风控": "AI-01 风控专员",
    "客服": "AI-02 客服代理",
    "策略": "AI-03 策略分析师",
    "合规": "AI-04 合规监测员",
    "运营": "AI-05 运营专员",
    "产品": "AI-06 产品顾问",
}

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

def report_token_usage(department, model="gpt-4o", input_chars=100, output_chars=100, action=None):
    """调用 LTY 看板 API 上报 Token 使用情况（含模型、成本、结果摘要）"""
    api_key = DEPARTMENT_KEY_MAP.get(department)
    if not api_key:
        logger.warning(f"未找到部门 '{department}' 对应的 API Key，跳过上报")
        return False
    
    payload = {
        "model": model,
        "inputChars": input_chars,
        "outputChars": output_chars,
    }
    
    # 补充结果摘要（工作日志）
    if action:
        payload["action"] = action[:100]  # 截取前100字符作为摘要
    
    try:
        resp = requests.post(
            LTY_TOKEN_API,
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=10
        )
        result = resp.json()
        if result.get("ok"):
            logger.info(f"Token 上报成功：部门={department}, model={model}, costHkd={result.get('costHkd')}, action={action[:30] if action else None}")
            return True
        else:
            logger.warning(f"Token 上报失败：{result}")
            return False
    except Exception as e:
        logger.error(f"Token 上报异常：{e}")
        return False

def build_action_summary(department, user_message, response_text):
    """生成工作日志摘要"""
    dept_name = DEPARTMENT_NAME_MAP.get(department, department)
    # 取用户请求前20字符 + 回复前30字符
    req_short = user_message[:20].replace("\n", " ")
    resp_short = response_text[:30].replace("\n", " ") if response_text else ""
    return f"{dept_name}处理：{req_short}… → {resp_short}"

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
            
            # 获取部门信息和回复内容
            department = data.get("department", "")
            response_text = data.get("response") or data.get("output") or data.get("result")
            
            if department:
                output_chars = len(response_text) if response_text else 100
                # 生成工作日志摘要
                action_summary = build_action_summary(department, user_message, response_text)
                # 上报：模型用 gpt-4o，附带结果摘要
                report_token_usage(
                    department=department,
                    model="gpt-4o",
                    input_chars=len(user_message),
                    output_chars=output_chars,
                    action=action_summary
                )
            
            if not response_text:
                response_text = str(data)
            return response_text
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
