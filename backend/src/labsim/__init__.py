"""labsim: a simulated copy of the TRV/MAA lab, for working while the EVE-NG lab is not available.

It opens one telnet console per device on this laptop, on the same ports as EVE-NG, so AINOPS
reaches it exactly as it reaches the real lab (LAB_EVE_HOST=127.0.0.1). The answers are worked
out from a model of the network (lab.yaml) and the faults applied to it; nothing is a recording.

Rules:
- AINOPS never imports labsim (a test checks it): AINOPS only knows the consoles it talks to.
- It is a stand-in, not the lab: results from it are never shown as results from real devices
  (LAB_SIMULATED=true shows "simulated devices" in the UI).
"""
