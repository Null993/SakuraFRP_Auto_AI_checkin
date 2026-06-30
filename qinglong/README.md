# NATFRP 自动签到（青龙面板版）

基于 Playwright 和智谱 AI 的 NATFRP 自动签到脚本，适用于青龙面板定时运行。

## 依赖管理

请确保青龙容器内已安装以下 Python 依赖：

```txt
playwright>=1.40.0
zhipuai>=2.0.0
pillow>=10.0.0
numpy>=1.24.0
captcha-recognizer>=1.0.2
```

可根据青龙环境使用 `pip` 安装：

```bash
pip install playwright zhipuai pillow numpy captcha-recognizer
```

## 安装浏览器

进入青龙容器：

```bash
docker exec -it qinglong bash
```

安装 Chromium 浏览器：

```bash
playwright install chromium
```

如果提示缺少系统依赖，继续执行：

```bash
playwright install-deps chromium
```

## 配置环境变量

进入青龙面板的「环境变量」，添加以下配置：

| 变量名 | 说明 | 必填 | 示例 |
| --- | --- | --- | --- |
| `NATFRP_USERNAME` | NATFRP 账号用户名 | 是 | `your_username` |
| `NATFRP_PASSWORD` | NATFRP 账号密码 | 是 | `your_password` |
| `ZHIPU_API_KEY` | 智谱 AI 的 API Key | 是 | `abcd1234...` |
| `ZHIPU_MODEL_VISION` | 视觉模型名称 | 否 | `glm-4v-flash` |
| `ZHIPU_MODEL_TEXT` | 文本模型名称 | 否 | `glm-4-flash` |
| `NATFRP_CHECKIN_MAX_ATTEMPTS` | 签到失败后的总尝试次数 | 否 | `3` |
| `NATFRP_CHECKIN_RETRY_INTERVAL` | 签到失败后的重试间隔，单位秒 | 否 | `60` |
| `NATFRP_NOTIFY` | 是否发送青龙通知，设为 `0` 可关闭 | 否 | `1` |

## 添加定时任务

进入青龙面板，打开「定时任务」并点击「新建任务」。

填写以下信息：

| 配置项 | 内容 |
| --- | --- |
| 名称 | `NATFRP自动签到` |
| 命令 | `task ql_natfrp_checkin.py` |
| 定时规则 | `0 8 * * *` |

默认定时规则表示每天早上 8 点执行。



以上配置表示：签到最多尝试 3 次；每次失败后等待 3600 秒再刷新页面并重试；

## 说明

- 登录状态会缓存到青龙数据目录下的 `scripts/natfrp_state.json`。
- 重试刷新页面后，脚本会重新检测登录状态；如果登录过期，会自动重新登录并更新缓存。

