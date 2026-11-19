# Test plan

## Setup
1. Start cocotb system clock
2. Initialize cocotb SPI bus
    - Frequency: 10 MHz
    - Word width: 16 bits
    - `cpol = False`
    - `chpa = True`
    - MSB first
    - CS active low

## Testing procedure
1. Status read after reset
    - Purpose: Ensure device is ready after reset
    - Procedure:
        1. Set `rst_n = 0`
        2. Wait 5 clock cycles
        3. Set `rst_n = 1`
        4. Wait 5 clock cycles
        5. Send status read command
    - Expected output:
        - `error == False`
        - `busy == False`
        - `counter == 0`
2. Set breakpoint to absorb
    - Purpose: Verify that the device responds to writes to the control register
    - Procedure:
        1. Write to control register:
            - `read_byte = 0`
            - `pause_at = ABSORB`
            - `reset = 0`
    - Expected output
        - `error == False`
        - `busy == False`
        - `counter == 0`
3. Read the entire state
    - Purpose: Preliminary check that the state can be read back using the read data and write control commands
    - Procedure:
        1. For byte 0, send a write control command to select byte 11 for reading (an invalid byte index will select byte 0 without starting another round of permutations)
        2. Read byte 0
        3. For all bytes b from 1 to 10 inclusive, send a write control command to select byte b for reading, and read byte b
    - Expected output:
        - All write control commands output
            - `error == False`
            - `busy == False`
            - `counter == 0`
        - All read bytes are 0
4. Absorb a random byte
    - Purpose: Ensure data writes output expected values
    - Procedure:
        1. Randomly generate a value between 0-255
        2. Send a write data command with this value
        3. Wait 100 clock cycles
    - Expected output:
        - `error == False`
        - `busy == False`
        - `counter == 0`
5. Read state after absorbing
    - Purpose: Ensure bytes can be XOR'ed into the state properly, and that the breakpoint is working as intended
    - Procedure:
        1. Absorb using the SPONGENT.py implementation, but do not perform permutation rounds
        2. As done in test 3, read the entire state
    - Expected output:
        - Both implementations have identical states
6. Read status after absorbing
    - Purpose: Ensure the device correctly reports a `busy` status
    - Procedure:
        1. Send status read command
    - Expected output:
        - `error == False`
        - `busy == True`
        - `counter == 0`
7. Attempt write while busy
    - Purpose: Ensure the device correctly reports an `error` status
    - Procedure:
        1. Send write data command with any data
    - Expected output:
        - `error == True`
        - `busy == True`
        - `counter == 0`
8. Increment breakpoint
    - Purpose: Ensure all stages of the permutation are working as intended
    - Procedure:
        - In order, for each stage `s` of `LFSR`, `SBOX`, and `PLAYER`:
            1. Write to control register:
                - `read_byte = 0`
                - `pause_at = s`
                - `reset = 0`
            2. Wait 100 clock cycles
            3. Perform `s` using the SPONGENT.py implementation
            4. As done in test 3, read the entire state
    - Expected output:
        - Both implementations have identical states throughout
        - Control register write outputs:
            - `error == False`
            - `busy == True`
            - `counter == 0`
9. Read counter
    - Purpose: Ensure the device correctly reports its counter
    - Procedure:
        1. Write to control register:
            - `read_byte = 0`
            - `pause_at = IDLE`
            - `reset = 0`
        2. Send status read command
    - Expected output:
        - `error == False`
        - `busy == True`
        - `counter > 0 && counter < 45`
10. Wait for remaining rounds to complete
    - Purpose: Ensure all rounds of the permutation complete without issue
    - Procedure:
        - Repeat until either status reports ready (`!busy`) or 10 total seconds have elapsed:
            1. Send status read command
            2. Wait 1 second
    - Expected output:
        - Within 10 seconds, the device reports ready
11. Check state
    - Purpose: Ensure the state remains consistent with the existing implementation after all 45 permutation rounds
    - Procedure:
        1. Absorb the same random value from test 4 using the SPONGENT.py implementation, performing all permutation rounds
        2. As done in test 3, read the entire state
    - Expected output:
        - Both implementations have identical states
12. Check control register reset
    - Purpose: Ensure the control register can be used to reset the device
    - Procedure:
        1. Write to control register:
            - `read_byte = 0`
            - `pause_at = IDLE`
            - `reset = 1`
        2. Send status read command
    - Expected output:
        - `error == False`
        - `busy == False`
        - `counter == 0`
13. Read state after reset
    - Purpose: Ensure the state is properly cleared after software reset
    - Procedure:
        1. As done in test 3, read all bytes of the state
    - Expected output:
        - All read bytes are 0
14. Test hash with known test vector
    - Purpose: Ensure the device can produce the correct hash for a known test vector
    - Procedure:
        1. Pad the known test vector with `0x80` in the least significant byte position
            - This is described in \[1\]
            - Test vector:
                - String: "Sponge + Present = Spongent"
                - Hex: 0x53706F6E6765202B2050726573656E74203D2053706F6E67656E74
        2. Starting from the most significant byte:
            - Busy-wait using the read status command for the device to be ready
            - Write one byte at a time using the write data command
        3. Repeat 11 times:
            - Busy-wait using the read status command for the device to be ready
            - Use the read data command to read the next byte of the digest (bytes will be read most significant byte first)
        4. Confirm that the digest matches the expected value:
            - Expected digest: 0x69971BF96DEF95BFC46822

## References
\[1\] A. Bogdanov, M. Knezevic, G. Leander, D. Toz, K. Varici, I. Verbauwhede, "SPONGENT: A Lightweight Hash Function," in CHES 2011, 2011, pp. 312-325, doi: https://doi.org/10.1007/978-3-642-23951-9_21.
