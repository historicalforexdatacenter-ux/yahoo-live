# server.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yfinance as yf
import asyncio
import json
import uvicorn
import datetime as dt

app = FastAPI(title="Yahoo Finance Live Server")

# Allow browser connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ REST ENDPOINT ============ #
@app.get("/history")
async def history(symbol: str = "^GSPC", period: str = "1y", interval: str = "1m"):
    """Return historical data for a symbol."""
    try:
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)
        df.reset_index(inplace=True)
        data = [
            {
                "date": str(row["Date"]),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            }
            for _, row in df.iterrows()
        ]
        return {"symbol": symbol, "period": period, "interval": interval, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============ WEBSOCKET ============ #
async def fetch_quote(symbol: str):
    """Return a near-real-time price using 1-minute data."""
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False)
        if not df.empty:
            last = df.iloc[-1]
            price = float(last["Close"])
            timestamp = last.name
            return {
                "symbol": symbol,
                "price": price,
                "currency": "N/A",
                "timestamp": str(timestamp),
            }
        else:
            return {"symbol": symbol, "error": "No data returned"}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


class ConnectionManager:
    def __init__(self):
        self.connections = set()
        self.symbols = ["^GSPC", "^NDX"]
        self.interval = 15  # seconds

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)
        if len(self.connections) == 1:
            asyncio.create_task(self.stream_prices())

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def stream_prices(self):
        """Fetch latest prices periodically and broadcast to all clients."""
        while self.connections:
            updates = []
            for s in self.symbols:
                quote = await fetch_quote(s)
                updates.append(quote)

            print("Fetched:", updates)  # Debug: shows data in console

            msg = json.dumps({"type": "quotes", "data": updates})
            for ws in list(self.connections):
                try:
                    await ws.send_text(msg)
                except Exception:
                    self.disconnect(ws)

            await asyncio.sleep(self.interval)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            if data.get("type") == "subscribe":
                manager.symbols = data.get("symbols", manager.symbols)
                manager.interval = int(data.get("interval", manager.interval))
    except WebSocketDisconnect:
        manager.disconnect(websocket)

from fastapi.staticfiles import StaticFiles
import os

# Serve client.html as static content
app.mount("/", StaticFiles(directory=os.path.dirname(__file__), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
