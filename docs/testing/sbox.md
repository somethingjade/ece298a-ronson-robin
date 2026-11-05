# Testing: sBox state

Tested using cocotb. Resulting `tb.gtkw` file was analyzed using GTKWave and compared against [an existing Python implementation](https://github.com/joostrijneveld/readable-crypto).

Note that this was tested independently of the SPI module. SPONGENT-88 core pins were wired directly to top-level pins for testing purposes.

The Python implementation had to be slightly modified for the message to be absorbed properly. It is currently unknown if this is a quirk of SPONGENT, or if it is a bug in the Python implementation. Either way, this part of absorption is the responsibility of the caller.

The state after one application of the sBox layer was verified against the Python implementation.

The FSM state also transitions to the pLayer state, encoded as `0b100`, as intended. The sBox layer is serialized; the counter counts up to `0x15` (21), corresponding to the 22 nibbles making up the 88-bit state, before resetting to 0 and transition to the pLayer state as intended.

cocotb waveform:
![GTKWave screenshot of SPONGENT-88 state](embed/sbox_state_gtkwave.png)

Python implementation:
![Screenshot of Python test script run output](embed/sbox_state_python.png)
