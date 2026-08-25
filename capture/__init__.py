"""Live-race capture: record what the upstream API actually served, mid-race.

Finished results are not a substitute. They are cleaned and retroactively corrected: an
athlete who withdraws is erased from every earlier checkpoint, provisional times are
revised away, and mats that were briefly down leave no trace. So a completed race contains
no withdrawal *event*, no revision, and no outage -- exactly the situations a live dashboard
has to survive.

The only way to get honest fixtures is to record them while a race is running, which is why
this exists and why it ships before the dashboard does.
"""

__all__ = ["harness", "report"]
