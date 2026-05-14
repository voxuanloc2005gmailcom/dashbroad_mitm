#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LEO SATELLITE MITM - DASHBOARD SERVER
Real-time visualization với WebSocket + Canvas animation
"""

import json, time, os, sys, math, random, struct, hashlib, threading
from datetime import datetime
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(_script_dir, 'templates'), static_folder=os.path.join(_script_dir, 'static'))
app.config['SECRET_KEY'] = 'starlink-550-mitm-dashboard-2025'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ─────────────────────────────────────────────
# CRYPTO (reused from vm_demo.py)
# ─────────────────────────────────────────────
SHARED_KEY = hashlib.sha256(b"starlink-550-leo-security-key-2025").digest()
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import hmac as hmac_module
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

def encrypt_packet(data: bytes) -> bytes:
    if not HAS_CRYPTO:
        return data
    nonce = os.urandom(12)
    timestamp = struct.pack('!d', time.time())
    seq = struct.pack('!I', random.randint(1, 999999))
    ct = AESGCM(SHARED_KEY).encrypt(nonce, data, None)
    mac = hmac_module.new(SHARED_KEY, nonce + timestamp + seq + ct, hashlib.sha256).digest()
    return nonce + timestamp + seq + ct + mac

def decrypt_packet(data: bytes) -> bytes:
    if not HAS_CRYPTO:
        return data
    nonce = data[:12]
    timestamp = data[12:20]
    seq = data[20:24]
    mac = data[-32:]
    ct = data[24:-32]
    mac_data = nonce + timestamp + seq + ct
    if not hmac_module.compare_digest(mac, hmac_module.new(SHARED_KEY, mac_data, hashlib.sha256).digest()):
        raise ValueError("HMAC failed")
    pkt_time = struct.unpack('!d', timestamp)[0]
    if abs(time.time() - pkt_time) > 30:
        raise ValueError("Timestamp drift")
    return AESGCM(SHARED_KEY).decrypt(nonce, ct, None)


# ─────────────────────────────────────────────
# CONSTELLATION DATA
# ─────────────────────────────────────────────
CONSTELLATION = {
    "name": "Starlink-550",
    "altitude_km": 550,
    "inclination": 53.0,
    "planes": 72,
    "sats_per_plane": 22,
    "total": 1584,
}
GROUND_STATIONS = [
    {"id": 0,  "name": "Tokyo",         "lat": 35.6895,  "lng": 139.6917},
    {"id": 1,  "name": "Delhi",         "lat": 28.6667,  "lng": 77.2167},
    {"id": 2,  "name": "Shanghai",      "lat": 31.2222,  "lng": 121.4581},
    {"id": 3,  "name": "São Paulo",     "lat": -23.5475, "lng": -46.6361},
    {"id": 4,  "name": "Mumbai",        "lat": 19.0740,  "lng": 72.8808},
    {"id": 5,  "name": "New York",      "lat": 40.7170,  "lng": -74.0037},
    {"id": 6,  "name": "Beijing",       "lat": 39.9075,  "lng": 116.3972},
    {"id": 7,  "name": "Osaka",         "lat": 34.6758,  "lng": 135.5538},
    {"id": 8,  "name": "Cairo",         "lat": 30.0392,  "lng": 31.2394},
    {"id": 9,  "name": "Mexico City",   "lat": 19.4273,  "lng": -99.1419},
    {"id": 10, "name": "Seoul",         "lat": 37.5683,  "lng": 126.9778},
    {"id": 11, "name": "Ho Chi Minh",   "lat": 10.7500,  "lng": 106.6667},
    {"id": 12, "name": "Moscow",        "lat": 55.7550,  "lng": 37.6218},
    {"id": 13, "name": "Paris",         "lat": 48.8534,  "lng": 2.3488},
    {"id": 14, "name": "London",        "lat": 51.5085,  "lng": -0.1257},
    {"id": 15, "name": "Bangkok",       "lat": 13.7220,  "lng": 100.5252},
    {"id": 16, "name": "Singapore",     "lat": 1.2897,   "lng": 103.8501},
    {"id": 17, "name": "Sydney",        "lat": -33.8679, "lng": 151.2073},
    {"id": 18, "name": "Istanbul",      "lat": 41.0138,  "lng": 28.9497},
    {"id": 19, "name": "Los Angeles",   "lat": 34.0317,  "lng": -118.2417},
]

def generate_telemetry(sat_id=0):
    plane = sat_id // 22
    sat_in_plane = sat_id % 22
    raan = plane * (360 / 72)
    mean_anomaly = sat_in_plane * (360 / 22) + (time.time() % 5757) * (360 / 5757)
    lat = 53.0 * math.sin(math.radians(mean_anomaly % 360))
    lng = raan + mean_anomaly * math.cos(math.radians(53.0))
    lng = ((lng + 180) % 360) - 180
    return {
        "satellite_id": f"SAT-{plane:02d}-{sat_in_plane:02d}",
        "constellation": "Starlink-550",
        "altitude_km": round(550 + random.uniform(-2, 2), 1),
        "latitude": round(lat, 4),
        "longitude": round(lng, 4),
        "velocity_km_s": round(7.59 + random.uniform(-0.01, 0.01), 4),
        "battery_pct": round(random.uniform(78, 98), 1),
        "solar_panel_w": round(random.uniform(2800, 3200), 0),
        "temperature_c": round(random.uniform(-15, 45), 1),
        "uptime_hours": round(random.uniform(100, 8760), 1),
        "isl_links_active": random.randint(2, 4),
        "ground_stations_visible": random.randint(1, 5),
    }


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
class SessionState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.scenario = None
        self.security = False
        self.attacker_mode = "SNIFF"
        self.command_idx = 0
        self.packets_sent = 0
        self.packets_intercepted = 0
        self.packets_modified = 0
        self.packets_blocked = 0
        self.replay_buffer = []
        self.events = []
        self.sat_telemetry = None
        self.active_sat_id = random.randint(0, 1583)
        self.start_time = None
        self.attack_summary = {}

    def add_event(self, level, source, message):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        event = {"time": ts, "level": level, "source": source, "message": message}
        self.events.append(event)
        if len(self.events) > 200:
            self.events = self.events[-200:]
        socketio.emit('event', event, namespace='/')
        return event

state = SessionState()

COMMANDS = [
    {"command": "PING"},
    {"command": "GET_TELEMETRY"},
    {"command": "ATTITUDE_ADJUST", "params": {"yaw": 2.5, "pitch": 0.3}},
    {"command": "ORBITAL_MANEUVER", "params": {"delta_v": 0.02, "duration": 30}},
    {"command": "GET_TELEMETRY"},
    {"command": "FIRMWARE_UPDATE", "params": {"url": "official.starlink.com/v4.2.3"}},
]


# ─────────────────────────────────────────────
# SIMULATION ENGINE
# ─────────────────────────────────────────────
def telemetry_loop():
    """Broadcast continuous telemetry every 2 seconds."""
    while True:
        time.sleep(2)
        if state.active and state.sat_telemetry:
            socketio.emit('telemetry_update', state.sat_telemetry, namespace='/')

def run_scenario_thread():
    """Chạy kịch bản demo trong background thread"""
    global state
    time.sleep(1)

    # 1. START PHASE
    state.add_event("info", "SYSTEM", f"🚀 Starting scenario: {state.scenario}")
    state.add_event("info", "SYSTEM", f"🔒 Security: {'ENABLED (AES-256-GCM + HMAC-SHA256)' if state.security else 'DISABLED (PLAINTEXT)'}")
    state.add_event("info", "SYSTEM", f"⚠️  Attacker mode: {state.attacker_mode}")
    time.sleep(1.5)

    # 2. SATELLITE BOOT
    state.sat_telemetry = generate_telemetry(state.active_sat_id)
    state.add_event("success", "SAT", f"🛰️  Satellite {state.sat_telemetry['satellite_id']} ONLINE")
    state.add_event("info", "SAT", f"   Position: {state.sat_telemetry['latitude']:.2f}°, {state.sat_telemetry['longitude']:.2f}° | Alt: {state.sat_telemetry['altitude_km']:.1f} km")
    state.add_event("info", "SAT", f"   Battery: {state.sat_telemetry['battery_pct']}% | Temp: {state.sat_telemetry['temperature_c']}°C | Velocity: {state.sat_telemetry['velocity_km_s']} km/s")
    time.sleep(1)

    # 3. ATTACKER CONNECT
    state.add_event("warning", "ATK", f"⚠️  MITM Proxy ACTIVE on attacker node")
    state.add_event("info", "ATK", f"   Mode: {state.attacker_mode}")
    state.add_event("info", "ATK", f"   Target: {state.sat_telemetry['satellite_id']}")
    time.sleep(1)

    # 4. SEND COMMANDS
    for i, cmd in enumerate(COMMANDS):
        state.command_idx = i
        state.packets_sent += 1

        # Emit progress
        socketio.emit('progress_update', {
            "command_idx": state.command_idx,
            "total": len(COMMANDS),
        }, namespace='/')

        if state.security:
            enc_cmd = encrypt_packet(json.dumps(cmd).encode('utf-8'))
            state.add_event("info", "GS", f"📡 Sending ENCRYPTED: {cmd['command']}")
            state.add_event("info", "GS", f"   🔒 Ciphertext: {enc_cmd[:16].hex()}... ({len(enc_cmd)} bytes)")

            # Attacker sees encrypted
            state.add_event("warning", "ATK", f"⚠️  ENCRYPTED PACKET DETECTED")
            state.add_event("warning", "ATK", f"   Cannot decode — AES-256-GCM active")
            state.packets_blocked += 1
            socketio.emit('attack_phase', {"type": "BLOCKED"}, namespace='/')

            # Satellite decrypts
            time.sleep(0.5)
            state.add_event("success", "SAT", f"🔓 Decrypted & verified: {cmd['command']}")

            if cmd['command'] == 'GET_TELEMETRY':
                state.sat_telemetry = generate_telemetry(state.active_sat_id)
                state.add_event("success", "SAT", f"📊 Telemetry: {json.dumps(state.sat_telemetry)}")
            elif cmd['command'] == 'ATTITUDE_ADJUST':
                state.add_event("success", "SAT", f"🔧 Attitude adjusted: yaw=2.5°, pitch=0.3°")
            elif cmd['command'] == 'ORBITAL_MANEUVER':
                state.add_event("success", "SAT", f"🚀 Orbital maneuver: Δv=0.02 m/s, 30s")
            elif cmd['command'] == 'FIRMWARE_UPDATE':
                state.add_event("success", "SAT", f"📦 Firmware: official.starlink.com/v4.2.3")

            state.add_event("success", "GS", f"   ✅ Response OK")

        else:
            # PLAINTEXT
            state.add_event("info", "GS", f"📡 Sending: {cmd['command']}")
            if 'params' in cmd:
                for k, v in cmd['params'].items():
                    state.add_event("info", "GS", f"   {k}: {v}")

            state.packets_intercepted += 1

            if state.attacker_mode == 'SNIFF':
                state.add_event("danger", "ATK", f"👁️  INTERCEPTED: {cmd['command']}")
                socketio.emit('attack_phase', {"type": "SNIFF"}, namespace='/')
                if 'params' in cmd:
                    for k, v in cmd['params'].items():
                        state.add_event("danger", "ATK", f"   Leaked: {k}={v}")
                state.add_event("info", "ATK", f"   → Forwarding to satellite...")

            elif state.attacker_mode == 'MODIFY':
                state.add_event("danger", "ATK", f"🔧 INTERCEPTED: {cmd['command']}")
                if 'params' in cmd:
                    for k, v in cmd['params'].items():
                        state.add_event("danger", "ATK", f"   Original: {k}={v}")

                # Modify
                if cmd['command'] == 'ATTITUDE_ADJUST':
                    cmd['params'] = {"yaw": 45.0, "pitch": 30.0}
                    state.add_event("danger", "ATK", f"🔧 MODIFIED → yaw=45.0°, pitch=30.0° ⚠️ DANGEROUS!")
                    state.packets_modified += 1
                    socketio.emit('attack_phase', {"type": "MODIFY"}, namespace='/')
                elif cmd['command'] == 'ORBITAL_MANEUVER':
                    cmd['params'] = {"delta_v": 5.0, "duration": 300}
                    state.add_event("danger", "ATK", f"🔧 MODIFIED → Δv=5.0 m/s (250× amplified!) ⚠️ CRITICAL!")
                    state.packets_modified += 1
                elif cmd['command'] == 'FIRMWARE_UPDATE':
                    cmd['params'] = {"url": "evil-server.attacker.com/backdoor.bin"}
                    state.add_event("danger", "ATK", f"🔧 MODIFIED → url=evil-server.attacker.com/backdoor.bin ⚠️ BACKDOOR!")
                    state.packets_modified += 1
                else:
                    state.add_event("info", "ATK", f"   → Forwarding (no modification)")

            elif state.attacker_mode == 'REPLAY':
                state.add_event("warning", "ATK", f"💾 SAVED: {cmd['command']} (buffer: {len(state.replay_buffer)+1})")
                state.replay_buffer.append(cmd.copy())
                socketio.emit('attack_phase', {"type": "REPLAY"}, namespace='/')
                state.add_event("info", "ATK", f"   → Forwarding to satellite...")

            time.sleep(0.8)

            # Satellite response
            if cmd['command'] == 'GET_TELEMETRY':
                state.sat_telemetry = generate_telemetry(state.active_sat_id)
                state.add_event("info", "SAT", f"📊 Telemetry: lat={state.sat_telemetry['latitude']:.2f}° alt={state.sat_telemetry['altitude_km']:.1f}km bat={state.sat_telemetry['battery_pct']}%")
            elif cmd['command'] == 'ATTITUDE_ADJUST':
                state.add_event("success", "SAT", f"🔧 Attitude adjusted → yaw={cmd['params']['yaw']}°")
            elif cmd['command'] == 'ORBITAL_MANEUVER':
                state.add_event("warning", "SAT", f"🚀 ORBITAL MANEUVER EXECUTED: Δv={cmd['params']['delta_v']} m/s")
                state.add_event("danger", "SAT", f"⚠️  ABNORMAL DELTA-V DETECTED!")
            elif cmd['command'] == 'FIRMWARE_UPDATE':
                state.add_event("danger", "SAT", f"📦 FIRMWARE DOWNLOAD FROM: {cmd['params']['url']}")
                state.add_event("danger", "SAT", f"⚠️  UNKNOWN SOURCE — SECURITY BREACH!")
            else:
                state.add_event("success", "SAT", f"✅ {cmd['command']} → OK")

            state.add_event("info", "GS", f"   ← Response received")

        time.sleep(1.2)

    # 5. REPLAY ATTACK
    if state.attacker_mode == 'REPLAY' and state.replay_buffer and not state.security:
        time.sleep(1)
        state.add_event("danger", "ATK", f"⚡ REPLAY ATTACK LAUNCHED ({len(state.replay_buffer)} commands)")
        socketio.emit('attack_phase', {"type": "REPLAY"}, namespace='/')
        for rpkt in state.replay_buffer:
            state.add_event("danger", "ATK", f"   🔄 Replaying: {rpkt['command']}")
            time.sleep(0.5)
        state.add_event("danger", "ATK", f"⚡ REPLAY COMPLETE — {len(state.replay_buffer)} commands executed!")

    # 6. SUMMARY
    time.sleep(1)
    state.active = False

    summary = {
        "scenario": state.scenario,
        "security": "ENABLED" if state.security else "DISABLED",
        "attacker_mode": state.attacker_mode,
        "packets_sent": state.packets_sent,
        "packets_intercepted": state.packets_intercepted,
        "packets_modified": state.packets_modified,
        "packets_blocked": state.packets_blocked,
        "replay_count": len(state.replay_buffer),
    }
    state.attack_summary = summary

    state.add_event("success", "SYSTEM", f"📋 SCENARIO COMPLETE")
    state.add_event("info", "SYSTEM", f"   Sent: {summary['packets_sent']} | Intercepted: {summary['packets_intercepted']} | Modified: {summary['packets_modified']} | Blocked: {summary['packets_blocked']}")

    if state.security:
        state.add_event("success", "SYSTEM", "🛡️  SECURITY EFFECTIVE — All attacks BLOCKED by AES-256-GCM encryption")
    else:
        if summary['packets_modified'] > 0:
            state.add_event("danger", "SYSTEM", f"🚨 CRITICAL — {summary['packets_modified']} commands were MODIFIED by attacker!")
        if summary['packets_intercepted'] > 0:
            state.add_event("warning", "SYSTEM", f"⚠️  {summary['packets_intercepted']} commands were INTERCEPTED (plaintext)")

    socketio.emit('scenario_complete', summary, namespace='/')


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/static/<path:fn>')
def static_files(fn):
    return send_from_directory('static', fn)


# ─────────────────────────────────────────────
# WEBSOCKET HANDLERS
# ─────────────────────────────────────────────
@socketio.on('connect')
def on_connect():
    emit('connected', {"status": "ok", "time": datetime.now().isoformat()})

@socketio.on('start_scenario')
def on_start_scenario(data):
    global state
    state.reset()
    state.scenario = data.get('scenario', 'SNIFF')
    state.security = data.get('security', False)
    state.attacker_mode = data.get('attacker_mode', 'SNIFF')

    emit('scenario_started', {
        "scenario": state.scenario,
        "security": state.security,
        "attacker_mode": state.attacker_mode
    })

    thread = threading.Thread(target=run_scenario_thread, daemon=True)
    thread.start()

@socketio.on('get_state')
def on_get_state():
    emit('state_update', {
        "active": state.active,
        "scenario": state.scenario,
        "security": state.security,
        "attacker_mode": state.attacker_mode,
        "packets_sent": state.packets_sent,
        "packets_intercepted": state.packets_intercepted,
        "packets_modified": state.packets_modified,
        "packets_blocked": state.packets_blocked,
        "command_idx": state.command_idx,
        "sat_telemetry": state.sat_telemetry,
        "events": state.events[-50:],
        "summary": state.attack_summary,
    })

@socketio.on('stop_scenario')
def on_stop_scenario():
    global state
    state.reset()
    emit('scenario_stopped', {"status": "stopped"})


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == '__main__':
    print('LEO SATELLITE MITM - DASHBOARD SERVER')
    print('Starlink-550 Security Lab')
    print('Running on http://localhost:5000')

    # Start continuous telemetry broadcast
    t_telem = threading.Thread(target=telemetry_loop, daemon=True)
    t_telem.start()

    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)