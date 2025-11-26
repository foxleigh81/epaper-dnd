#!/usr/bin/env python3
"""
E-Paper DND Display

Connects to Home Assistant via WebSocket and displays a DND status
on a Waveshare 7.5 inch tri-colour e-Paper display.

Environment variables:
    HA_BASE_URL: Home Assistant base URL (e.g. http://192.168.1.100:8123)
    HA_TOKEN: Long-lived access token
    HA_ENTITY_ID: Entity ID to monitor (default: input_boolean.dnd_status)
    HA_MIN_REFRESH_SECONDS: Minimum seconds between display refreshes (default: 10)
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

import websockets
from PIL import Image, ImageDraw, ImageFont

# Add Waveshare library path
sys.path.append('/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment
HA_BASE_URL = os.environ.get('HA_BASE_URL', 'http://localhost:8123')
HA_TOKEN = os.environ.get('HA_TOKEN', '')
HA_ENTITY_ID = os.environ.get('HA_ENTITY_ID', 'input_boolean.dnd_status')
MIN_REFRESH_SECONDS = int(os.environ.get('HA_MIN_REFRESH_SECONDS', '10'))

# Display dimensions for 7.5 inch display
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# Track last refresh time
last_refresh_time = 0


def get_epd():
    """Import and return the e-Paper display driver."""
    try:
        from waveshare_epd import epd7in5b_V2
        return epd7in5b_V2.EPD()
    except ImportError:
        logger.warning("Waveshare library not found - running in simulation mode")
        return None


def draw_free_screen(draw_black, draw_red):
    """Draw the FREE status screen."""
    # Black background card effect - draw a rounded rectangle
    margin = 40
    draw_black.rectangle(
        [margin, margin, DISPLAY_WIDTH - margin, DISPLAY_HEIGHT - margin],
        fill=0
    )

    # Draw "FREE" text in white (by not drawing on the black layer inside the rect)
    # We need to draw the text by leaving it empty on black, so invert approach
    # Actually for e-ink: black layer = black pixels, so we draw black rect then
    # need to "cut out" the text. Easier approach: draw text in red layer or
    # use a different method.

    # Let's redraw: white background, black border, black text
    draw_black.rectangle(
        [margin, margin, DISPLAY_WIDTH - margin, DISPLAY_HEIGHT - margin],
        fill=255,
        outline=0,
        width=8
    )

    # Draw FREE text centered
    try:
        font_large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 160)
    except OSError:
        font_large = ImageFont.load_default()

    text = "FREE"
    bbox = draw_black.textbbox((0, 0), text, font=font_large)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (DISPLAY_WIDTH - text_width) // 2
    y = (DISPLAY_HEIGHT - text_height) // 2 - 20

    draw_black.text((x, y), text, font=font_large, fill=0)


def draw_dnd_screen(draw_black, draw_red):
    """Draw the DND (Do Not Disturb) screen with no-entry symbol."""
    center_x = DISPLAY_WIDTH // 2
    center_y = DISPLAY_HEIGHT // 2 - 20
    radius = 180
    bar_height = 60

    # Draw the red circle (outer)
    draw_red.ellipse(
        [center_x - radius, center_y - radius,
         center_x + radius, center_y + radius],
        fill=0,
        outline=0
    )

    # Draw white inner circle (cut out) - on both layers to ensure white
    inner_radius = radius - 35
    draw_red.ellipse(
        [center_x - inner_radius, center_y - inner_radius,
         center_x + inner_radius, center_y + inner_radius],
        fill=255
    )
    draw_black.ellipse(
        [center_x - inner_radius, center_y - inner_radius,
         center_x + inner_radius, center_y + inner_radius],
        fill=255
    )

    # Draw the horizontal red bar
    bar_width = inner_radius * 2 - 20
    draw_red.rectangle(
        [center_x - bar_width // 2, center_y - bar_height // 2,
         center_x + bar_width // 2, center_y + bar_height // 2],
        fill=0
    )


def draw_timestamp(draw_black):
    """Draw a small timestamp in the corner."""
    try:
        font_small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
    except OSError:
        font_small = ImageFont.load_default()

    timestamp = datetime.now().strftime("Updated: %H:%M %d/%m/%Y")
    draw_black.text((10, DISPLAY_HEIGHT - 30), timestamp, font=font_small, fill=0)


def update_display(is_dnd: bool):
    """Update the e-Paper display with current status."""
    global last_refresh_time

    # Rate limiting
    current_time = time.time()
    if current_time - last_refresh_time < MIN_REFRESH_SECONDS:
        logger.info(f"Skipping refresh - too soon (min {MIN_REFRESH_SECONDS}s between refreshes)")
        return

    logger.info(f"Updating display: DND = {is_dnd}")

    # Create images for black and red channels
    # For Waveshare tri-colour: 0 = colour shown, 255 = white
    img_black = Image.new('1', (DISPLAY_WIDTH, DISPLAY_HEIGHT), 255)
    img_red = Image.new('1', (DISPLAY_WIDTH, DISPLAY_HEIGHT), 255)

    draw_black = ImageDraw.Draw(img_black)
    draw_red = ImageDraw.Draw(img_red)

    if is_dnd:
        draw_dnd_screen(draw_black, draw_red)
    else:
        draw_free_screen(draw_black, draw_red)

    draw_timestamp(draw_black)

    # Update physical display
    epd = get_epd()
    if epd:
        try:
            logger.info("Initializing display...")
            epd.init()
            logger.info("Sending image to display...")
            epd.display(epd.getbuffer(img_black), epd.getbuffer(img_red))
            logger.info("Putting display to sleep...")
            epd.sleep()
        except Exception as e:
            logger.error(f"Display error: {e}")
            if epd:
                epd.sleep()
    else:
        # Simulation mode - save images for debugging
        img_black.save('/tmp/epaper_black.png')
        img_red.save('/tmp/epaper_red.png')
        logger.info("Simulation mode: saved images to /tmp/epaper_*.png")

    last_refresh_time = current_time
    logger.info("Display update complete")


async def connect_to_ha():
    """Connect to Home Assistant WebSocket API and listen for state changes."""
    ws_url = HA_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://')
    ws_url = f"{ws_url}/api/websocket"

    logger.info(f"Connecting to {ws_url}")

    message_id = 1

    async with websockets.connect(ws_url) as ws:
        # Wait for auth_required message
        msg = json.loads(await ws.recv())
        logger.info(f"Received: {msg['type']}")

        if msg['type'] != 'auth_required':
            raise Exception(f"Unexpected message: {msg}")

        # Send authentication
        await ws.send(json.dumps({
            'type': 'auth',
            'access_token': HA_TOKEN
        }))

        msg = json.loads(await ws.recv())
        if msg['type'] != 'auth_ok':
            raise Exception(f"Authentication failed: {msg}")

        logger.info("Authentication successful")

        # Get initial state
        await ws.send(json.dumps({
            'id': message_id,
            'type': 'get_states'
        }))
        message_id += 1

        msg = json.loads(await ws.recv())
        if msg['type'] == 'result' and msg['success']:
            for state in msg['result']:
                if state['entity_id'] == HA_ENTITY_ID:
                    is_dnd = state['state'] == 'on'
                    logger.info(f"Initial state: {HA_ENTITY_ID} = {state['state']}")
                    update_display(is_dnd)
                    break

        # Subscribe to state changes
        await ws.send(json.dumps({
            'id': message_id,
            'type': 'subscribe_events',
            'event_type': 'state_changed'
        }))
        message_id += 1

        # Wait for subscription confirmation
        msg = json.loads(await ws.recv())
        logger.info(f"Subscription result: {msg.get('success', False)}")

        # Listen for state changes
        logger.info(f"Listening for changes to {HA_ENTITY_ID}...")

        while True:
            msg = json.loads(await ws.recv())

            if msg['type'] == 'event':
                event_data = msg['event']['data']
                entity_id = event_data.get('entity_id')

                if entity_id == HA_ENTITY_ID:
                    new_state = event_data['new_state']['state']
                    old_state = event_data['old_state']['state'] if event_data.get('old_state') else 'unknown'

                    logger.info(f"State changed: {old_state} -> {new_state}")

                    is_dnd = new_state == 'on'
                    update_display(is_dnd)


async def main():
    """Main entry point with reconnection logic."""
    if not HA_TOKEN:
        logger.error("HA_TOKEN environment variable not set")
        sys.exit(1)

    logger.info("E-Paper DND Display starting...")
    logger.info(f"Home Assistant URL: {HA_BASE_URL}")
    logger.info(f"Entity ID: {HA_ENTITY_ID}")
    logger.info(f"Min refresh interval: {MIN_REFRESH_SECONDS}s")

    while True:
        try:
            await connect_to_ha()
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection closed, reconnecting in 10 seconds...")
        except ConnectionRefusedError:
            logger.warning("Connection refused, retrying in 30 seconds...")
            await asyncio.sleep(20)  # Extra delay for refused connections
        except Exception as e:
            logger.error(f"Error: {e}, reconnecting in 10 seconds...")

        await asyncio.sleep(10)


if __name__ == '__main__':
    asyncio.run(main())
