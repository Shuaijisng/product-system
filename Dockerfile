FROM python:3.9-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    FLASK_APP=app.py

WORKDIR /app

# 安装必要的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    fontconfig \
    libjpeg62-turbo \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 确保数据目录存在（用于挂载卷）
RUN mkdir -p /app/uploads/images /app/uploads/pending_images /app/exports /app/data

# 暴露端口
EXPOSE 5000

# 使用Gunicorn启动生产服务器（sync worker，简单稳定）
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "120", "--access-logfile", "-", "app:app"]