# SPONGENT-88 Core Architecture

The SPONGENT-88 core module is implemented as a finite state machine (FSM) with 6 states:
- IDLE
- ABSORB
- LFSR
- SBOX
- PLAYER
- SQUEEZE

In parallel with the FSM, there is a 2-bit command register and a 4-bit counter, which counts the number of message bits received. There is also an 8-bit shift register for the output. There is a 6-bit counter that is reused throughout the design.

Once the first 2 message bits (the command bits) have been received, the command is immediately handled:
- `00` (write data)
    - If the current state is IDLE, transition to the ABSORB state
    - Otherwise, output an error (TODO: error codes)
- `01` (write control)
    - this isnt implemented yet :3
- `10` (read data)
    - this isnt implemented yet either yipeeeeeee
- `11` (read status)
    - The current status is determined combinationally, and the corresponding bits are placed into the output shift register

The remaining 8 bits of the message, if applicable, are handled in their corresponding states:
- Write data
    - The FSM transitions to the ABSORB state and the next 8 bits are absorbed into the SPONGENT-88 state
        - The 6-bit counter is used to count these bits

# References
[1] A. Bogdanov, M. Knezevic, G. Leander, D. Toz, K. Varici, I. Verbauwhede, "SPONGENT: A Lightweight Hash Function," in CHES 2011, 2011, pp. 312-325, doi: https://doi.org/10.1007/978-3-642-23951-9_21.
