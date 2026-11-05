# ASAP7 estimate: core and L1 caches

A pre-layout estimate, not a chip result. Yosys maps `cpu` (the core and its L1 caches) to ASAP7 standard cells, three small
scripts buffer, size and swap thresholds, and OpenSTA times the result at the typical corner, 0.7 V, against a bare 1 GHz
clock. There are no wires, clock tree or skew, and the RAM macros are placeholder models with placeholder timing.

| File | Contents |
|---|---|
| `timing.rpt` | OpenSTA: worst setup slack, endpoint counts by slack, and the worst path |
| `area.rpt` | cell counts and area by cell type after mapping |
| `flow.rpt` | the sizing passes at 30 ps uncertainty, the threshold mix, and area split into RAM, logic, flops and buffers |

The netlist itself isn't published. How the flow works: https://jsnhynh.github.io/orca/bringup/asic-synthesis.html
