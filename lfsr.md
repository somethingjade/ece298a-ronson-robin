# Testing: LFSR state

Tested using cocotb. Resulting `tb.gtkw` file was analyzed using GTKWave and compared against [an existing Python implementation](https://github.com/joostrijneveld/readable-crypto).

Note that this was tested independently of the SPI module. SPONGENT-88 core pins were wired directly to top-level pins for testing purposes.

The Python implementation had to be slightly modified for the message to be absorbed properly. It is currently unknown if this is a quirk of SPONGENT, or if it is a bug in the Python implementation. Either way, this part of absorption is the responsibility of the caller.

cocotb waveform:\
![GTKWave screenshot of SPONGENT-88 state](embed/lfsr_state_gtkwave.py)\

Python implementation:\
![Screenshot of Python test script run output](embed/lfsr_state_python.py)\
