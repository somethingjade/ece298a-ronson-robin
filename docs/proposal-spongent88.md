# Proposal: SPONGENT-88 Accelerator

This is the [original paper](https://link.springer.com/chapter/10.1007/978-3-642-23951-9_21).

This has [previously been done on TinyTapeout](https://tinytapeout.com/chips/ttihp26a/tt_um_spongent88). This implementation took 2x2 cells though. According to the paper, SPONGENT-88 can be implemented with 738 GE. According to some people on the TT Discord server ([1](https://discord.com/channels/1009193568256135208/1509616280993533982/1510065328191967393), [2](https://discord.com/channels/1009193568256135208/1442605676508741662/1446188498842292234)), one cell is ~1000 GE, so it should theoretically be possible to fit SPONGENT-88 on one cell.

There are a number of obvious space optimizations that can be made compared to the past TT design. The past design has hardware to apply 2 rounds of the PRESENT-type permutation in parallel; we plan on only doing 1. The past design stores 3 copies of the state, which results in 3 88-bit registers; we plan on only having one copy.

The device would interface with a host via SPI.
Input/output would be processed byte-by-byte. This minimizes the number of registers needed to store input.
A status register would be readable to identify whether a result is ready, and a protocol for commands (TBD) would allow for "start" and "read" instructions.
