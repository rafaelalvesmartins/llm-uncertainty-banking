# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""End-to-end integration tests.

Every test in this subpackage is marked ``@pytest.mark.integration``
(via ``tests/integration/conftest.py::pytestmark``). They exercise
cross-layer flows — estimator → pipeline → guard, benchmark → report,
conformal fit + reload + inference, drift detection windowed run-to-run,
CLI chain (``lub benchmark`` → ``lub report``), and every supported
report format produced from a single benchmark run.

Selectors:

* Fast loop (unit only):   ``pytest -m "not integration"``
* Full e2e (this subtree): ``pytest -m integration``
* Everything:              ``pytest``

All tests remain hermetic — no network, no real models — via
``DummyBackend`` and the registry snapshot in ``tests/conftest.py``.
"""
