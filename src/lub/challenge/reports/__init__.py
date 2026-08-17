# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.reports -- assemble + render CEC reports.

Spec: planning/24_CEC_Spec_2026-04-25.md section 1.4 + section 4 steps 4-6.
"""

from __future__ import annotations

from lub.challenge.reports.cec_report import (
    CECReport,
    assemble_cec_report,
    render_markdown,
)
from lub.challenge.reports.oscal_export import to_oscal_assessment_results

__all__ = [
    "CECReport",
    "assemble_cec_report",
    "render_markdown",
    "to_oscal_assessment_results",
]
