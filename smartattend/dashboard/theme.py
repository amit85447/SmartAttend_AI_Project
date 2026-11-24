"""Dark / light theme via injected CSS (Streamlit's built-in theme can also be set in .streamlit/config.toml)."""
import streamlit as st

PALETTES = {
    "dark": dict(bg="#0E1525", card="#18223A", text="#E8EEF9", muted="#9AA8C7", accent="#4DA3FF", border="#2A3858"),
    "light": dict(bg="#F4F7FB", card="#FFFFFF", text="#14213D", muted="#5B6B8C", accent="#1F6FEB", border="#DCE3EF"),
}


def apply(mode: str):
    p = PALETTES[mode]
    st.markdown(f"""
<style>
.stApp {{ background:{p['bg']}; color:{p['text']}; }}
[data-testid="stSidebar"] {{ background:{p['card']}; border-right:1px solid {p['border']}; }}
h1,h2,h3,h4,p,label,span,div[data-testid="stMarkdownContainer"] {{ color:{p['text']}; }}
.kpi {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:14px; padding:16px 18px; }}
.kpi .v {{ font-size:28px; font-weight:700; color:{p['accent']}; line-height:1.1; }}
.kpi .l {{ font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:{p['muted']}; }}
.stButton button, .stDownloadButton button {{ background:{p['accent']}; color:#FFFFFF; border:0; border-radius:10px; }}
.stButton button p, .stDownloadButton button p {{ color:#FFFFFF; }}
header[data-testid="stHeader"] {{ background:{p['bg']}; }}
.badge-ok {{ color:#2ECC71; font-weight:600; }} .badge-bad {{ color:#FF5A5F; font-weight:600; }}
@media (max-width: 700px) {{ .kpi .v {{ font-size:22px; }} }}
</style>""", unsafe_allow_html=True)


def kpi(col, label, value, sub=""):
    p = PALETTES[st.session_state.get("theme", "dark")]
    col.markdown(f"<div class='kpi'><div class='l'>{label}</div><div class='v'>{value}</div>"
                 f"<div style='color:{p['muted']};font-size:12px'>{sub}</div></div>", unsafe_allow_html=True)
