import json
import os
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium
import boto3
from dotenv import load_dotenv
from celonis_client import celonis_load_locations

load_dotenv()

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pilot Flying J",
    page_icon="⛽",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Phone-like styling ────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Roboto Flex — matches real Pilot website */
  @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&display=swap');

  *, *::before, *::after {
    font-family: 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif;
    box-sizing: border-box;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Page: dark background around phone ── */
  .stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"],
  [data-testid="stAppViewBlockContainer"], body {
    background: #111827 !important;
  }
  [data-testid="stMain"], [data-testid="stMainScrollable"],
  section.main, [data-testid="stMainArea"] {
    background: transparent !important;
  }

  /* ── Phone shell ── */
  [data-testid="stMainBlockContainer"],
  [data-testid="block-container"],
  .main .block-container,
  div.block-container {
    max-width: 393px !important;
    width: 393px !important;
    min-width: 393px !important;
    background: #f2f2f7 !important;
    border-radius: 50px !important;
    padding: 56px 0 0 0 !important;
    margin: 20px auto !important;
    box-shadow:
      0 0 0 10px #1c1c1e,
      0 0 0 12px #3a3a3c,
      0 0 0 13px #1c1c1e,
      0 30px 80px rgba(0,0,0,0.7) !important;
    min-height: 852px !important;
    position: relative !important;
    overflow: hidden !important;
  }

  /* Scrollable content area — fill phone interior */
  [data-testid="stVerticalBlock"] {
    padding: 0 16px !important;
  }

  /* Dynamic island (modern iPhone notch) */
  [data-testid="stMainBlockContainer"]::before,
  div.block-container::before {
    content: "";
    position: absolute;
    top: 12px; left: 50%;
    transform: translateX(-50%);
    width: 120px; height: 34px;
    background: #1c1c1e;
    border-radius: 20px;
    z-index: 1000;
  }

  /* Status bar (9:41 time) */
  [data-testid="stMainBlockContainer"]::after,
  div.block-container::after {
    content: "9:41";
    position: absolute;
    top: 16px; left: 36px;
    font-size: 0.8rem; font-weight: 700;
    color: #1c1c1e; z-index: 1001;
    letter-spacing: -0.02em;
  }

  /* ── Hide all Streamlit chrome ── */
  #MainMenu, footer, header,
  [data-testid="stDecoration"],
  [data-testid="stToolbar"],
  [data-testid="stStatusWidget"],
  [data-testid="manage-app-button"],
  [data-testid="collapsedControl"],
  .stDeployButton,
  section[data-testid="stSidebar"],
  [data-testid="stBottom"] { display: none !important; }

  /* ── Pilot mobile header bar ── */
  .pfj-header {
    background: #fff;
    padding: 12px 16px 12px;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #e5e5ea;
    margin: 0 -16px 0;
    position: sticky; top: 0; z-index: 100;
  }
  .pfj-header-logo {
    background: #DC1730; color: #fff;
    font-size: 0.95rem; font-weight: 900;
    padding: 4px 10px; border-radius: 4px;
    letter-spacing: -0.02em; text-transform: lowercase;
    font-style: italic;
  }
  .pfj-header-icon { font-size: 1.2rem; color: #1c1c1e; cursor: pointer; }
  .pfj-header-greeting {
    font-size: 0.72rem; font-weight: 600; color: #636366;
    text-align: center; flex: 1; margin: 0 8px;
  }

  /* ── Hero card (matches site's dark hero) ── */
  .pfj-hero {
    background: #1c1c1e;
    border-radius: 16px;
    padding: 20px 18px;
    margin: 12px 0 8px;
    color: #fff;
    position: relative;
    overflow: hidden;
  }
  .pfj-hero::after {
    content: "";
    position: absolute;
    right: -20px; bottom: -20px;
    width: 100px; height: 100px;
    background: rgba(220,23,48,0.15);
    border-radius: 50%;
  }
  .pfj-eyebrow {
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.1em; color: #DC1730; margin-bottom: 6px;
    display: flex; align-items: center; gap: 4px;
  }
  .pfj-hero h2 {
    font-size: 1.35rem; font-weight: 900; line-height: 1.15;
    margin: 0 0 14px; color: #fff; letter-spacing: -0.02em;
  }
  .pfj-btn-primary {
    display: inline-flex; align-items: center; gap: 6px;
    background: #DC1730; color: #fff; border: none;
    border-radius: 24px; padding: 10px 18px;
    font-size: 0.82rem; font-weight: 700; cursor: pointer;
    text-decoration: none; letter-spacing: 0.01em;
  }
  .pfj-btn-primary-outline {
    display: inline-flex; align-items: center; gap: 6px;
    background: transparent; color: #fff;
    border: 1.5px solid rgba(255,255,255,0.4);
    border-radius: 24px; padding: 9px 18px;
    font-size: 0.82rem; font-weight: 700; cursor: pointer;
    text-decoration: none; letter-spacing: 0.01em;
  }

  /* ── Fuel banner (loyalty points) ── */
  .pfj-fuel-banner {
    background: #DC1730;
    border-radius: 14px;
    padding: 14px 16px;
    display: flex; align-items: center; gap: 12px;
    margin: 8px 0;
    color: #fff;
  }
  .pfj-fuel-banner-icon { font-size: 1.8rem; line-height: 1; }
  .pfj-fuel-banner-text h4 {
    font-size: 0.82rem; font-weight: 800; margin: 0 0 2px; color: #fff;
  }
  .pfj-fuel-banner-text p {
    font-size: 0.68rem; opacity: 0.88; margin: 0; color: #fff;
  }
  .pfj-fuel-banner-arrow {
    margin-left: auto; font-size: 1rem; opacity: 0.7;
  }

  /* ── Quick links (matches site nav row) ── */
  .pfj-quicklinks {
    background: #fff;
    border-radius: 14px;
    margin: 8px 0;
    overflow: hidden;
  }
  .pfj-quicklink-item {
    display: flex; align-items: center;
    padding: 14px 16px;
    border-bottom: 1px solid #e5e5ea;
    text-decoration: none; cursor: pointer;
  }
  .pfj-quicklink-item:last-child { border-bottom: none; }
  .pfj-quicklink-icon {
    width: 36px; height: 36px; background: #fff0f1;
    border-radius: 10px; display: flex; align-items: center;
    justify-content: center; font-size: 1rem; flex-shrink: 0;
    margin-right: 12px;
  }
  .pfj-quicklink-label {
    font-size: 0.85rem; font-weight: 600; color: #1c1c1e; flex: 1;
  }
  .pfj-quicklink-arrow {
    color: #DC1730; font-size: 1rem; font-weight: 700;
  }

  /* ── Offer cards ── */
  .pfj-section-title {
    font-size: 1.05rem; font-weight: 800; color: #1c1c1e;
    margin: 16px 0 8px; letter-spacing: -0.02em;
  }
  .pfj-offer-card {
    background: #fff; border-radius: 14px;
    overflow: hidden; margin-bottom: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .pfj-offer-card-body { padding: 14px 16px 16px; }
  .pfj-offer-title {
    font-size: 0.95rem; font-weight: 800; color: #1c1c1e;
    margin: 6px 0 4px; letter-spacing: -0.01em;
  }
  .pfj-offer-desc { font-size: 0.75rem; color: #636366; margin: 0 0 10px; line-height: 1.4; }
  .pfj-offer-img {
    width: 100%; height: 110px; background: linear-gradient(135deg, #1c1c1e, #3a3a3c);
    display: flex; align-items: center; justify-content: center;
    font-size: 2.5rem;
  }
  .pfj-link-btn {
    display: inline-flex; align-items: center; gap: 4px;
    color: #DC1730; font-size: 0.78rem; font-weight: 700;
    text-decoration: none; cursor: pointer;
  }

  /* ── Find/map screen ── */
  .pfj-screen-header {
    background: #fff;
    padding: 14px 16px 10px;
    margin: 0 -16px 12px;
    border-bottom: 1px solid #e5e5ea;
    display: flex; align-items: center; gap: 10px;
  }
  .pfj-screen-title {
    font-size: 1rem; font-weight: 800; color: #1c1c1e; letter-spacing: -0.02em;
  }
  .filter-row { display: flex; gap: 6px; align-items: center; padding: 0 0 10px; flex-wrap: wrap; }
  .filter-pill {
    background: #1c1c1e; color: #fff; border-radius: 20px;
    padding: 6px 14px; font-size: 0.68rem; font-weight: 600;
  }
  .filter-pill-outline {
    background: #fff; color: #1c1c1e;
    border: 1.5px solid #d1d1d6; border-radius: 20px;
    padding: 6px 14px; font-size: 0.68rem; font-weight: 600;
  }

  /* ── RoadIQ pick card ── */
  .roadiq-pick {
    background: #fff; border: none;
    border-left: 4px solid #DC1730;
    border-radius: 12px; padding: 14px 16px; margin: 8px 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  .pick-tag {
    font-size: 0.58rem; font-weight: 800; color: #DC1730;
    text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 4px;
  }
  .pick-name { font-size: 1rem; font-weight: 800; color: #1c1c1e; margin-bottom: 2px; }
  .pick-city { font-size: 0.72rem; color: #636366; margin-bottom: 8px; }
  .pick-stats { display: flex; flex-wrap: wrap; gap: 5px; }
  .stat-pill {
    background: #f2f2f7; border-radius: 20px;
    padding: 4px 10px; font-size: 0.65rem; font-weight: 600; color: #1c1c1e;
  }
  .stat-pill-good {
    background: #d1fae5; color: #065f46;
    border-radius: 20px; padding: 4px 10px; font-size: 0.65rem; font-weight: 600;
  }

  /* ── AI response card ── */
  .ai-response {
    background: #fff; border-radius: 12px;
    padding: 14px 16px; margin: 8px 0;
    font-size: 0.8rem; line-height: 1.65; color: #1c1c1e;
    white-space: pre-wrap; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .ai-label {
    font-size: 0.6rem; font-weight: 800; color: #DC1730;
    text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;
  }

  /* ── RoadIQ screen header ── */
  .roadiq-header {
    background: #1c1c1e; padding: 12px 16px;
    display: flex; align-items: center; gap: 8px;
    border-radius: 12px; margin-bottom: 8px;
  }
  .roadiq-logo-sm {
    background: #DC1730; color: #fff; font-weight: 900;
    font-size: 0.75rem; padding: 3px 8px; border-radius: 4px;
    font-style: italic;
  }
  .roadiq-header-text { font-size: 0.85rem; font-weight: 700; color: #fff; }

  /* ── Bottom tab bar — sticky inside phone shell ── */
  #roadiq-tab-nav {
    position: sticky;
    bottom: 0;
    width: calc(100% + 32px);  /* cancel the 16px side padding */
    margin: 0 -16px;
    background: rgba(249,249,249,0.94);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-top: 0.5px solid rgba(0,0,0,0.12);
    display: flex; align-items: stretch;
    padding: 10px 6px 26px;  /* 26px = iOS home indicator room */
    z-index: 9999;
    border-radius: 0 0 48px 48px;
  }
  #roadiq-tab-nav a {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; gap: 2px; text-decoration: none; padding: 4px 0;
    border-radius: 10px; transition: background 0.15s;
  }
  #roadiq-tab-nav a.active { background: rgba(220,23,48,0.08); }
  #roadiq-tab-nav .nav-label {
    font-size: 0.58rem; font-weight: 600; color: #8e8e93; letter-spacing: 0.01em;
  }
  #roadiq-tab-nav a.active .nav-label { color: #DC1730; font-weight: 700; }
  #roadiq-tab-nav a:not(.active) .nav-icon-wrap { opacity: 0.45; }
  .nav-icon-wrap {
    width: 44px; height: 28px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 14px; font-size: 1.2rem; line-height: 1;
    transition: background 0.15s;
  }
  .active-pill {
    background: #DC1730;
    font-size: 1.1rem;
  }

  /* ── Streamlit buttons (primary actions) ── */
  div[data-testid="stButton"] > button {
    background-color: #DC1730 !important;
    color: #fff !important; border: none !important;
    border-radius: 24px !important; font-weight: 700 !important;
    font-size: 0.85rem !important; padding: 12px 20px !important;
    width: 100% !important; box-shadow: none !important;
    letter-spacing: 0.01em !important;
  }
  div[data-testid="stButton"] > button:hover { background-color: #b8121f !important; }

  /* ── Text inputs ── */
  div[data-testid="stTextInput"] input {
    background: #fff !important; color: #1c1c1e !important;
    border: 1.5px solid #d1d1d6 !important; border-radius: 12px !important;
    font-size: 0.85rem !important; padding: 11px 14px !important;
  }
  div[data-testid="stTextInput"] input:focus {
    border-color: #DC1730 !important;
    box-shadow: 0 0 0 3px rgba(220,23,48,0.1) !important;
    background: #fff !important;
  }
  div[data-testid="stTextInput"] label {
    font-size: 0.72rem !important; font-weight: 600 !important; color: #636366 !important;
  }

  div[data-testid="stAlert"] { font-size: 0.78rem !important; border-radius: 12px !important; }
  div[data-testid="stSpinner"] p { font-size: 0.78rem !important; }
</style>
""", unsafe_allow_html=True)

# ── data ──────────────────────────────────────────────────────────────────────
from data_layer import get_drivers, get_locations

@st.cache_data
def load_prompt(name):
    base = os.path.dirname(__file__)
    with open(os.path.join(base, "prompts", name)) as f:
        return f.read()

drivers = get_drivers()
locations = get_locations()

# ── Amazon Bedrock ────────────────────────────────────────────────────────────
@st.cache_resource
def get_bedrock_client():
    import botocore.config
    # Corporate SSL inspection workaround
    os.environ.setdefault("PYTHONHTTPSVERIFY", "0")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        verify=False,
    )

def ask_ai(prompt_text, max_tokens=400):
    try:
        client = get_bedrock_client()
        model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt_text}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.7},
        )
        return response["output"]["message"]["content"][0]["text"]
    except Exception as e:
        return f"AI unavailable: {e}"

# ── helpers ───────────────────────────────────────────────────────────────────
DEMO_DRIVER = next(d for d in drivers if d["id"] == 7)

def get_location(driver):
    for loc in locations.values():
        if loc["name"] == driver["recommended_stop"]:
            return loc
    return None

def stops_summary():
    return "\n".join([
        f"- {l['name']} ({l['city']}): parking {l['parking_forecast_pct']}% "
        f"available, shower {l['shower_wait_min']} min wait, {l['food_available']}"
        for l in locations.values()
    ])

CITY_COORDS = {
    "Nashville, TN": (36.1627, -86.7816),
    "Atlanta, GA": (33.7490, -84.3880),
    "Knoxville, TN": (35.9606, -83.9207),
    "Columbus, OH": (39.9612, -82.9988),
    "Dayton, OH": (39.7589, -84.1916),
    "Gaffney, SC": (35.0718, -81.6496),
    "Memphis, TN": (35.1495, -90.0490),
    "Charlotte, NC": (35.2271, -80.8431),
    "Louisville, KY": (38.2527, -85.7585),
    "Detroit, MI": (42.3314, -83.0458),
    "Indianapolis, IN": (39.7684, -86.1581),
    "Cincinnati, OH": (39.1031, -84.5120),
    "Birmingham, AL": (33.5207, -86.8025),
    "Tampa, FL": (27.9506, -82.4572),
    "Arlington, TX": (32.7357, -97.1081),
}

def get_osrm_route(start_coords, end_coords):
    """Get route geometry from OSRM."""
    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
        f"?overview=full&geometries=geojson"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("routes"):
            coords = data["routes"][0]["geometry"]["coordinates"]
            return [(c[1], c[0]) for c in coords]
    except Exception:
        pass
    return None


def get_celonis_stops(from_coords, to_coords):
    """Get Pilot stops from Celonis (already-mapped keys), fallback to None."""
    return celonis_load_locations([from_coords, to_coords])


# ── Session state ─────────────────────────────────────────────────────────────
if "screen" not in st.session_state:
    st.session_state.screen = "home"
if "journey_plan" not in st.session_state:
    st.session_state.journey_plan = None
if "route_from" not in st.session_state:
    st.session_state.route_from = ""
if "route_to" not in st.session_state:
    st.session_state.route_to = ""
if "route_calculated" not in st.session_state:
    st.session_state.route_calculated = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

def switch_screen(name):
    st.session_state.screen = name


def render_tab_nav():
    """Sticky bottom tab bar — rendered inside phone shell."""
    current = st.session_state.screen
    tabs = [
        ("🏠", "Home",    "home"),
        ("📍", "Find",    "find"),
        ("⚡", "RoadIQ",  "roadiq"),
        ("💬", "Chat",    "chat"),
    ]
    items = ""
    for icon, label, key in tabs:
        active = "active" if current == key else ""
        # Active tab gets a red pill background on the icon (matches real app)
        icon_wrap = (
            f'<span class="nav-icon-wrap active-pill">{icon}</span>'
            if current == key else
            f'<span class="nav-icon-wrap">{icon}</span>'
        )
        items += (
            f'<a class="{active}" href="?nav={key}" target="_self">'
            f'{icon_wrap}'
            f'<span class="nav-label">{label}</span></a>'
        )
    st.markdown(
        f'<div id="roadiq-tab-nav">{items}</div>',
        unsafe_allow_html=True,
    )
    # Handle nav clicks via query params
    params = st.query_params
    if "nav" in params and params["nav"] != current:
        st.session_state.screen = params["nav"]
        st.query_params.clear()
        st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# SCREENS
# ═══════════════════════════════════════════════════════════════════════════════

def render_home():
    d = DEMO_DRIVER
    name = d["name"].split()[0]
    fuel_pct = min(int(d["fuel_remaining_miles"] / 6), 100)
    fuel_color = "#DC1730" if fuel_pct < 25 else "#ff9500" if fuel_pct < 50 else "#30d158"

    st.markdown(f"""
    <!-- Header -->
    <div class="pfj-header">
      <span class="pfj-header-icon">☰</span>
      <div style="display:flex;flex-direction:column;align-items:center;flex:1">
        <span class="pfj-header-logo">pilot</span>
        <span style="font-size:0.62rem;color:#636366;font-weight:600;margin-top:2px">Hey, {name} 👋</span>
      </div>
      <span class="pfj-header-icon">👤</span>
    </div>

    <!-- RoadIQ proactive alert -->
    <div style="background:linear-gradient(135deg,#DC1730,#8b0010);border-radius:14px;padding:14px 16px;margin:10px 0 8px;color:#fff">
      <div class="pfj-eyebrow" style="color:rgba(255,255,255,0.7)">⚡ ROADIQ ALERT</div>
      <div style="font-size:0.92rem;font-weight:800;margin:4px 0 6px;letter-spacing:-0.01em">Fuel stop needed in ~95 miles</div>
      <div style="font-size:0.72rem;opacity:0.85;margin-bottom:10px">Based on your route to {d['destination']} — Pilot Knoxville #198 recommended</div>
      <div style="display:flex;gap:8px">
        <span style="background:rgba(255,255,255,0.2);border-radius:20px;padding:5px 12px;font-size:0.7rem;font-weight:700">🅿️ 78% parking</span>
        <span style="background:rgba(255,255,255,0.2);border-radius:20px;padding:5px 12px;font-size:0.7rem;font-weight:700">⛽ Best price</span>
        <span style="background:rgba(255,255,255,0.2);border-radius:20px;padding:5px 12px;font-size:0.7rem;font-weight:700">🏆 {d['loyalty_tier']}</span>
      </div>
    </div>

    <!-- Fuel level bar -->
    <div style="background:#fff;border-radius:12px;padding:12px 14px;margin:8px 0">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="font-size:0.72rem;font-weight:700;color:#636366">FUEL LEVEL</span>
        <span style="font-size:0.72rem;font-weight:700;color:{fuel_color}">{d['fuel_remaining_miles']} mi remaining</span>
      </div>
      <div style="background:#e5e5ea;border-radius:6px;height:8px">
        <div style="background:{fuel_color};width:{fuel_pct}%;height:100%;border-radius:6px;transition:width 0.3s"></div>
      </div>
      <div style="margin-top:6px;font-size:0.7rem;color:#636366">
        📍 {d['current_location']} &nbsp;→&nbsp; 🏁 {d['destination']}
      </div>
    </div>

    <!-- Quick links (matches real site) -->
    <div class="pfj-quicklinks">
      <div class="pfj-quicklink-item">
        <div class="pfj-quicklink-icon">📍</div>
        <span class="pfj-quicklink-label">Find a Location</span>
        <span class="pfj-quicklink-arrow">↗</span>
      </div>
      <div class="pfj-quicklink-item">
        <div class="pfj-quicklink-icon">⛽</div>
        <span class="pfj-quicklink-label">Apply for Fuel Savings</span>
        <span class="pfj-quicklink-arrow">↗</span>
      </div>
      <div class="pfj-quicklink-item">
        <div class="pfj-quicklink-icon">🍕</div>
        <span class="pfj-quicklink-label">Order Now</span>
        <span class="pfj-quicklink-arrow">↗</span>
      </div>
    </div>

    <!-- Offers section -->
    <div class="pfj-section-title">Today's Deals</div>

    <div class="pfj-offer-card">
      <div class="pfj-offer-img">🥤</div>
      <div class="pfj-offer-card-body">
        <div class="pfj-eyebrow">⏰ LIMITED-TIME OFFER</div>
        <div class="pfj-offer-title">BOGO Gatorade</div>
        <div class="pfj-offer-desc">Buy any Gatorade, get one free. This week only.</div>
        <span class="pfj-link-btn">See Offer →</span>
      </div>
    </div>

    <div class="pfj-offer-card">
      <div class="pfj-offer-img">🍕</div>
      <div class="pfj-offer-card-body">
        <div class="pfj-eyebrow">🍽️ MEAL DEAL</div>
        <div class="pfj-offer-title">$8 Lunch &amp; Dinner Deal</div>
        <div class="pfj-offer-desc">2 XL pizza slices + 20oz fountain drink.</div>
        <span class="pfj-link-btn">Order Now →</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("⚡  View My RoadIQ Journey Plan"):
        switch_screen("roadiq")
        st.rerun()
    render_tab_nav()


def render_find():
    st.markdown("""<div class="filter-row">
      <span class="filter-pill-outline">⚙️ Filters</span>
      <span class="filter-pill">Price: Diesel ▾</span>
      <span class="filter-pill-outline">Favorites</span>
    </div>""", unsafe_allow_html=True)

    from_city = st.text_input("From", value=st.session_state.route_from or "Nashville, TN", key="input_from")
    to_city = st.text_input("To", value=st.session_state.route_to or "Atlanta, GA", key="input_to")

    if st.button("🛣️  Route It"):
        st.session_state.route_from = from_city
        st.session_state.route_to = to_city
        st.session_state.route_calculated = True
        st.rerun()

    if st.session_state.route_calculated:
        from_coords = CITY_COORDS.get(st.session_state.route_from)
        to_coords = CITY_COORDS.get(st.session_state.route_to)

        if from_coords and to_coords:
            center = ((from_coords[0]+to_coords[0])/2, (from_coords[1]+to_coords[1])/2)
            m = folium.Map(location=center, zoom_start=7, tiles="CartoDB positron")

            route_coords = get_osrm_route(from_coords, to_coords)
            if route_coords:
                folium.PolyLine(route_coords, weight=4, color="#DC1730", opacity=0.8).add_to(m)

            folium.Marker(from_coords, tooltip=st.session_state.route_from,
                          icon=folium.Icon(color="red", icon="play", prefix="fa")).add_to(m)
            folium.Marker(to_coords, tooltip=st.session_state.route_to,
                          icon=folium.Icon(color="black", icon="flag-checkered", prefix="fa")).add_to(m)

            # Celonis live stops or fallback
            celonis_stops = get_celonis_stops(from_coords, to_coords)
            if celonis_stops:
                for stop in celonis_stops:
                    if stop["lat"] and stop["lng"]:
                        color = "red" if stop["is_pfj"] else "gray"
                        tip = f"{stop['brand']} — {stop['city']}, {stop['state']}"
                        popup = (f"<b>{stop['brand']}</b><br>{stop['address']}<br>"
                                 f"{stop['city']}, {stop['state']}<br>Diesel: {stop['diesel_brand']}")
                        folium.Marker([stop["lat"], stop["lng"]], tooltip=tip,
                                      popup=folium.Popup(popup, max_width=180),
                                      icon=folium.Icon(color=color, icon="gas-pump", prefix="fa")).add_to(m)
            else:
                for loc in locations.values():
                    is_pick = loc.get("name", "") == DEMO_DRIVER["recommended_stop"]
                    # Handle both Databricks and local JSON formats
                    if loc.get("source") == "databricks":
                        tip = f"{'⭐ ' if is_pick else ''}{loc['name']} — {loc.get('interstate', '')}"
                        popup_text = (
                            f"<b>{loc['name']}</b><br>{loc.get('address', '')}<br>"
                            f"{loc['city']}<br>Diesel: {loc.get('diesel_brand', '')}<br>"
                            f"{'🛋️ Lounge ' if loc.get('has_lounge') else ''}"
                            f"{'❄️ IdleAir ' if loc.get('has_idle_air') else ''}"
                            f"{'⛽ Mobile Fuel' if loc.get('has_mobile_fuel') else ''}"
                        )
                    else:
                        price = "$3.48" if loc.get("diesel_price_advantage") else "$3.75"
                        tip = f"{'⭐ ' if is_pick else ''}{loc['name']} — {price}"
                        popup_text = (
                            f"<b>{loc['name']}</b><br>{loc.get('city', '')}<br>"
                            f"Parking: {loc.get('parking_forecast_pct', 'N/A')}%<br>"
                            f"Shower: {loc.get('shower_wait_min', 'N/A')} min"
                        )
                    folium.Marker(
                        [loc["lat"], loc["lon"]],
                        tooltip=tip,
                        popup=folium.Popup(popup_text, max_width=180),
                        icon=folium.Icon(color="red" if is_pick or loc.get("is_pfj") else "gray", icon="gas-pump", prefix="fa"),
                    ).add_to(m)

            st_folium(m, width=350, height=300, returned_objects=[])

            rec_loc = get_location(DEMO_DRIVER)
            if rec_loc:
                st.markdown(f"""<div class="roadiq-pick">
                  <div class="pick-tag">⭐ RoadIQ Pick</div>
                  <div class="pick-name">{rec_loc['name']}</div>
                  <div class="pick-city">{rec_loc['city']}</div>
                  <div class="pick-stats">
                    <span class="stat-pill-good">🅿️ {rec_loc['parking_forecast_pct']}%</span>
                    <span class="stat-pill">🚿 {rec_loc['shower_wait_min']} min</span>
                    <span class="stat-pill">🍽️ {rec_loc['food_available']}</span>
                    <span class="stat-pill-good">⛽ Fleet deal</span>
                  </div></div>""", unsafe_allow_html=True)

            if st.button("✨  Get My RoadIQ Plan"):
                switch_screen("roadiq")
                st.rerun()
        else:
            st.warning("City not found. Try: Nashville, TN → Atlanta, GA")
    else:
        m = folium.Map(location=[35.5, -84.5], zoom_start=6, tiles="CartoDB positron")
        for loc in locations.values():
            folium.Marker([loc["lat"], loc["lon"]], tooltip=loc.get("name", "Pilot"),
                          icon=folium.Icon(color="red", icon="gas-pump", prefix="fa")).add_to(m)
        st_folium(m, width=350, height=300, returned_objects=[])
    render_tab_nav()

def render_roadiq():
    d = DEMO_DRIVER
    loc = get_location(d)
    name = d["name"].split()[0]

    st.markdown("""<div class="roadiq-header">
      <span class="roadiq-logo-sm">pilot</span>
      <span class="roadiq-header-text">RoadIQ — Your Journey</span>
    </div>""", unsafe_allow_html=True)

    st.markdown(f"""<div style="padding:0.5rem 0;display:flex;align-items:center;gap:0.4rem">
      <span style="font-weight:700;font-size:0.82rem">📍 {d['current_location']}</span>
      <span style="color:#DC1730;font-weight:900">→</span>
      <span style="font-weight:700;font-size:0.82rem">🏁 {d['destination']}</span>
    </div>""", unsafe_allow_html=True)

    fuel_pct = min(int(d["fuel_remaining_miles"] / 6), 100)
    fuel_color = "#DC1730" if fuel_pct < 25 else "#ff9800" if fuel_pct < 50 else "#4caf50"
    st.markdown(f"""<div style="margin:0.3rem 0 0.6rem">
      <div style="font-size:0.65rem;font-weight:700;color:#666;margin-bottom:0.2rem">FUEL LEVEL</div>
      <div style="background:#f0f0f0;border-radius:6px;height:7px;overflow:hidden">
        <div style="background:{fuel_color};height:100%;width:{fuel_pct}%;border-radius:6px"></div>
      </div>
      <div style="font-size:0.72rem;color:#333;margin-top:0.15rem;font-weight:600">{d['fuel_remaining_miles']} miles remaining</div>
    </div>""", unsafe_allow_html=True)

    if loc:
        from_coords = CITY_COORDS.get(d["current_location"])
        to_coords = CITY_COORDS.get(d["destination"])
        if from_coords and to_coords:
            center = ((from_coords[0]+to_coords[0])/2, (from_coords[1]+to_coords[1])/2)
            m = folium.Map(location=center, zoom_start=7, tiles="CartoDB positron")
            route_coords = get_osrm_route(from_coords, to_coords)
            if route_coords:
                folium.PolyLine(route_coords, weight=4, color="#DC1730", opacity=0.8).add_to(m)
            folium.Marker([loc["lat"], loc["lon"]], tooltip=f"⭐ {loc['name']}",
                          icon=folium.Icon(color="red", icon="star", prefix="fa")).add_to(m)
            folium.Marker(from_coords, tooltip=d["current_location"],
                          icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
            folium.Marker(to_coords, tooltip=d["destination"],
                          icon=folium.Icon(color="black", icon="flag-checkered", prefix="fa")).add_to(m)
            st_folium(m, width=350, height=200, returned_objects=[])

        st.markdown(f"""<div class="roadiq-pick">
          <div class="pick-tag">⭐ RoadIQ Recommended Stop</div>
          <div class="pick-name">{loc['name']}</div>
          <div class="pick-city">{loc['city']}</div>
          <div class="pick-stats">
            <span class="stat-pill-good">🅿️ {loc['parking_forecast_pct']}%</span>
            <span class="stat-pill">🚿 {loc['shower_wait_min']} min</span>
            <span class="stat-pill">🍽️ {loc['food_available']}</span>
            <span class="stat-pill-good">⛽ Fleet deal</span>
          </div></div>""", unsafe_allow_html=True)

    if st.session_state.journey_plan is None:
        if st.button("✨  Generate My Plan"):
            with st.spinner("RoadIQ is thinking..."):
                prompt = load_prompt("journey_optimizer.txt").format(
                    driver_name=name,
                    current_location=d["current_location"],
                    destination=d["destination"],
                    miles_remaining=250,
                    fuel_remaining_miles=d["fuel_remaining_miles"],
                    parking_need=d["parking_need"],
                    loyalty_tier=d["loyalty_tier"],
                    preferred_food=d["preferred_food"],
                    shower_needed="Yes" if d["shower_needed"] else "No",
                    vehicle_health=d["vehicle_health"],
                    stop_name=d["recommended_stop"],
                    stop_city=loc["city"] if loc else "",
                    parking_pct=loc["parking_forecast_pct"] if loc else "N/A",
                    shower_wait=loc["shower_wait_min"] if loc else "N/A",
                    food_available=loc["food_available"] if loc else "N/A",
                    price_advantage="Yes" if loc and loc["diesel_price_advantage"] else "No",
                )
                st.session_state.journey_plan = ask_ai(prompt, max_tokens=350)
                st.rerun()
    else:
        st.markdown(f"""<div class="ai-response">
          <div class="ai-label">RoadIQ Says</div>{st.session_state.journey_plan}
        </div>""", unsafe_allow_html=True)

    if st.button("← Back to Map"):
        switch_screen("find")
        st.rerun()
    render_tab_nav()


def render_chat():
    st.markdown("""<div class="roadiq-header">
      <span class="roadiq-logo-sm">pilot</span>
      <span class="roadiq-header-text">Ask RoadIQ</span>
    </div>""", unsafe_allow_html=True)

    st.markdown("<div style='font-size:0.75rem;color:#666;margin:0.4rem 0'>Ask anything about your route, stops, fuel, or what's ahead.</div>", unsafe_allow_html=True)

    # Quick-tap prompts
    qcols = st.columns(3)
    quick_prompts = [
        "I need fuel in 2 hours",
        "Best parking tonight?",
        "Fuel deal on my route?",
    ]
    for i, qp in enumerate(quick_prompts):
        with qcols[i]:
            if st.button(qp, key=f"qp_{i}"):
                st.session_state.chat_history.append({"role": "user", "text": qp})
                with st.spinner("..."):
                    d = DEMO_DRIVER
                    prompt = load_prompt("driver_chat.txt").format(
                        driver_name=d["name"].split()[0],
                        current_location=d["current_location"],
                        destination=d["destination"],
                        fuel_remaining_miles=d["fuel_remaining_miles"],
                        loyalty_tier=d["loyalty_tier"],
                        vehicle_health=d["vehicle_health"],
                        available_stops=stops_summary(),
                        driver_message=qp,
                    )
                    reply = ask_ai(prompt, max_tokens=250)
                    st.session_state.chat_history.append({"role": "ai", "text": reply})
                st.rerun()

    # Chat history
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"""<div style="background:#DC1730;border-radius:8px 8px 2px 8px;padding:0.55rem 0.8rem;margin:0.3rem 0;color:#fff;font-size:0.8rem">
              <div style="font-size:0.6rem;font-weight:800;color:rgba(255,255,255,0.7);margin-bottom:0.15rem">YOU</div>{msg['text']}</div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<div style="background:#f5f5f5;border-left:3px solid #DC1730;border-radius:2px 8px 8px 8px;padding:0.55rem 0.8rem;margin:0.3rem 0;font-size:0.8rem;line-height:1.5;white-space:pre-wrap">
              <div style="font-size:0.6rem;font-weight:800;color:#DC1730;margin-bottom:0.15rem">ROADIQ</div>{msg['text']}</div>""", unsafe_allow_html=True)

    # Input form
    with st.form("chat_form", clear_on_submit=True):
        user_input = st.text_input("Message", placeholder="e.g. I'm tired and need to stop soon", label_visibility="collapsed")
        submitted = st.form_submit_button("Send →")

    if submitted and user_input.strip():
        st.session_state.chat_history.append({"role": "user", "text": user_input})
        with st.spinner("RoadIQ is thinking..."):
            d = DEMO_DRIVER
            prompt = load_prompt("driver_chat.txt").format(
                driver_name=d["name"].split()[0],
                current_location=d["current_location"],
                destination=d["destination"],
                fuel_remaining_miles=d["fuel_remaining_miles"],
                loyalty_tier=d["loyalty_tier"],
                vehicle_health=d["vehicle_health"],
                available_stops=stops_summary(),
                driver_message=user_input,
            )
            reply = ask_ai(prompt, max_tokens=250)
            st.session_state.chat_history.append({"role": "ai", "text": reply})
        st.rerun()
    render_tab_nav()

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.screen == "home":
    render_home()
elif st.session_state.screen == "find":
    render_find()
elif st.session_state.screen == "roadiq":
    render_roadiq()
elif st.session_state.screen == "chat":
    render_chat()
