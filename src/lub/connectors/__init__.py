"""LUB Connectors — plug-in banking applications.

Each connector adapts the LUB uncertainty framework to a specific
banking platform. The Bridge connector implements Bradesco's
multi-agent AI platform.

Usage:
    from lub.connectors.bridge import BridgePlatform
    from lub.connectors.bridge.agents import ChatbotAgent
"""

__all__ = ["bridge"]
