"""项目开发启动入口。"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """本地开发启动命令。"""
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)


if __name__ == "__main__":
    main()
