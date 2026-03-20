# agent-demo

## 项目描述

`agent-demo` 是一个基于 FastAPI 的智能体后端示例项目，提供多用户会话、流式聊天（SSE）、记忆读写与文件管理等基础能力。  
项目适合作为本地开发验证和二次改造的起点。

## 使用方法

### 方式一：本地运行

1. 安装依赖：

```bash
python -m pip install -r requirements.txt
```

2. 启动服务：

```bash
python run.py
```

3. 访问地址：

- 首页：`http://127.0.0.1`
- OpenAPI：`http://127.0.0.1/docs`

### 方式二：Docker 部署

1. 构建镜像：

```bash
docker build -t agent-demo:latest .
```

2. 启动容器：

```bash
docker run -d --name agent-demo -p 80:80 -v ${PWD}/data:/app/data agent-demo:latest
```

3. 访问地址：

- 首页：`http://127.0.0.1`
- OpenAPI：`http://127.0.0.1/docs`
