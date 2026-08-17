# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Optional integrations with third-party ML platforms.

Each sub-module is independently importable and fails gracefully
when its platform dependency is not installed. No integration is
required to use the core library.

Available:
    - :mod:`lub.integrations.mlflow` — log UQ metrics + OSCAL as MLflow artifacts
    - :mod:`lub.integrations.langchain` — LangChain callback handler for UQ
"""
