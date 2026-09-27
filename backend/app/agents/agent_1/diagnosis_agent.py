"""
TeslaLab AI — Diagnosis Agent Bridge for app.agents.agent_1.
"""

try:
    from backend.agents.agent_1.diagnosis_agent import DiagnosisAgent
except (ImportError, ModuleNotFoundError):
    from agents.agent_1.diagnosis_agent import DiagnosisAgent

__all__ = ["DiagnosisAgent"]
