FROM python:3.9-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    FLASK_APP=app.py

WORKDIR /app

# 安装必要的系统库（字体支持、时区等）
# fonts-noto-cjk 提供基本的CJK字体支持
# libfreetype6 fontconfig 用于reportlab字体渲染
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    fontconfig \
    libjpeg62-turbo \
    fonts-noto-cjk \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 确保数据目录存在（用于挂载卷）
RUN mkdir -p /app/uploads/images /app/exports /app/fonts /app/data

# 暴露端口
EXPOSE 5000

# 使用Gunicorn启动生产服务器 (针对低配服务器优化)
# -w 1: 1个worker进程（0.2核CPU只够1个）
# -k gevent: 使用异步worker，支持并发
# --worker-connections 500: 每个worker最多500并发连接
# -b 0.0.0.0:5000: 绑定地址和端口
# --timeout 120: 请求超时时间
# --access-logfile -: 输出访问日志到标准输出
CMD ["gunicorn", "-w", "1", "-k", "gevent", "--worker-connections", "500", "-b", "0.0.0.0:5000", "--timeout", "120", "--access-logfile", "-", "app:app"]