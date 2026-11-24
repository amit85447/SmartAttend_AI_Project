"""Browser geolocation bridge for Streamlit.

The browser asks the user for permission (a popup). Nothing is read without it. Requires HTTPS or
localhost. Returns GpsFix, or a string explaining why no fix is available.
"""
from services.geo import GpsFix


def request_browser_gps(key: str = "gps"):
    """Call inside a Streamlit page. Returns (GpsFix | None, message)."""
    from streamlit_js_eval import get_geolocation
    data = get_geolocation(component_key=key)
    if data is None:
        return None, "Waiting for location. Click Allow when the browser asks for permission."
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return None, f"Location unavailable: {msg}. Allow location access in your browser settings (and use HTTPS)."
    coords = (data or {}).get("coords")
    if not coords or coords.get("latitude") is None:
        return None, "Browser did not return coordinates."
    return GpsFix(float(coords["latitude"]), float(coords["longitude"]),
                  float(coords.get("accuracy") or 0), data.get("timestamp"), "browser_gps"), "GPS fix received"
