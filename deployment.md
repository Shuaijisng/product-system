# 部署指南 (Deployment Guide)

## 1. 字体配置 (Critical: Fonts)
由于生成PDF和图片水印需要中文字体，而服务器（尤其是Linux系统）通常没有预装这些字体，**您必须手动添加字体文件**。

### 步骤:
1.  **准备字体文件**：找到一个支持中文的字体文件，例如 `SimHei.ttf` (黑体)。
    -   您可以在 Windows 的 `C:\Windows\Fonts` 下找到它。
    -   或者从网上下载开源字体 `Noto Sans SC`。
2.  **放入项目目录**：
    -   本指南已为您创建了 `fonts` 文件夹：`./fonts/`。
    -   将 `SimHei.ttf` (或 `simhei.ttf`) 复制到该文件夹中。
    -   如果使用其他字体（如 `msyh.ttc`），也可以放入，程序会自动尝试加载。

## 2. Docker 部署 (推荐)

### 方案 A: 使用脚本一键构建 (Windows/PowerShell)
我们为您准备了一个自动化脚本，只需运行即可跟随提示完成。
1. 在 VS Code 终端或 PowerShell 中运行：
   ```powershell
   .\build_and_push.ps1
   ```
2. 输入您的 Docker Hub 用户名和版本号即可。

### 方案 B: 手动命令行构建
如果您更喜欢手动操作，请按以下步骤进行：

1.  **登录 Docker Hub**
    ```bash
    docker login
    ```
    (如果没有账号，请先去 [hub.docker.com](https://hub.docker.com/) 注册)

2.  **构建镜像**
    通常服务器是 Linux 环境，建议指定平台为 `linux/amd64`：
    ```bash
    # 将 "your_username" 替换为您的 Docker Hub 用户名
    docker build --platform linux/amd64 -t your_username/product-system:latest .
    ```

3.  **推送镜像**
    ```bash
    docker push your_username/product-system:latest
    ```

### 服务器端部署 (拉取并运行)
在服务器上，您只需要 `docker-compose.yml` 文件。

1. 修改 `docker-compose.yml`，将 `build: .` 替换为 `image: your_username/product-system:latest`。
   或者直接使用以下命令启动：
   ```bash
   docker run -d \
     --name product-system \
     --restart unless-stopped \
     -p 5000:5000 \
     -v $(pwd)/uploads:/app/uploads \
     -v $(pwd)/data:/app/data \
     -v $(pwd)/exports:/app/exports \
     your_username/product-system:latest
   ```

## 3. 非 Docker 依赖安装 (Dependencies)
在服务器上，您需要安装 Python 依赖项。

```bash
pip install -r requirements.txt
```

`requirements.txt` 文件已包含：
- flask
- pandas
- openpyxl
- reportlab
- pillow

## 3. 运行应用 (Running)

### 直接运行 (Testing/Development)
```bash
python app.py
```

### 生产环境 (Production)
建议使用 `gunicorn` (Linux/Mac) 或 `waitress` (Windows) 来运行。

**Linux (Gunicorn):**
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

**Windows (Waitress):**
```bash
pip install waitress
waitress-serve --port=5000 app:app
```

## 4. 常见问题 (FAQs)
-   **中文显示乱码/方框**：请检查 `fonts` 文件夹下是否有 `SimHei.ttf`，并确保文件名大小写匹配。
-   **文件权限**：确保程序对 `product_images`、`temp_images`、`uploads` 文件夹有读写权限。
-   **端口冲突**：如果 5000 端口被占用，请更改运行端口。
