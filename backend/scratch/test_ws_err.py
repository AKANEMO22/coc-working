import asyncio
import json
import websockets
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        res = await client.post("http://127.0.0.1:8000/api/v1/sessions/initiate", json={
            "student_id": "SE171234",
            "target_company": "FPT Software",
            "target_role": "Java Backend Intern"
        })
        sid = res.json()["session_id"]
        print("Created session:", sid)

    async with websockets.connect(f"ws://127.0.0.1:8000/ws/interview/{sid}") as ws:
        m1 = await ws.recv()
        print("M1:", m1[:80])
        try:
            m2 = await ws.recv()
            print("M2:", m2[:80])
        except Exception as e:
            print("M2 error:", type(e), e)

asyncio.run(test())
