#!/usr/bin/env python3
"""
E-Paper DND Display

Connects to Home Assistant via WebSocket and displays a DND status
on a Waveshare 7.5 inch tri-colour e-Paper display.

Environment variables:
    HA_BASE_URL: Home Assistant base URL (e.g. http://192.168.1.100:8123)
    HA_TOKEN: Long-lived access token
    HA_ENTITY_ID: Entity ID to monitor (default: input_boolean.office_dnd)
    HA_MIN_REFRESH_SECONDS: Minimum seconds between display refreshes (default: 10)
"""

import asyncio
import datetime
import json
import os
import ssl
import sys
import time
from urllib.parse import urlparse

import requests
import websockets
from PIL import Image, ImageDraw, ImageFont

# Add Waveshare library path
EPAPER_LIB_PATH = "/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib"
if EPAPER_LIB_PATH not in sys.path:
    sys.path.append(EPAPER_LIB_PATH)

# Configuration from environment
HA_BASE_URL = os.environ.get('HA_BASE_URL')
HA_TOKEN = os.environ.get('HA_TOKEN')
HA_ENTITY_ID = os.environ.get('HA_ENTITY_ID', 'input_boolean.office_dnd')
MIN_REFRESH_SECONDS = int(os.environ.get('HA_MIN_REFRESH_SECONDS', '10'))


def ensure_env():
    """Validate required environment variables."""
    if not HA_BASE_URL:
        raise RuntimeError("HA_BASE_URL env var not set")
    if not HA_TOKEN:
        raise RuntimeError("HA_TOKEN env var not set")


def get_epd():
    """Import and initialize the e-Paper display driver."""
    try:
        from waveshare_epd import epd7in5bc
        epd = epd7in5bc.EPD()
        try:
            epd.init()
        except AttributeError:
            epd.Init()
        try:
            epd.Clear()
        except AttributeError:
            epd.clear()
        return epd
    except ImportError:
        print("Waveshare library not found - running in simulation mode")
        return None


def get_font(height: int):
    """Get the main font scaled to display height."""
    try:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        size = max(18, height // 4)
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def get_small_font(height: int):
    """Get a smaller font for timestamps."""
    try:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        size = max(10, height // 24)
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def render_state_image(width: int, height: int, state: str):
    """Render the display images for a given state."""
    # For 1-bit images: 1 = white, 0 = black/colored
    black_img = Image.new("1", (width, height), 1)
    red_img = Image.new("1", (width, height), 1)

    draw_b = ImageDraw.Draw(black_img)
    draw_r = ImageDraw.Draw(red_img)

    font = get_font(height)
    small_font = get_small_font(height)

    now = datetime.datetime.now()
    ts_text = now.strftime("%H:%M - %d/%m")

    def measure(text: str, f):
        bbox = draw_b.textbbox((0, 0), text, font=f)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    ts_w, ts_h = measure(ts_text, small_font)
    ts_x = width - ts_w - 8
    ts_y = height - ts_h - 8

    if state == "on":
        # DND/Busy: red background with a white circle and red bar (no-entry symbol)
        draw_r.rectangle((0, 0, width, height), fill=0)

        circle_diameter = int(min(width, height) * 0.4)
        cx = width // 2
        cy = height // 2

        left = cx - circle_diameter // 2
        top = cy - circle_diameter // 2
        right = cx + circle_diameter // 2
        bottom = cy + circle_diameter // 2

        # White circle in the middle
        draw_r.ellipse((left, top, right, bottom), fill=1)

        # Red bar inside circle
        bar_height = max(6, circle_diameter // 8)
        bar_top = cy - bar_height // 2
        bar_bottom = cy + bar_height // 2
        bar_margin = int(circle_diameter * 0.15)
        bar_left = left + bar_margin
        bar_right = right - bar_margin
        draw_r.rectangle((bar_left, bar_top, bar_right, bar_bottom), fill=0)

        # Thin black border for framing
        draw_b.rectangle((3, 3, width - 4, height - 4), outline=0)

        # Timestamp in white on red
        draw_r.text((ts_x, ts_y), ts_text, font=small_font, fill=1)

    else:
        # Free: black background with white FREE text and white timestamp
        draw_b.rectangle((0, 0, width, height), fill=0)

        text = "FREE"
        tw, th = measure(text, font)
        tx = (width - tw) // 2
        ty = (height - th) // 2
        draw_b.text((tx, ty), text, font=font, fill=1)

        draw_b.text((ts_x, ts_y), ts_text, font=small_font, fill=1)

    return black_img, red_img


def display_state(epd, state: str):
    """Update the physical display with the given state."""
    if epd is None:
        # Simulation mode
        black_img, red_img = render_state_image(800, 480, state)
        black_img.save('/tmp/epaper_black.png')
        red_img.save('/tmp/epaper_red.png')
        print(f"Simulation mode: saved images to /tmp/epaper_*.png (state={state})")
        return

    black_img, red_img = render_state_image(epd.width, epd.height, state)
    epd.display(epd.getbuffer(black_img), epd.getbuffer(red_img))


def build_ws_url_from_base(base_url: str) -> str:
    """Convert HTTP base URL to WebSocket URL."""
    p = urlparse(base_url)
    scheme = "wss" if p.scheme == "https" else "ws"
    return f"{scheme}://{p.netloc}/api/websocket"


def fetch_current_state() -> str:
    """Fetch current entity state via REST API."""
    url = HA_BASE_URL.rstrip("/") + f"/api/states/{HA_ENTITY_ID}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json().get("state", "off")


async def ha_dnd_listener(epd, stop_event: asyncio.Event):
    """Connect to Home Assistant WebSocket API and listen for state changes."""
    ws_url = build_ws_url_from_base(HA_BASE_URL)

    # Get initial state via REST API
    try:
        current_state = fetch_current_state()
    except Exception as e:
        print(f"Failed to fetch initial state: {e}")
        current_state = "off"

    print(f"Initial state: {current_state}")
    display_state(epd, current_state)
    last_refresh = time.time()

    while not stop_event.is_set():
        try:
            ssl_ctx = None
            if ws_url.startswith("wss://"):
                ssl_ctx = ssl.create_default_context()

            async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
                # Wait for auth_required message
                msg = await ws.recv()
                print(f"Connected to Home Assistant")

                # Send authentication
                await ws.send(json.dumps({
                    "type": "auth",
                    "access_token": HA_TOKEN
                }))
                auth_result = await ws.recv()
                auth_data = json.loads(auth_result)
                if auth_data.get("type") != "auth_ok":
                    raise Exception(f"Authentication failed: {auth_data}")

                print("Authentication successful")

                # Subscribe to state changes
                await ws.send(json.dumps({
                    "id": 1,
                    "type": "subscribe_events",
                    "event_type": "state_changed"
                }))

                print(f"Listening for changes to {HA_ENTITY_ID}... press Esc to exit")

                async for raw in ws:
                    if stop_event.is_set():
                        break

                    event = json.loads(raw)
                    if event.get("type") != "event":
                        continue

                    e = event.get("event", {})
                    if e.get("event_type") != "state_changed":
                        continue

                    d = e.get("data", {})
                    if d.get("entity_id") != HA_ENTITY_ID:
                        continue

                    new_state = (d.get("new_state") or {}).get("state", "off")

                    if new_state == current_state:
                        continue

                    now = time.time()
                    if now - last_refresh < MIN_REFRESH_SECONDS:
                        print(f"Skipping refresh - too soon (min {MIN_REFRESH_SECONDS}s)")
                        current_state = new_state
                        continue

                    print(f"State changed: {current_state} -> {new_state}")
                    current_state = new_state
                    display_state(epd, current_state)
                    last_refresh = now

        except asyncio.CancelledError:
            break
        except Exception as e:
            if stop_event.is_set():
                break
            print(f"WebSocket error: {e}, reconnecting in 5 seconds...")
            await asyncio.sleep(5)


async def main():
    """Main entry point."""
    ensure_env()
    epd = get_epd()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_stdin():
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            print("Esc pressed. Exiting.")
            stop_event.set()

    try:
        loop.add_reader(sys.stdin, on_stdin)
    except Exception:
        print("stdin reader not supported, use Ctrl+C to exit")

    print("E-Paper DND Display starting...")
    print(f"Home Assistant URL: {HA_BASE_URL}")
    print(f"Entity ID: {HA_ENTITY_ID}")
    print(f"Min refresh interval: {MIN_REFRESH_SECONDS}s")

    task = asyncio.create_task(ha_dnd_listener(epd, stop_event))

    try:
        await stop_event.wait()
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        if epd:
            try:
                epd.sleep()
            except Exception:
                pass


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting.")
