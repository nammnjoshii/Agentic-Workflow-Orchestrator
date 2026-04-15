"""
config.py — Centralized environment configuration for the Agentic Workflow Orchestrator.

All agents should import client identity from here rather than reading os.environ directly.
This prevents drift and makes reconfiguration a single-file change.
"""
import os

CLIENT_NAME = os.environ.get("CLIENT_NAME", "Your Organization")
CLIENT_DESCRIPTION = os.environ.get("CLIENT_DESCRIPTION", "a data and analytics consultancy")
