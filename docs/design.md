# SPONGENT-88 Core Architecture

Refer to \[1\] for details about the SPONGENT algorithm

The SPONGENT-88 core module is implemented as a finite state machine (FSM) with 6 states:
- IDLE
- ABSORB
- LFSR
- SBOX
- PLAYER
- SQUEEZE

In parallel with the FSM, there is a 2-bit command register and a 4-bit counter, which counts the number of message bits received. There is also an 8-bit shift register for the output. There is a 6-bit counter that is reused throughout the design.

## Handling messages

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

By counting the number of received bits and using the FSM to determine how individual message bits are handled based on their index (see below FSM state descriptions for more details), we avoid needing a shift register for the entire message; we only need to store the 2-bit command, which controls FSM transitions.

## FSM design
- IDLE
    - This is the idle state. Transitions from this state are determined by the 2 command bits of the message (see above)
- ABSORB
    - Bits \[2:9\] of the message are absorbed directly into the SPONGENT-88 state
    - The 6-bit counter is used to count these bits and to determine the correct index to XOR the incoming bit into
    - THe FSM then transitions to the LFSR state
- LFSR
    - The LFSR is XOR'ed into the least significant 6 bits of the SPONGENT-88 state, and the reversed LFSR is XOR'ed into the most signficannt 6 bits
    - The LFSR is incremented - see \[1\] for the polynomial used
    - The FSM then transitions to the SBOX state
- SBOX
    - The S-box layer is applied serially; the S-box (which just substitutes nibbles for other nibbles) is applied to one nibble at a time
    - A 5-bit counter, counting from 0-21, is used to track which nibble is being processed
    - When the counter reaches 21, the next FSM state is assigned to PLAYER
- PLAYER
    - fill out when complete :3

# Status register
- Bit 7: Error
- Bit 6: Busy
- Bits \[5:0\]: Current round of the PRESENT-type permutation


# References
[1] A. Bogdanov, M. Knezevic, G. Leander, D. Toz, K. Varici, I. Verbauwhede, "SPONGENT: A Lightweight Hash Function," in CHES 2011, 2011, pp. 312-325, doi: https://doi.org/10.1007/978-3-642-23951-9_21.
