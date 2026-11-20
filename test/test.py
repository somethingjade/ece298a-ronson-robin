
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from cocotbext.spi import SpiBus, SpiConfig, SpiMaster
import SPONGENT
import logging
import random

IDLE = 0b000;
ABSORB = 0b001;
LFSR = 0b010;
SBOX = 0b011;
PLAYER = 0b100;

WRITE_DATA = 0b00;
WRITE_CONTROL = 0b01;
READ_DATA = 0b10;
READ_STATUS = 0b11;

FSM_STATES = [IDLE, ABSORB, LFSR, SBOX, PLAYER]
FSM_STATES_NAMES = ["IDLE", "ABSORB", "LFSR", "SBOX", "PLAYER"]

def decode_status(byte):
    """
    Extracts the error, busy, and counter information from a value read in from SPI
    Args:
        byte: Value to be interpreted
    Returns:
        A tuple of 3, (error, busy, counter)
    """
    byte = byte & 0xFF
    error = (byte & (1 << 7)) != 0
    busy = (byte & (1 << 6)) != 0
    counter = byte & 0x3F
    return error, busy, counter

def encode_control(read_byte, pause_at, reset):
    return ((read_byte & 0xF) << 4) | ((pause_at & 0b111) << 1) | (reset & 0b1)

def generate_frame(command, data):
    return ((command & 0b11) << 14) | ((data & 0xFF) << 6)

async def read_entire_state(dut, spi_master):
    state = 0
    tx_data = []
    # we can read an invalid byte (11) to read the least significant byte without starting another permutation
    tx_data.append(generate_frame(WRITE_CONTROL, encode_control(11, 0, 0)))
    tx_data.append(generate_frame(READ_DATA, 0))
    for i in range(10):
        tx_data.append(generate_frame(WRITE_CONTROL, encode_control(i + 1, 0, 0)))
        tx_data.append(generate_frame(READ_DATA, 0))
    dut._log.debug(f"TX: {' '.join(f'{num:04x}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:02x}' for num in rx_data)}")
    assert len(rx_data) == 22
    for i in range(11):
        error, _busy, _counter = decode_status(rx_data[2*i])
        assert error == False
        state |= (rx_data[2*i + 1] << (8 * i))
    return state

async def write_data(dut, spi_master, data):
    tx_data = [generate_frame(WRITE_DATA, data & 0xFF)]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return decode_status(rx_data[0])

async def write_control(dut, spi_master, read_byte, pause_at, reset):
    tx_data = [generate_frame(WRITE_CONTROL, encode_control(read_byte, pause_at, reset))]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return decode_status(rx_data[0])

async def read_data(dut, spi_master) -> int:
    tx_data = [generate_frame(READ_DATA, 0)]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return rx_data[0]

async def read_status(dut, spi_master):
    tx_data = [generate_frame(READ_STATUS, 0)]
    dut._log.debug(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()
    dut._log.debug(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")
    assert len(rx_data) == 1
    return decode_status(rx_data[0])

async def wait_for_ready(dut, spi_master):
    error, busy, _ = await read_status(dut, spi_master)
    while busy and not error:
        error, busy, _ = await read_status(dut, spi_master)
    return not error

async def hash(dut, spi_master, msg, num_bytes):
    ret = 0
    msg = (msg << 8) | 0x80 # padding
    for i in reversed(range(num_bytes + 1)):
        byte = (msg >> (i*8)) & 0xFF
        await wait_for_ready(dut, spi_master)
        await write_data(dut, spi_master, byte)
    for _ in range(0, 11):
        await wait_for_ready(dut, spi_master)
        ret <<= 8
        ret |= await read_data(dut, spi_master)
    await wait_for_ready(dut, spi_master)
    return ret

def load_expected_values(dut, message_block):  
    # Create the Spongent-88 instance
    spongent = SPONGENT.SPONGENT(n=88, c=80, r=8, R=45)
    # Initial 88-bit state (all zeros)
    state = 0
    
    # 1. Absorb: XOR message into LSB 8 bits
    state ^= message_block 
    absorb_state = state
    # 2. Generate and apply round constants
    tmp = spongent.LFSR
    revLFSR = 0

    for _ in range(spongent.LFSRsize):
        revLFSR = (revLFSR << 1) | (tmp & 0x1)
        tmp >>= 1

    state ^= revLFSR << (spongent.r + spongent.c - spongent.LFSRsize)
    state ^= spongent.LFSR
    lsfr_state = state
    
    # 3. Advance LFSR
    spongent.lCounter()
    
    # 4. Apply S-box layer
    state = spongent.sBoxLayer(state)
    sbox_state = state
    dut._log.info(f"FULL: {state:022X}")
    dut._log.info(f"LSB: {bin(state & 0xFF)}")
    
    # 5. Apply pLayer
    state = spongent.pLayer(state)
    player_state = state
    dut._log.info(f"FULL: {state:022X}")
    dut._log.info(f"LSB: {bin(state & 0xFF)}")
    
    # Final 88-bit state after one round
    return [absorb_state, lsfr_state, sbox_state, player_state], spongent

def apply_next_round(spongent: SPONGENT.SPONGENT, previous_states: list):
    state = previous_states[-1]

    tmp = spongent.LFSR
    rev_lfsr = 0
    for _ in range(spongent.LFSRsize):
        rev_lfsr = (rev_lfsr << 1) | (tmp & 1)
        tmp >>= 1

    state ^= rev_lfsr << (spongent.r + spongent.c - spongent.LFSRsize)
    state ^= spongent.LFSR
    lfsr_state = state

    spongent.lCounter()
    state = spongent.sBoxLayer(state)
    sbox_state = state
    state = spongent.pLayer(state)

    return [previous_states[0], lfsr_state, sbox_state, state]


        

@cocotb.test()
async def test_project(dut):

    # Start system clock
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut._log.setLevel(logging.INFO)

    # Reset DUT
    dut._log.info("Reset")

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0

    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1

    # Initialize SPI bus
    spi_bus = SpiBus.from_prefix(dut, prefix="spi", cs_name="cs")

    spi_config = SpiConfig(
        sclk_freq=10000000,
        word_width=16,
        cpol=False,
        cpha=True,
        msb_first=True,
        cs_active_low=True
    )

    spi_master = SpiMaster(spi_bus, spi_config)
    
    # Allow CS_N to settle after reset
    await ClockCycles(dut.clk, 5)

    EXPECTED_STATE_LSBYTE = 0x98 # from existing implementation
    EXPECTED_STATE_MSBYTE = 0x8e # from existing implementation
    EXPECTED_STATE = 0x8eeeeeeeeeeeeeeeeeee98 # from existing implementation
    EXPECTED_STATE_END = 0xe95aa77a862489d1e04491 # from existing implementation

    TEST_VECTOR = 0x53706F6E6765202B2050726573656E74203D2053706F6E67656E74
    EXPECTED_HASH = 0x69971BF96DEF95BFC46822

    dut._log.info("")
    dut._log.info(">>> Test: Status read (ready)")
    error, busy, counter = await read_status(dut, spi_master)
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Status read (ready)")

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at absorb)")
    error, busy, counter = await write_control(dut, spi_master, 0, ABSORB, 0)
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (breakpoint at absorb)")

    dut._log.info("")
    dut._log.info(">>> Test: Absorb + status read (busy) + write while busy")
    error, busy, counter = await write_data(dut, spi_master, (0x67 << 1) | 0b1)
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Absorb")
    error, busy, counter = await read_status(dut, spi_master)
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Status read (busy)")
    error, busy, counter = await write_data(dut, spi_master, (0x99 << 1) | 0b1 << 6)
    assert error == True
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Write while busy")
    
    dut._log.info("")
    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at lfsr)")
    error, busy, counter = await write_control(dut, spi_master, 0, LFSR, 0)
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (breakpoint at lfsr)")

    dut._log.info("")
    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at sbox)")
    error, busy, counter = await write_control(dut, spi_master, 0, SBOX, 0)
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (breakpoint at sbox)")

    dut._log.info("")
    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at player)")
    error, busy, counter = await write_control(dut, spi_master, 0, PLAYER, 0)
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (breakpoint at player)")

    dut._log.info("")
    dut._log.info("Waiting 100 clock cycles")
    await ClockCycles(dut.clk, 100)

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at absorb)")
    error, busy, counter = await write_control(dut, spi_master, 0, ABSORB, 0)
    assert error == False
    assert busy == True
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (breakpoint at absorb)")

    dut._log.info("")
    dut._log.info(">>> Test: Control write (breakpoint at idle)")
    error, busy, counter = await write_control(dut, spi_master, 0, IDLE, 0)
    assert error == False
    assert busy == True
    # assert counter == 1
    dut._log.info(">>> PASSED: Control write (breakpoint at idle)")

    dut._log.info("")
    dut._log.info("Waiting for ready")
    await wait_for_ready(dut, spi_master)

    dut._log.info("")
    dut._log.info(">>> Test: Status read (ready)")
    error, busy, counter = await read_status(dut, spi_master)
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Status read (ready)")

    dut._log.info("")
    dut._log.info(">>> Test: Entire state")
    state = await read_entire_state(dut, spi_master)
    assert state == EXPECTED_STATE_END
    dut._log.info(">>> PASSED: Entire state")

    dut._log.info("")
    dut._log.info(">>> Test: Control write (reset)")
    error, busy, counter = await write_control(dut, spi_master, 0, IDLE, 1)
    assert error == False
    assert busy == False
    assert counter == 0
    dut._log.info(">>> PASSED: Control write (reset)")
    

    dut._log.info("")
    dut._log.info(">>> Test: hash test vector")
    hash_result = await hash(dut, spi_master, TEST_VECTOR, int(216/8))
    assert hash_result == EXPECTED_HASH
    dut._log.info(">>> PASSED: hash test vector")

    # DO NOT REMOVE THIS COMMENT
    # TODO: One of the test cases for testing spi should be mass write
    # right now, we use the helper function write_control and write_data, but they only perform
    # one byte write at a time, instead of writing all bytes in a single transaction
    # i.e. tx_data = [0x00, 0x01, 0x02, 0x03, ..., n_th byte]
    # read back n+1 bytes in a single transaction
    # This is important because the behavior of the cs_n signal may or may not be different on 
    # actual HW vs the simulation
    
    await ClockCycles(dut.clk, 20)
    dut._log.info("---------------- CHECKING WITH PYTHON IMPLEMENTATION ----------------")    
    
    component_states, spongent = load_expected_values(dut, message_block=(0x67 << 1) | 0b1)
    # component_states will be a list of size 4, [absorb, lfsr, sbox, player]
    
    
    # the function is defined here because it is not a helper function, and rather part of the test plan itself
    async def component_tests(dut, spi_master: SpiBus, message_block: int, component_states: list[int], reset_per_component: bool, permutation: bool):
        """
        A function that tests the system's breakpoint capabilities for the main internal spongent components: absorb, lfsr, sbox, player.
        In a single round, all 4 fsm_states will be paused at, read from, and compared to the expected values given from the Spongent implementation
        in python.
        Args:
            dut: 
            spi_master: the SpiBus being used for this dut
            message_block: an 8-bit message, with or without padding doesn't matter
            component_states: a list[int] of size 4 containing the the entire 88-bits of each fsm_state: absorb, lfsr, sbox, player
            reset_per_component: set to True if you want to reset the device for each possible breakpoint that can be tested. 
                            For example, the device will be reset when the breakpoint is set to lfsr, and when the breakpoint changes to sbox, the device 
                            will be reset again. Naturally, this requires us to re-absorb the message before we reach the sbox state. Setting this parameter
                            to True will only allow 1 round to run out of the 45 rounds per permutation.
            permutation: set this to True if you want all 45 rounds in the permutation to run. This means that for a single 8-bit data absorbed, 
                        45 rounds of lfsr->sbox->player will be performed. This is tested and implemented using the existing python implementation. 
        Returns:
            A tuple of 3, (error, busy, counter)
        """
        dut._log.info("\n\nReset\n\n")
        dut.ena.value = 1
        dut.ui_in.value = 0
        dut.uio_in.value = 0
        dut.rst_n.value = 0

        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 10)
                
        # When performing 45 rounds, we do not want to reset at each breakpoint
        reset_per_component = False if permutation else reset_per_component
        first_time_absorbing = True
        
        for cnt in range(45 if permutation else 1): # cnt is the counter tracking 45 rounds of permutation in the python implementation
            dut._log.info(f"\n----- Performing Round {cnt} -----")
            
            # For each possible fsm_state that can be paused
            for i in range(4): 
                if (cnt > 0 and i == 0):
                    # If not on the very first round, ignore the ABSORB STATE
                    continue
                
                if (reset_per_component):
                    dut._log.info("\n\nReset\n\n")
                    dut.ena.value = 1
                    dut.ui_in.value = 0
                    dut.uio_in.value = 0
                    dut.rst_n.value = 0

                    await ClockCycles(dut.clk, 5)
                    dut.rst_n.value = 1
                    await ClockCycles(dut.clk, 10)
                    
                # First step, set the break point at the correct location
                dut._log.info(f"\n----- SET BREAKPOINT AT {FSM_STATES_NAMES[i+1]} -----")
                dut._log.info(">>> Test: Control write")
                error, busy, counter = await write_control(dut, spi_master, 0, FSM_STATES[i+1], 0)
                assert error == False
                assert busy == False if reset_per_component else True
                if (cnt == 0):
                    assert counter == cnt 
                    # Note that when we change the breakpoint, the fsm_state and the counter do not change immediately.
                    # They change on the next clock cycle, but not fast enough to make it on the current miso output.
                    # As such, the fsm_state and the counter read from this write command would still be old values.
                    # However, this isn't a problem on the first round as the counter is already 0 anyways.
                    # As such, we need a seperate read/write command after we wait for one extra clock cycle.
                dut._log.info(f">>> PASSED: Control write for setting bp to {FSM_STATES_NAMES[i+1]}")
                
                await ClockCycles(dut.clk, 1)                
                
                # Second step, absorb a byte of data into the state registers once. Only permit re-absorbing at each breakpoint if you reset everything
                if (reset_per_component or first_time_absorbing): 
                    dut._log.info(f"\n>>> Test: Absorb + status read (busy)")
                    error, busy, counter = await write_data(dut, spi_master, message_block)
                    assert error == False
                    assert busy == False
                    assert counter == cnt
                    dut._log.info(">>> PASSED: Absorb")
                    error, busy, counter = await read_status(dut, spi_master)
                    assert error == False
                    assert busy == True
                    assert counter == cnt
                    dut._log.info(">>> PASSED: Status read (busy)")
                    first_time_absorbing = False
                    

                
                # Third step, try writing while the system is busy
                dut._log.info(f"\n>>> Test: Write while busy at {FSM_STATES_NAMES[i+1]}")
                error, busy, counter = await write_data(dut, spi_master, (0x99 << 1) | (1 << 6))
                assert error == True
                assert busy == True
                assert counter == cnt
                dut._log.info(f">>> PASSED: Write while busy at {FSM_STATES_NAMES[i+1]}")
                
                # Fourth step, read the LSByte from the state registers for this specific breakpoint (fsm_state)
                dut._log.info(f"\n>>> Test: Least significant byte of SPONGENT-88 state at {FSM_STATES_NAMES[i+1]}")
                rx_data = await read_data(dut, spi_master)
                assert rx_data == (component_states[i] & 0xFF)
                dut._log.info(f">>> PASSED: Least significant byte of SPONGENT-88 state at {FSM_STATES_NAMES[i+1]}")
                
                # Fifth step, read the LSByte from the state registers AGAIN to ensure state is not changing without any mosi input
                await ClockCycles(dut.clk, 10)
                dut._log.info(f"\n>>> Test: LSByte again after 10clck delay at {FSM_STATES_NAMES[i+1]}")
                rx_data = await read_data(dut, spi_master)
                assert rx_data == (component_states[i] & 0xFF)
                dut._log.info(f">>> PASSED: Least significant byte of SPONGENT-88 state at {FSM_STATES_NAMES[i+1]}")
                await ClockCycles(dut.clk, 10)
                    
            if (permutation):
                dut._log.debug("\nApplying next round to python implementation")
                dut._log.debug(f"Before: {component_states}")
                component_states = apply_next_round(spongent, component_states)
                dut._log.debug(f"After: {component_states}")
                    
    dut._log.info(f"\n---------------- RESET AT EACH BREAKPOINT, 1 ROUND ----------------")        
    await component_tests(dut, spi_master, (0x67 << 1) | 0b1, component_states, reset_per_component=True, permutation=False)
    dut._log.info(f"\n---------------- RESET ONCE, TRAVERSE EACH BREAKPOINT, 1 ROUND ----------------") 
    await component_tests(dut, spi_master, (0x67 << 1) | 0b1, component_states, reset_per_component=False, permutation=False)
    dut._log.info(f"\n---------------- PERMUTATION: 45 ROUNDS WITH BREAKPOINTS WITH PRE-SET INPUT ----------------") 
    await component_tests(dut, spi_master, (0x67 << 1) | 0b1, component_states, reset_per_component=False, permutation=True)
    
    # Try the full permutation with a randomly generated byte
    dut._log.info(f"\n---------------- PERMUTATION: BREAKPOINTS WITH RANDOM INPUT BYTE ----------------") 
    custom_random_byte = random.randint(0, 255)
    component_states, spongent = load_expected_values(dut, message_block=custom_random_byte)
    await component_tests(dut, spi_master, custom_random_byte, component_states, reset_per_component=False, permutation=True)
    

