"""Theme registry. The actual colours live in static/css/themes.css (data-theme attribute)."""

THEMES = {
    "ocean": {"name": "Ocean Blue", "desc": "Clean and trustworthy", "mode": "Light",
              "swatch": ["#2563eb", "#06b6d4", "#f4f7fb"]},
    "emerald": {"name": "Emerald Campus", "desc": "Fresh and calm", "mode": "Light",
                "swatch": ["#059669", "#f59e0b", "#f3f8f5"]},
    "royal": {"name": "Royal Purple", "desc": "Modern and creative", "mode": "Light",
              "swatch": ["#7c3aed", "#ec4899", "#f6f4fb"]},
    "sunset": {"name": "Sunset Orange", "desc": "Warm and energetic", "mode": "Light",
               "swatch": ["#ea580c", "#eab308", "#fbf6f1"]},
    "rose": {"name": "Rose Garden", "desc": "Soft and friendly", "mode": "Light",
             "swatch": ["#e11d48", "#8b5cf6", "#fbf4f6"]},
    "graphite": {"name": "Graphite", "desc": "Minimal and formal", "mode": "Light",
                 "swatch": ["#1f2937", "#6366f1", "#f5f5f6"]},
    "midnight": {"name": "Midnight", "desc": "Easy on the eyes", "mode": "Dark",
                 "swatch": ["#818cf8", "#22d3ee", "#0f172a"]},
}

THEME_CHOICES = [(k, v["name"]) for k, v in THEMES.items()]
DEFAULT_THEME = "ocean"
