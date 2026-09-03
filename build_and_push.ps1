# 交互式 Docker 构建与推送脚本
# 使用方法: 在 PowerShell 中运行 .\build_and_push.ps1

Write-Host "=== Docker 镜像构建与推送工具 ===" -ForegroundColor Cyan

# 1. 检查 Docker 是否运行
docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker 未运行，请先启动 Docker Desktop！"
    exit 1
}

# 2. 获取 Docker Hub 用户名
$username = Read-Host "请输入您的 Docker Hub 用户名 (例如 myuser)"
if ([string]::IsNullOrWhiteSpace($username)) {
    Write-Error "用户名不能为空"
    exit 1
}

# 3. 获取版本标签
$tag = Read-Host "请输入镜像标签 (默认为 latest)"
if ([string]::IsNullOrWhiteSpace($tag)) {
    $tag = "latest"
}

$imageName = "$username/product-system:$tag"

# 4. 登录 Docker Hub
Write-Host "`n正在登录 Docker Hub..." -ForegroundColor Yellow
docker login
if ($LASTEXITCODE -ne 0) {
    Write-Error "登录失败，请检查网络或重试"
    exit 1
}

# 5. 构建镜像 (强制使用 linux/amd64 架构，确保服务器兼容性)
Write-Host "`n正在构建镜像 $imageName (架构: linux/amd64)..." -ForegroundColor Yellow
docker build --platform linux/amd64 -t $imageName .
if ($LASTEXITCODE -ne 0) {
    Write-Error "构建失败！"
    exit 1
}

# 6. 推送镜像
Write-Host "`n正在推送镜像到仓库..." -ForegroundColor Yellow
docker push $imageName
if ($LASTEXITCODE -ne 0) {
    Write-Error "推送失败！"
    exit 1
}

Write-Host "`n=== 操作成功！ ===" -ForegroundColor Green
Write-Host "您的镜像已发布为: $imageName"
Write-Host "在服务器上，您可以运行以下命令部署："
Write-Host "docker run -d -p 5000:5000 --name product-system $imageName" -ForegroundColor Gray
