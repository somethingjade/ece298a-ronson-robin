# Test plan

## Setup
1. Start cocotb system clock
2. Initialize cocotb SPI bus
    - Frequency: 10 MHz
    - Word width: 16 bits
    - `cpol = False`
    - `cpha = True`
    - MSB first
    - CS active low
3. Drive `ena = 1`
4. Hold `rst_n = 0` for 5 clock cycles
5. Release `rst_n = 1`
6. Wait 5 clock cycles for the SPI CS signal to settle

## Testing procedure

### Basic status and permutation tests

1. Status read after hard reset
    - Purpose: Ensure device is ready after reset
    - Procedure: Send the status read command
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

3. Read the entire initial state at ABSORB
    - Purpose: Preliminary check that the state can be read back using the read-data and write-control commands
    - Procedure:
        1. Select byte 11 with a write-control command to read the least-significant byte without starting another permutation
        2. Read byte 0
        3. For all bytes 1 through 10 inclusive, write-control commands select each byte before the corresponding read-data command
    - Expected output:
        - All write control commands output
            - `error == False`
            - `busy == False`
            - `counter == 0`
        - All read bytes are 0

4. Absorb a test byte
    - Purpose: Ensure data writes output expected values
    - Procedure:
        1. Send write-data command with `0x67 << 1 | 1`
        2. Read status immediately
        3. Attempt a write-data command while the device is busy
    - Expected output:
        - Absorb write: `error == False`, `busy == False`, `counter == 0`
        - Busy status: `error == False`, `busy == True`, `counter == 0`
        - Write while busy: `error == True`, `busy == True`, `counter == 0`

5. Read state after absorption
    - Purpose: Ensure bytes can be XORed into the state and that the ABSORB breakpoint works
    - Procedure:
        1. Absorb the test byte using the SPONGENT.py implementation without applying permutation rounds
        2. Read the entire 88-bit state
    - Expected output:
        - Both implementations have identical states

6. Increment breakpoints through LFSR, SBOX, PLAYER, and ABSORB
    - Purpose: Exercise stage breakpoints and waiting behavior
    - Procedure:
        1. For each stage in the order LFSR, SBOX, PLAYER, ABSORB:
            - Write to the control register with `read_byte = 0`, `pause_at = stage`, and `reset = 0`
            - Wait 100 clock cycles
        2. Wait an additional full permutation interval, then set the breakpoint to IDLE
    - Expected output:
        - `error == False`
        - `busy == True` for the stage breakpoints
        - `counter == 0`

7. Read status and counter after the permutation
    - Purpose: Ensure the device reports ready and resets the round counter
    - Procedure:
        1. Write to control register:
            - `read_byte = 0`
            - `pause_at = IDLE`
            - `reset = 0`
        2. Busy-wait using status reads until the device is ready
        3. Send another status read
    - Expected output:
        - `error == False`
        - `busy == False`
        - `counter == 0`

8. Check state after the completed permutation
    - Purpose: Ensure the state remains consistent after all 45 permutation rounds
    - Procedure:
        1. Read the entire state with IDLE
    - Expected output:
        - State equals `0xe95aa77a862489d1e04491`

9. Check control-register soft reset
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

### Component functional testing

SPONGENT.py is used to calculate the exact 88-bit state at the ABSORB, LFSR, SBOX, and PLAYER stages.

10. Reset at every breakpoint
    - Purpose: Test each stage independently in one round
    - Procedure:
        1. Hard-reset the device
        2. For ABSORB, LFSR, SBOX, and PLAYER:
            - Hard-reset again before each stage
            - Set the breakpoint
            - Absorb the test byte
            - Read status and attempt a write while busy
            - Read the entire state and compare it with SPONGENT.py
            - Wait 10 clock cycles and verify the least-significant byte is unchanged

11. Traverse all breakpoints after one reset
    - Purpose: Verify one round while changing breakpoints without resetting between stages
    - Procedure:
        1. Hard-reset once
        2. For ABSORB, LFSR, SBOX, and PLAYER:
            - Set the breakpoint
            - Absorb the test byte only on the first stage
            - Attempt a write while busy
            - Read the entire state and compare it with SPONGENT.py

12. Run all 45 rounds using breakpoints
    - Purpose: Verify the full permutation stage-by-stage against SPONGENT.py
    - Procedure:
        1. Hard-reset and absorb the test byte
        2. For every round 0 through 44:
            - In round 0, check ABSORB, LFSR, SBOX, and PLAYER
            - In rounds 1 through 44, check LFSR, SBOX, and PLAYER
            - Read the full 88-bit state at each reached stage
            - Advance the Python implementation to the next round
        3. Repeat the test with a randomly generated byte from 0 through 255
    - Expected output:
        - Every device state equals the Python implementation
        - The ABSORB/LFSR/SBOX/PLAYER control writes return no error
        - Writes while busy return `error == True` and `busy == True`
        - Counter values remain 0 or match the Python round index during round testing
        - Each 45-round breakpoint run completes within 30 seconds

### System functional and behavior tests

13. Hash the known test vector after hard reset
    - Purpose: Verify the complete padded-message and digest operation
    - Procedure:
        1. Pad the test vector with `0x80` in the least-significant-byte position
        2. Send bytes from most significant to least significant
        3. Busy-wait until ready before each write
        4. Read 11 digest bytes, most significant first
        5. Compare the assembled digest
    - Expected output:
        - Test vector: `0x53706F6E6765202B2050726573656E74203D2053706F6E67656E74`
        - Expected digest: `0x69971BF96DEF95BFC46822`
        - Hash operation completes within 10 seconds

14. Check corrupted state behavior
    - Purpose: Confirm that a second hash without resetting does not reuse the empty initial state
    - Procedure:
        1. Run the known test vector again without a reset
    - Expected output:
        - The returned hash does not equal `0x69971BF96DEF95BFC46822`

15. Soft-reset and known hash
    - Purpose: Verify that soft reset clears the state and allows a correct hash
    - Procedure:
        1. Write control with `pause_at = IDLE` and `reset = 1`
        2. Read the entire state and assert it is zero
        3. Read the least-significant byte and assert it is zero
        4. Trigger squeeze and wait for ready
        5. Read the state and assert it equals `0x7CC08139EB7F16CFCEF382`
        6. Soft-reset again
        7. Run the known test vector
    - Expected output:
        - Reset status reports ready with counter zero
        - Cleared state is zero
        - Squeeze state matches the Python implementation
        - The known hash equals `0x69971BF96DEF95BFC46822`

16. Random-size and random-value hashes
    - Purpose: Compare the device against SPONGENT.py for varied byte-aligned messages
    - Procedure:
        1. Repeat 10 times:
            - Soft-reset
            - Choose a random byte-aligned size from 1 through 11 bytes
            - Generate a random message of that size
            - Calculate the Python implementation hash
            - Run the hash helper on the device
    - Expected output:
        - Each device hash equals the Python implementation hash

### Negative testing

17. Invalid breakpoint
    - Purpose: Verify that an out-of-range breakpoint is handled
    - Procedure:
        1. Hard-reset
        2. Write control with `pause_at = 7`
        3. Read the entire state
        4. Repeat 10 status-and-squeeze-read sequences
        5. Read the entire state again
    - Expected output:
        - State remains zero
        - `read_data()` returns zero for every squeeze attempt

18. Control fields passed through arbitrary read-data data
    - Purpose: Verify that `read_data()` does not change control behavior
    - Procedure:
        1. Issue reads using arbitrary encode-control values
        2. Check zero-state and permutation values
        3. Continue permutation operations using data values that resemble control frames
    - Expected output:
        - The first read sees the correct initial state
        - Subsequent reads match the Python-permuted states
        - No write-control behavior is triggered by arbitrary read-data payloads

19. Arbitrary status-read data
    - Purpose: Verify that `read_status()` ignores control-like data fields
    - Procedure:
        1. Soft-reset
        2. Read status and state around a permutation
        3. Issue status reads with arbitrary encode-control payloads
    - Expected output:
        - Status remains valid
        - The permutation can become busy and later return to ready
        - Status reads do not trigger soft reset or breakpoint behavior

## References
\[1\] A. Bogdanov, M. Knezevic, G. Leander, D. Toz, K. Varici, I. Verbauwhede, "SPONGENT: A Lightweight Hash Function," in CHES 2011, 2011, pp. 312-325, doi: https://doi.org/10.1007/978-3-642-23951-9_21.