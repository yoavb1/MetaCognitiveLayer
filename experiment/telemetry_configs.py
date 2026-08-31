"""

Centralized metadata and presentation configuration mapping for experimental datasets.
Provides dynamic schema parameters for Django views, template rendering, and WebSocket streams.
"""

DATASET_CONFIGS = {
    # 10-Variable Tennessee Eastman Process (TEP) Configuration
    "TEP_10VARS": {
        "title": "Tennessee Eastman Process (10-Variable Subset)",
        "description": "Standard industrial process benchmark monitoring 10 selected process variables.",
        "sensors": [
            {"key": "Feed_Flow_A", "label": "Feed Flow A", "tag": "XMEAS(1)", "unit": "kkg/h", "color": "#38bdf8"},
            {"key": "Reactor_Pressure", "label": "Reactor Pressure", "tag": "XMEAS(7)", "unit": "kPa",
             "color": "#f43f5e"},
            {"key": "Reactor_Level", "label": "Reactor Level", "tag": "XMEAS(8)", "unit": "%", "color": "#fbbf24"},
            {"key": "Reactor_Temp", "label": "Reactor Temp", "tag": "XMEAS(9)", "unit": "°C", "color": "#a855f7"},
            {"key": "Separator_Temp", "label": "Separator Temp", "tag": "XMEAS(11)", "unit": "°C", "color": "#34d399"},
            {"key": "Separator_Level", "label": "Separator Level", "tag": "XMEAS(12)", "unit": "%", "color": "#f97316"},
            {"key": "Stripper_Level", "label": "Stripper Level", "tag": "XMEAS(15)", "unit": "%", "color": "#06b6d4"},
            {"key": "Stripper_Temp", "label": "Stripper Temp", "tag": "XMEAS(18)", "unit": "°C", "color": "#ec4899"},
            {"key": "Reactor_Coolant_Valve", "label": "Reactor Coolant Valve", "tag": "XMV(10)", "unit": "%",
             "color": "#8b5cf6"},
            {"key": "Separator_Coolant_Valve", "label": "Separator Coolant Valve", "tag": "XMV(11)", "unit": "%",
             "color": "#10b981"}
        ],
    }
}


def get_dataset_config(dataset_type: str = "TEP_10VARS") -> dict:
    """
    Safely retrieves the metadata configuration for a given dataset type.
    Falls back to 'TEP_10VARS' if the specified key does not exist.
    """
    return DATASET_CONFIGS.get(dataset_type, DATASET_CONFIGS["TEP_10VARS"])