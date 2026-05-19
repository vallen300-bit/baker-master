"""Forces ImportError to simulate hook env where anthropic SDK is not installed.

Mounted via PYTHONPATH by the pytest harness only when fixture mock.behavior
== "import_error". call_validator should degrade to PASS with
"anthropic SDK not installed in hook env" reason.
"""
raise ImportError("mocked: anthropic SDK not installed in hook env")
