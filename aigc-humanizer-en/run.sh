source .venv/bin/activate


# 后台运行 app.py，日志按日期输出
mkdir -p logs
nohup python app.py > logs/log.$(date +%Y%m%d) 2>&1 &


