# Firewall outputs for the security-zone tests

Laid out like `fixtures/lab` so the replay executor can read them, one folder per scenario.

| File | Where it comes from |
|---|---|
| no-zones/FWL-MAA/show-interfaces-terse-display-json.txt | live lab, 2026-10-07 (ge-0/0/0 and ge-0/0/1 have addresses) |
| no-zones/FWL-MAA/show-security-zones-display-json.txt | HAND-WRITTEN in the `\| display json` shape: zones with no interfaces, as the lab firewalls were set up on 10-07. Replace it with a live recording (`uv run python -m ainops capture`) when the lab answers. |
