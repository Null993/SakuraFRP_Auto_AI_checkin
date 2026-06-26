#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron: 0 8 * * *
new Env('NATFRP自动签到');
"""

import sys
import io
import os
import time
import random
import re
import json
import base64
import traceback
from pathlib import Path
from datetime import datetime
from PIL import Image
from playwright.sync_api import sync_playwright
import numpy as np

SCRIPT_TITLE = "NATFRP自动签到"

# ========= 缓动函数（来自 PyAutoGUI，避免导入整个模块）=========
def easeInOutQuad(n):
    """缓动函数：先加速后减速"""
    if n < 0.5:
        return 2 * n * n
    else:
        n = n * 2 - 1
        return -0.5 * (n * (n - 2) - 1)

def easeOutQuad(n):
    """缓动函数：快速启动，逐渐减速"""
    return -n * (n - 2)

def easeInOutCubic(n):
    """缓动函数：更平滑的加速减速"""
    if n < 0.5:
        return 4 * n * n * n
    else:
        n = n * 2 - 2
        return 0.5 * n * n * n + 1

# ========= 青龙面板环境变量配置 =========
# 在青龙面板中配置以下环境变量：
# NATFRP_USERNAME - NATFRP账号用户名
# NATFRP_PASSWORD - NATFRP账号密码
# ZHIPU_API_KEY - 智谱AI的API Key
# ZHIPU_MODEL_VISION - 视觉模型（可选，默认glm-4v-flash）
# ZHIPU_MODEL_TEXT - 文本模型（可选，默认glm-4-flash）

# ========= 配置 =========
domain = "www.natfrp.com"
target_url = f"https://{domain}/user/"
ALREADY_SIGNED_TEXT = "今天已经签到过啦"

# 青龙面板数据目录
QL_DATA_DIR = Path(os.getenv("QL_DATA_DIR", "/ql/data"))
STATE_FILE = QL_DATA_DIR / "scripts" / "natfrp_state.json"

# ========= 青龙通知 =========
def _load_qinglong_notify_send():
    """加载青龙内置 notify.py 的 send 函数。"""
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        QL_DATA_DIR / "scripts",
        Path("/ql/scripts"),
        Path("/ql/data/scripts"),
    ]
    for path in candidates:
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)

    try:
        from notify import send
        return send
    except Exception as e:
        print(f"[WARNING] 未加载到青龙 notify.py，跳过通知发送: {e}")
        return None

def build_result(status, message, details=None):
    """构建统一运行结果，方便最终通知。"""
    return {
        "status": status,
        "message": message,
        "details": details or [],
    }

def mask_account(account):
    """账号脱敏展示。"""
    if not account:
        return "未配置"
    if len(account) <= 4:
        return account[0] + "***"
    return f"{account[:2]}***{account[-2:]}"

def send_checkin_notification(result, started_at, username=""):
    """发送青龙通知。设置 NATFRP_NOTIFY=0 可关闭。"""
    if os.getenv("NATFRP_NOTIFY", "1").lower() in ("0", "false", "no", "off"):
        print("[INFO] NATFRP_NOTIFY 已关闭，跳过通知")
        return

    send = _load_qinglong_notify_send()
    if not send:
        return

    ended_at = datetime.now()
    elapsed = int((ended_at - started_at).total_seconds())
    title = f"{SCRIPT_TITLE} - {result.get('status', '未知')}"
    lines = [
        f"账号：{mask_account(username)}",
        f"状态：{result.get('status', '未知')}",
        f"结果：{result.get('message', '')}",
        f"耗时：{elapsed} 秒",
        f"时间：{ended_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    details = result.get("details") or []
    if details:
        lines.append("")
        lines.append("详情：")
        lines.extend([f"- {item}" for item in details])

    try:
        send(title, "\n".join(lines))
        print("[INFO] 通知发送完成")
    except Exception as e:
        print(f"[WARNING] 通知发送失败: {e}")

# ========= AI服务类 =========
class AIService:
    """AI服务类，封装所有AI调用逻辑"""
    
    def __init__(self):
        """初始化AI服务，从环境变量读取配置"""
        self.api_key = os.getenv("ZHIPU_API_KEY", "")
        self.model_vision = os.getenv("ZHIPU_MODEL_VISION", "glm-4v-flash")
        self.model_text = os.getenv("ZHIPU_MODEL_TEXT", "glm-4-flash")
        
        if not self.api_key:
            raise ValueError("未找到ZHIPU_API_KEY环境变量，请在青龙面板中配置")
        
        from zhipuai import ZhipuAI
        self.client = ZhipuAI(api_key=self.api_key)
    
    def safe_parse_json(self, text):
        """强力解析 AI 返回的 JSON 列表"""
        try:
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return json.loads(text)
        except Exception:
            return None
    
    def call_vision(self, image_bytes, prompt):
        """调用智谱多模态模型"""
        base64_data = base64.b64encode(image_bytes).decode('utf-8')
        try:
            response = self.client.chat.completions.create(
                model=self.model_vision,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_data}"}}
                    ]
                }]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] AI API 调用失败: {e}")
            return ""
    
    def identify_captcha_row(self, row_img_bytes, row_index):
        """分行识别逻辑"""
        prompt = "这是验证码的一行图片，包含3个格子。请从左到右识别这3个格子的物体名称，只返回一个 JSON 字符串数组，例如：[\"猫\", \"狗\", \"汽车\"]。不要有任何解释文字。"
        res = self.call_vision(row_img_bytes, prompt)
        print(f"[AI] 第 {row_index} 行识别结果: {res}")
        
        parsed = self.safe_parse_json(res)
        if parsed and isinstance(parsed, list):
            while len(parsed) < 3:
                parsed.append("未知")
            return parsed[:3]
        return ["未知", "未知", "未知"]
    
    def semantic_match(self, target, descriptions):
        """语义裁决逻辑"""
        items_text = "\n".join([f"{i+1}. {d}" for i, d in enumerate(descriptions)])
        prompt = f"题目是：找出图片中所有的【{target}】。\n当前 9 个格子的识别结果如下：\n{items_text}\n请根据描述，判断哪些序号（1-9）最符合题目要求？\n返回格式：只返回 JSON 数组，如 [1, 3, 5]。如果没有符合的，返回空数组 []。"
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_text,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.choices[0].message.content.strip()
            print(f"[AI] 语义裁决原始输出: {content}")
            parsed = self.safe_parse_json(content)
            return parsed if isinstance(parsed, list) else []
        except Exception as e:
            print(f"[ERROR] 语义匹配失败: {e}")
            return []

# ========= 验证码识别函数 =========
def identify_gap_with_library(bg_img_bytes):
    """使用 captcha-recognizer 库识别滑块验证码缺口位置"""
    try:
        from captcha_recognizer.slider import Slider
        
        bg_img = Image.open(io.BytesIO(bg_img_bytes))
        bg_arr = np.array(bg_img)
        
        box, confidence = Slider().identify(source=bg_arr, show=False)
        
        if box and len(box) >= 4:
            x1, y1, x2, y2 = box
            gap_position = int(x1)
            print(f"[DEBUG] captcha-recognizer 识别结果: 缺口位置={gap_position}px, 置信度={confidence:.2f}")
            return gap_position
        else:
            print("[WARNING] captcha-recognizer 未识别到缺口")
            return 0
        
    except ImportError as e:
        print(f"[WARNING] captcha-recognizer 库未安装: {e}")
        return 0
    except Exception as e:
        print(f"[ERROR] captcha-recognizer 识别异常: {e}")
        return 0

# ========= 验证码类型检测 =========
def detect_captcha_type(page):
    """检测验证码类型：九宫格或滑块"""
    # 检查九宫格验证码
    grid_visible = False
    grid_selectors = [".geetest_table_box", ".geetest_grid"]
    for selector in grid_selectors:
        try:
            if page.locator(selector).is_visible(timeout=2000):
                grid_visible = True
                break
        except:
            continue
    
    # 检查滑块验证码
    slider_visible = False
    slider_selectors = [".geetest_slider", ".geetest_slider_button", ".geetest_canvas_bg"]
    for selector in slider_selectors:
        try:
            if page.locator(selector).is_visible(timeout=2000):
                slider_visible = True
                break
        except:
            continue
    
    if grid_visible:
        print("[DEBUG] 检测到九宫格验证码")
        return "grid"
    elif slider_visible:
        print("[DEBUG] 检测到滑块验证码")
        return "slider"
    else:
        return "unknown"

# ========= 九宫格验证码处理 =========
def solve_geetest_multistep(page, ai_service):
    """使用AI服务处理九宫格验证码"""
    print("[INFO] 开始处理九宫格验证码...")
    
    img_container = page.locator(".geetest_table_box").first
    if not img_container.is_visible(timeout=3000):
        print("[DEBUG] 验证码容器不可见")
        return False
    
    # 识别题目
    target_object = ""
    tip_img = page.locator(".geetest_tip_img").first
    if tip_img.is_visible(timeout=2000):
        print("[DEBUG] 检测到图片提示，使用AI识别...")
        try:
            target_object = ai_service.call_vision(tip_img.screenshot(), "图中是什么物体？只回答物体名称，不要带标点。")
        except Exception as e:
            print(f"[ERROR] AI识别图片提示失败: {e}")
    else:
        tip_text_loc = page.locator(".geetest_tip_content").first
        if tip_text_loc.is_visible(timeout=2000):
            try:
                target_object = tip_text_loc.inner_text()
            except Exception as e:
                print(f"[ERROR] 读取文本提示失败: {e}")
    
    target_object = re.sub(r'[^\w]', '', target_object)
    print(f">>> [Step 1] 识别题目为：【{target_object}】")
    
    # 逐行抠图识别
    all_descriptions = []
    try:
        grid_bytes = img_container.screenshot()
        grid_img = Image.open(io.BytesIO(grid_bytes))
        w, h = grid_img.size
        row_h = h / 3
        
        for i in range(3):
            top = i * row_h
            bottom = (i + 1) * row_h
            row_crop = grid_img.crop((0, top, w, bottom))
            
            buf = io.BytesIO()
            row_crop.save(buf, format='PNG')
            row_res = ai_service.identify_captcha_row(buf.getvalue(), i+1)
            all_descriptions.extend(row_res)
    except Exception as e:
        print(f"[ERROR] 九宫格识别过程出错: {e}")
        return False
    
    # 语义匹配并模拟点击
    try:
        click_indices = ai_service.semantic_match(target_object, all_descriptions)
        print(f">>> [Final] 最终决定点击序号: {click_indices}")
    except Exception as e:
        print(f"[ERROR] 语义匹配失败: {e}")
        return False
    
    if not click_indices:
        print("[INFO] 未找到匹配项，刷新验证码...")
        try:
            refresh_btn = page.locator(".geetest_refresh").first
            if refresh_btn.is_visible():
                refresh_btn.click()
                time.sleep(2)
        except:
            pass
        return False
    
    try:
        box = img_container.bounding_box()
        cell_w, cell_h = box['width']/3, box['height']/3
        
        for idx in click_indices:
            try:
                val = int(idx)
                if 1 <= val <= 9:
                    r, c = (val-1)//3, (val-1)%3
                    target_x = box['x'] + c*cell_w + cell_w/2
                    target_y = box['y'] + r*cell_h + cell_h/2
                    page.mouse.click(target_x, target_y)
                    time.sleep(random.uniform(0.3, 0.5))
            except:
                continue
    except Exception as e:
        print(f"[ERROR] 获取验证码容器位置失败: {e}")
        return False
    
    # 提交验证
    for sel in [".geetest_commit", "text=确认", ".geetest_submit"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                return True
        except:
            continue
    
    return False

# ========= 滑块验证码处理 =========
def solve_geetest_slider(page, ai_service):
    """使用AI服务处理滑块验证码"""
    print("[INFO] 开始处理滑块验证码...")
    
    # 查找滑块按钮
    slider_button = None
    slider_selectors = [".geetest_slider_button", ".geetest_slider_knob", ".geetest_btn"]
    
    for selector in slider_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                slider_button = btn
                print(f"[DEBUG] 找到滑块按钮: {selector}")
                break
        except:
            continue
    
    if not slider_button:
        print("[ERROR] 未找到滑块按钮")
        return False
    
    button_box = slider_button.bounding_box()
    if not button_box:
        print("[ERROR] 无法获取滑块按钮位置")
        return False
    
    button_initial_x = button_box['x']
    button_x = button_box['x'] + button_box['width'] / 2
    button_y = button_box['y'] + button_box['height'] / 2
    
    # 获取验证码图片
    bg_img_bytes = None
    bg_canvas = None
    
    canvas_selectors = [".geetest_canvas_bg", "canvas.geetest_canvas_bg"]
    for selector in canvas_selectors:
        try:
            canvas = page.locator(selector).first
            if canvas.is_visible(timeout=1000):
                bg_canvas = canvas
                bg_img_bytes = canvas.screenshot()
                print("[DEBUG] 成功获取背景图")
                break
        except:
            continue
    
    if not bg_img_bytes:
        print("[ERROR] 无法获取验证码图片")
        return False
    
    # 使用 captcha-recognizer 识别缺口位置
    gap_position = identify_gap_with_library(bg_img_bytes)
    
    if gap_position <= 0:
        print("[ERROR] 识别到的缺口位置无效")
        return False
    
    # 计算滑动距离
    bg_canvas_box = None
    if bg_canvas:
        try:
            bg_canvas_box = bg_canvas.bounding_box()
        except:
            pass
    
    if bg_canvas_box:
        bg_canvas_x = bg_canvas_box['x']
        offset = button_initial_x - bg_canvas_x
        drag_distance_base = gap_position + offset
        human_error = random.uniform(-5.0, 5.0)
        drag_distance = drag_distance_base + human_error
        target_x = button_x + drag_distance
    else:
        drag_distance_base = gap_position
        human_error = random.uniform(-5.0, 5.0)
        drag_distance = drag_distance_base + human_error
        target_x = button_x + drag_distance
    
    print(f"[INFO] 滑动距离: {drag_distance:.1f}px, 目标位置: {target_x:.1f}px")
    
    # 执行拖动
    try:
        page.mouse.move(button_x, button_y)
        time.sleep(random.uniform(0.1, 0.2))
        page.mouse.down()
        time.sleep(random.uniform(0.1, 0.2))
        
        # 使用缓动函数模拟人类拖动
        steps = random.randint(20, 30)
        easing_functions = [
            easeInOutQuad,
            easeOutQuad,
            easeInOutCubic,
        ]
        easing_func = random.choice(easing_functions)
        
        for i in range(steps):
            progress = easing_func(i / steps)
            jitter_x = random.uniform(-1.5, 1.5)
            jitter_y = random.uniform(-2, 2)
            current_x = button_x + drag_distance * progress + jitter_x
            current_y = button_y + jitter_y
            page.mouse.move(current_x, current_y)
            
            if i < steps * 0.3:
                time.sleep(random.uniform(0.005, 0.015))
            elif i > steps * 0.7:
                time.sleep(random.uniform(0.02, 0.04))
            else:
                time.sleep(random.uniform(0.01, 0.025))
        
        # 超调效果
        if random.random() > 0.5:
            overshoot = random.uniform(2, 5)
            page.mouse.move(target_x + overshoot, button_y + random.uniform(-1, 1))
            time.sleep(random.uniform(0.05, 0.1))
        
        page.mouse.move(target_x, button_y)
        time.sleep(random.uniform(0.15, 0.25))
        page.mouse.up()
        time.sleep(random.uniform(0.5, 1.0))
        
        print("[DEBUG] 滑块拖动完成")
        time.sleep(2)
        
        # 检查验证结果
        captcha_gone = True
        try:
            if page.locator(".geetest_slider").is_visible(timeout=1000):
                captcha_gone = False
        except:
            pass
        
        return captcha_gone
        
    except Exception as e:
        print(f"[ERROR] 拖动滑块失败: {e}")
        return False

# ========= 主逻辑 =========
def find_signed_text_locator(page, timeout=3000):
    """查找已签到文本"""
    try:
        loc = page.get_by_text(ALREADY_SIGNED_TEXT).first
        if loc.is_visible(timeout=timeout):
            return loc
    except: 
        pass
    return None

def main():
    """主函数"""
    print("=" * 60)
    print("NATFRP 自动签到脚本 - 青龙面板版")
    print("=" * 60)
    
    # 从环境变量获取配置
    username = os.getenv("NATFRP_USERNAME", "")
    password = os.getenv("NATFRP_PASSWORD", "")
    
    if not username or not password:
        print("[ERROR] 未配置账号信息，请在青龙面板中设置环境变量：")
        print("  - NATFRP_USERNAME: NATFRP账号用户名")
        print("  - NATFRP_PASSWORD: NATFRP账号密码")
        return build_result(
            "失败",
            "未配置账号信息",
            ["请在青龙面板中设置 NATFRP_USERNAME 和 NATFRP_PASSWORD"],
        )
    
    # 初始化AI服务
    try:
        ai_service = AIService()
        print(f"[INFO] AI服务初始化成功")
        print(f"  - 视觉模型: {ai_service.model_vision}")
        print(f"  - 文本模型: {ai_service.model_text}")
    except Exception as e:
        print(f"[ERROR] AI服务初始化失败: {e}")
        print("[提示] 请在青龙面板中配置 ZHIPU_API_KEY 环境变量")
        return build_result(
            "失败",
            "AI 服务初始化失败",
            [str(e), "请检查 ZHIPU_API_KEY、ZHIPU_MODEL_VISION、ZHIPU_MODEL_TEXT"],
        )
    
    result = build_result("失败", "脚本未完成")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=100)
        
        # 尝试使用缓存的登录状态
        storage_state = None
        if STATE_FILE.exists():
            try:
                print(f"[INFO] 发现登录状态缓存: {STATE_FILE}")
                storage_state = str(STATE_FILE)
            except Exception as e:
                print(f"[WARNING] 读取登录状态缓存失败: {e}")
        
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})
        
        print(f"[INFO] 正在访问: {target_url}")
        
        try:
            page.goto(target_url, timeout=30000)
            print(f"[DEBUG] 页面加载完成")
        except Exception as e:
            print(f"[ERROR] 页面访问失败: {e}")
            browser.close()
            return build_result("失败", "页面访问失败", [str(e), target_url])
        
        # 登录判断
        current_url = page.url
        is_logged_in = True
        
        try:
            username_input_visible = page.locator("#username").is_visible(timeout=2000)
        except:
            username_input_visible = False
        
        if "login" in current_url or username_input_visible:
            is_logged_in = False
            print("[INFO] 检测到需要登录")
            
            try:
                print("[INFO] 正在填写登录信息...")
                page.fill("#username", username)
                page.fill("#password", password)
                page.click("#login")
                
                print("[DEBUG] 等待登录完成...")
                page.wait_for_selector("text=账号信息", timeout=10000)
                
                # 保存登录状态
                try:
                    context.storage_state(path=str(STATE_FILE))
                    print(f"[SUCCESS] 登录成功，状态已保存到: {STATE_FILE}")
                except Exception as e:
                    print(f"[WARNING] 保存登录状态失败: {e}")
                    print("[SUCCESS] 登录成功")
                
                is_logged_in = True
            except Exception as e:
                print(f"[ERROR] 登录失败: {e}")
                browser.close()
                return build_result("失败", "登录失败", [str(e)])
        else:
            print("[INFO] 已登录状态（使用缓存）")
        
        # 处理18岁弹窗
        try:
            btn_18 = page.get_by_text("是，我已满18岁")
            if btn_18.is_visible(timeout=3000): 
                print("[DEBUG] 检测到18岁确认弹窗，正在点击...")
                btn_18.click()
                time.sleep(1)
        except:
            pass
        
        # 签到
        print("[DEBUG] 开始检查签到状态...")
        
        signed_locator = find_signed_text_locator(page)
        if signed_locator:
            print("[SUCCESS] 今日已签到")
            result = build_result("成功", "今日已签到，无需重复签到")
        else:
            print("[DEBUG] 未检测到已签到状态，查找签到按钮...")
            
            sign_btn = page.get_by_text("点击这里签到")
            try:
                sign_btn_visible = sign_btn.is_visible(timeout=3000)
            except:
                sign_btn_visible = False
            
            if sign_btn_visible:
                print("[INFO] 点击签到按钮...")
                sign_success = False
                
                try:
                    sign_btn.click()
                    print("[DEBUG] 已点击签到按钮，等待验证码加载...")
                    
                    # 等待15秒让验证码加载
                    print("[INFO] 等待15秒让验证码完全加载...")
                    for i in range(30):
                        time.sleep(0.5)
                        
                        if (i + 1) % 10 == 0:
                            print(f"[DEBUG] 已等待 {(i+1)*0.5:.1f} 秒...")
                        
                        signed_check = find_signed_text_locator(page, timeout=500)
                        if signed_check:
                            print(f"[SUCCESS] 签到完成（无需验证码）！")
                            sign_success = True
                            break
                    
                    if not sign_success:
                        # 检查验证码
                        captcha_type = detect_captcha_type(page)
                        
                        if captcha_type != "unknown":
                            print(f"[INFO] 检测到验证码类型: {captcha_type}")
                            
                            max_attempts = 3
                            for attempt in range(1, max_attempts + 1):
                                print(f"[DEBUG] 第 {attempt}/{max_attempts} 次尝试处理验证码...")
                                
                                try:
                                    if captcha_type == "grid":
                                        captcha_result = solve_geetest_multistep(page, ai_service)
                                    elif captcha_type == "slider":
                                        captcha_result = solve_geetest_slider(page, ai_service)
                                    else:
                                        captcha_result = False
                                    
                                    if captcha_result:
                                        print("[INFO] 验证码处理成功")
                                        time.sleep(3)
                                        
                                        # 检查是否签到成功
                                        signed_check = find_signed_text_locator(page, timeout=2000)
                                        if signed_check:
                                            print("[SUCCESS] 签到完成！")
                                            sign_success = True
                                            break
                                    else:
                                        print("[WARNING] 验证码处理失败，重试...")
                                        time.sleep(2)
                                        
                                        # 重新检测验证码类型
                                        captcha_type = detect_captcha_type(page)
                                        if captcha_type == "unknown":
                                            print("[DEBUG] 验证码已消失，检查签到状态...")
                                            signed_check = find_signed_text_locator(page, timeout=2000)
                                            if signed_check:
                                                print("[SUCCESS] 签到完成！")
                                                sign_success = True
                                                break
                                
                                except Exception as e:
                                    print(f"[ERROR] 验证码处理异常: {e}")
                                    traceback.print_exc()
                        else:
                            print("[WARNING] 未检测到验证码")
                    
                    if not sign_success:
                        print("[ERROR] 签到失败：超时或验证码处理失败")
                        result = build_result("失败", "签到失败：超时或验证码处理失败")
                    else:
                        result = build_result("成功", "签到完成")
                
                except Exception as e:
                    print(f"[ERROR] 签到过程出错: {e}")
                    traceback.print_exc()
                    result = build_result("失败", "签到过程出错", [str(e)])
            else:
                print("[ERROR] 未找到签到按钮")
                result = build_result("失败", "未找到签到按钮")
        
        print("[INFO] 脚本运行结束")
        print("=" * 60)
        browser.close()
        return result

if __name__ == "__main__":
    started_at = datetime.now()
    notify_username = os.getenv("NATFRP_USERNAME", "")
    final_result = build_result("失败", "脚本异常退出")
    try:
        final_result = main()
        if not final_result:
            final_result = build_result("失败", "脚本未返回运行结果")
    except Exception as e:
        print(f"[ERROR] 脚本异常: {e}")
        traceback.print_exc()
        final_result = build_result("失败", "脚本异常", [str(e)])
    finally:
        send_checkin_notification(final_result, started_at, notify_username)
