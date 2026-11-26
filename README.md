# 校园活动与实践管理平台（AI 协同开发课程设计）

一个用 Python + Streamlit + SQLite 实现的校园活动全流程管理平台，覆盖活动发布、报名、成绩计算、数据清洗、统计看板、预测分群、反馈问答、多模态资料处理、自动化工作流与工具调用助手。大模型相关功能通过 DeepSeek 接口实现，且全部经过校验与降级处理。

## 一、环境要求

- Python 3.11 或更高版本
- Windows 10/11、macOS 或 Linux（路径统一用 pathlib 处理）
- 网络：仅智能功能需要访问 `api.deepseek.com`；业务功能离线可用

## 二、安装与启动

```bash
# 1. 进入项目目录
cd campus-activity

# 2. 创建并激活虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量（可选，不配置则智能功能提示未启用）
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 5. 初始化数据库（可重复运行，不产生重复数据）
python db/init_db.py

# 6. 启动平台
streamlit run app.py
```

浏览器打开终端提示的地址（默认 http://localhost:8501）。

## 三、演示账号

在页面左侧“当前用户”下拉框切换身份（模拟登录，无密码）：

| 用户名 | 角色 | 说明 |
|---|---|---|
| admin | 管理员 | 管理全部活动、运行工作流、查看日志 |
| org_zhang / org_li | 活动组织者 | 只能维护自己发布的活动 |
| stu_001 / stu_002 / stu_003 | 学生 | 报名、提交反馈、查看本人成绩 |

## 四、目录说明

```
app.py                 入口：侧边栏当前用户、首页
pages/                 Streamlit 页面，每个功能一个文件
services/              业务层：规则、清洗、统计、建模、模型调用、工具
db/schema.sql          建表语句
db/init_db.py          建库并写入演示数据
data/raw/              教师下发的只读导入文件
data/docs/             知识库资料（问答用）
data/eval/             评测数据（单元 9 下发）
templates/             Word 模板
outputs/               程序产出：异常清单、证明、名册、报告、归档
logs/                  运行日志
tests/                 pytest 测试与评测脚本
docs/                  需求、数据字典、口径说明、评测与演练记录
.continue/rules/       AI 项目指令
.env.example           配置项示例（不含真实密钥）
```

## 五、分层约定

- `pages/` 只负责界面，不写 SQL、不算业务规则。
- 业务规则和统计口径只在 `services/` 实现，可脱离界面单独测试。
- 全项目只有 `services/llm.py` 读取密钥、创建模型客户端。

## 六、运行测试

```bash
pytest -q
```

评测脚本 `tests/eval_*.py` 需调用模型并产生费用，不纳入 pytest 自动运行，请单独执行。

## 七、已知问题

见 `docs/已知问题.md`（单元 9 填写）。智能功能的实际表现依赖真实接口与本机模拟数据，需在配置密钥后联调验证。
