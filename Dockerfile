FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 Python 生成缓存字节码且保证输出能实时打印到 Docker 日志中
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 安装系统所需基础库并清理缓存
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 复制并安装依赖项
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用程序源代码和前端资产
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/

# 预先创建用于持久化 SQLite 的 data 目录
RUN mkdir -p /app/data

# 暴露管理后台端口
EXPOSE 5000

# 启动应用程序
CMD ["python", "app/main.py"]
