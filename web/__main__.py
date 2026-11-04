import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "web.app:app",
        host=os.environ.get("WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("WEB_PORT", "8000")),
    )
