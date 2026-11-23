"""Restricted, serial source acquisition. No ingestion or citation fetching."""

from .http import HttpClient
from .registry import SOURCES, PolicyError, SourceRegistry

__all__ = ["HttpClient", "SOURCES", "PolicyError", "SourceRegistry"]
