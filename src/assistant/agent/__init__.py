"""LLM client and tool-calling orchestration loop.

Framework-agnostic: no FastAPI. The LLM never accesses the database or the
services directly - it only sees tool definitions and tool results (see
assistant.tools).
"""
