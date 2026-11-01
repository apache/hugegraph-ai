# FMEA — IO Ring & ESD Protection (DSG-201)

Module: DSG-201
Project: X1
Design owner: Analog & IO
Revision: DFMEA-2026-07
Linked requirement: REQ-101 (IO ESD robustness ±8kV contact discharge)
Scope: pad ring ESD clamp network, IO buffers and LVDS receiver front-ends of the X1 project, from incoming wafer sort to board-level handling at the customer.

## Failure mode effects analysis

The table below is the living core of this document. RPN = S × O × D.
Severity (S), occurrence (O) and detection (D) are scored 1–10 per the
automotive QA scoring guide; any RPN above 100 requires a containment action
before the affected lot is released to shipment.

| FMEA ID | Failure mode | Cause | Effect | S | O | D | Recommended action |
|---|---|---|---|---|---|---|---|
| FM-DSG201-01 | ESD latch-up above 8kV contact discharge | Clamp footprint sized exactly to the ±8kV requirement, no margin | Port latches low; field return at the customer | 8 | 4 | 3 | Resize clamp to ±12kV margin in TO-A1; enforce wrist-strap handling SOP at board assembly |
| FM-DSG201-02 | IO leakage above 10 nA at 25 °C | Etch window offset on the guard ring | Signal integrity loss in low-power modes; CP bin loss | 7 | 3 | 5 | Etch equipment window check per lot; SPC chart on leakage bins at CP |
| FM-DSG201-03 | Ground bounce during simultaneous switching | Insufficient on-die decoupling on the IO rail | Data errors in burst mode; intermittent field complaints | 6 | 4 | 4 | Add on-die decap in the next metal spin; restrict simultaneous switching groups in firmware |
| FM-DSG201-04 | ESD protection diode early wear-out | Thin gate oxide stressed beyond spec during ESD events | Parametric drift after 1000 h operation | 7 | 2 | 4 | Burn-in sampling per lot; monitor HTOL data monthly |
| FM-DSG201-05 | IO pad corrosion | Under-plated pad metallization from the fab | Contact resistance rise; opens at the customer | 5 | 3 | 3 | Incoming plating thickness audit per fab lot |
| FM-DSG201-06 | Latch-up during burn-in screening | Substrate current injection at elevated temperature | Destruction during screening; lot yield loss | 9 | 2 | 3 | Latch-up test per AEC-Q100 before release; current-limited burn-in sockets |
| FM-DSG201-07 | Missing ESD characterization record | Test coverage gap on port bank B | Traceability block at customer PPAP | 5 | 3 | 2 | Gate lot release on a complete characterization report |

## Detection coverage

Leakage bins at CP cover FM-DSG201-02 and FM-DSG201-04 on every unit.
TLP (transmission line pulse) characterization per tapeout version covers
FM-DSG201-01; latch-up testing per AEC-Q100 covers FM-DSG201-06 on a sample
of each lot. FM-DSG201-03 is detected only at the customer today — the
recommended decap change closes that gap.

## Containment rules

- Any RPN above 100 requires a containment action before lot release.
- Any field failure matching a listed failure mode must be traced to its
  wafer lot before a root cause is recorded.
- When a failure mode is confirmed in the field, the linked requirement
  margin must be re-reviewed by the design owner within five working days.

Prepared by: Manufacturing Quality. Reviewed with Core Design and the fab
process integration team.
