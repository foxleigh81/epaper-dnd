# E-Paper DND Display

A DIY "Do Not Disturb" status display using a Raspberry Pi and Waveshare tri-colour e-Paper display, controlled by Home Assistant.

This is a companion to the following YouTube video: [placeholder]

## What it does

- Displays a red **no-entry symbol** when you're busy (DND on)
- Displays a black **FREE** card when you're available (DND off)
- Shows a **last updated** timestamp so you know it's not frozen
- Updates in real-time when you toggle the status in Home Assistant

## Hardware required

- [Raspberry Pi 3B](https://amzn.to/489N42w) or above (Link is for the 1GB Pi 4) or [Pi Zero 2 W](https://amzn.to/43V22Ix)
- [MicroSD card](https://amzn.to/4pykm2y) (8 GB or larger)
- [Waveshare 7.5 inch tri-colour e-Paper display (B or BC) with HAT](https://amzn.to/4oZyvWx)
- [5V USB power supply](https://amzn.to/4opIun3) (Linked version is for Pi 4 and above)
- Mounting solution (3D printed frame, picture frame, or tape)

## Quick start

### 1. Set up the Raspberry Pi

Flash **Raspberry Pi OS Lite**, enable SSH, and boot. Then:

```bash
sudo apt update && sudo apt upgrade -y
sudo raspi-config  # Enable SPI under Interface Options
sudo reboot
```

### 2. Install the Waveshare driver

```bash
cd /home/pi
git clone https://github.com/waveshare/e-Paper.git
```

Test with:

```bash
cd /home/pi/e-Paper/RaspberryPi_JetsonNano/python/examples
sudo python3 epd_7in5bc_test.py
```

### 3. Install Python dependencies

On **Raspberry Pi OS Bookworm** or newer:

```bash
cd /home/pi
python3 -m venv dnd-venv
source dnd-venv/bin/activate
pip install pillow requests websockets
```

On older versions:

```bash
sudo pip3 install pillow requests websockets
```

### 4. Clone this repository

```bash
cd /home/pi
git clone https://github.com/foxleigh81/epaper-dnd.git
cd epaper-dnd
```

### 5. Set up Home Assistant

Create a Toggle helper:

1. Go to **Settings > Devices & Services > Helpers**
2. Click **+ Create Helper**
3. Select **Toggle**
4. Name it `DND Status`
5. Click **Create**

Create a long-lived access token:

1. Click your username in Home Assistant
2. Scroll to the **Security** section
3. Under **Long-Lived Access Tokens**, click **Create Token**
4. Copy the token (you won't see it again)

### 6. Configure and run

```bash
export HA_BASE_URL="http://YOUR_HA_IP:8123"
export HA_TOKEN="your-long-lived-token"
export HA_ENTITY_ID="input_boolean.dnd_status"
export HA_MIN_REFRESH_SECONDS=10

python3 epaper_dnd.py
```

### 7. Run on boot (optional)

Copy the systemd service file and launcher script:

```bash
chmod +x run_dnd_display.sh
sudo cp dnd-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dnd-display
sudo systemctl start dnd-display
```

Edit `run_dnd_display.sh` with your Home Assistant URL and token first.

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HA_BASE_URL` | Home Assistant URL | `http://localhost:8123` |
| `HA_TOKEN` | Long-lived access token | (required) |
| `HA_ENTITY_ID` | Entity to monitor | `input_boolean.dnd_status` |
| `HA_MIN_REFRESH_SECONDS` | Minimum seconds between refreshes | `10` |

## How it works

1. The script connects to Home Assistant via WebSocket
2. It subscribes to state change events for your toggle entity
3. When the state changes, it redraws the e-Paper display
4. The display shows either FREE or a no-entry symbol with a timestamp

## Troubleshooting

**Display not updating:**
- Check SPI is enabled: `ls /dev/spidev*`
- Ensure the HAT is connected properly (pin 1 to pin 1)
- Run the Waveshare test script first

**Connection errors:**
- Verify your Home Assistant URL is reachable
- Check the long-lived token is valid
- Ensure the entity ID matches your helper

**Python errors on Bookworm:**
- Make sure you're using a virtual environment
- Activate it with `source /home/pi/dnd-venv/bin/activate`

## Licence

MIT
